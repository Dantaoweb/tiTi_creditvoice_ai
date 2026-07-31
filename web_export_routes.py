"""
Export routes: token-based + authenticated CSV export, and loan-statement PDF
(token-based public download + authenticated generation).

Split out of web_routes.py. Register with register_export_routes(app);
shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from database import SessionLocal
from models import User, Transaction, Customer, InventoryItem
from web_auth import require_web_auth
from web_common import _session_owner_phone, _safe_filename, _money


def register_export_routes(app):

    @app.get("/app/api/export/dl/{token}")
    def web_export_download(token: str):
        """Public token-based CSV download — for WhatsApp download links."""
        from export_utils import build_export_csv, verify_export_token
        info = verify_export_token(token)
        if not info:
            raise HTTPException(status_code=410, detail="This export link has expired or is invalid.")
        db = SessionLocal()
        try:
            filename, csv_bytes = build_export_csv(db, info["phone"], info["period"], info["type"])
            return StreamingResponse(
                iter([csv_bytes]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/export")
    def web_export_authenticated(
        export_type: str = Query(default="transactions"),
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str] = Query(default=None),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """Authenticated CSV export for the web dashboard."""
        from admin import is_app_admin
        from export_utils import build_export_csv
        db = SessionLocal()
        try:
            session_phone = _session_owner_phone(db, session)
            user = db.query(User).filter(User.id == session["user_id"]).first()
            # Admins may export any phone; everyone else is bound to their own business
            if owner_phone and user and is_app_admin(user.phone, db):
                phone = owner_phone
            else:
                phone = session_phone
            period_key = period.upper() if period else None
            filename, csv_bytes = build_export_csv(db, phone, period_key, export_type, branch_id=branch_id)
            return StreamingResponse(
                iter([csv_bytes]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/loan-statement/dl/{token}")
    def web_statement_download(token: str):
        """Public token-based PDF download — used in WhatsApp download links."""
        from export_utils import verify_export_token
        from loan_statement import generate_loan_statement
        from reports import (
            get_dashboard_summary, get_unpaid_debtors,
            get_owner_transaction_query, dashboard_period_label,
        )
        payload = verify_export_token(token)
        if not payload or payload.get("type") != "loan_statement":
            raise HTTPException(status_code=403, detail="Invalid or expired statement link.")

        phone      = payload["phone"]
        period_key = payload.get("period") or None

        db = SessionLocal()
        try:
            owner_user = db.query(User).filter(User.phone == phone).first()
            if not owner_user:
                raise HTTPException(status_code=404, detail="Business not found.")

            owner = {
                "name":               owner_user.name or phone,
                "phone":              phone,
                "business_type_label": owner_user.business_type_label,
                "business_category":  owner_user.business_category,
            }
            summary        = get_dashboard_summary(db, owner_phone=phone, period=period_key)
            debtors_raw, _ = get_unpaid_debtors(db, owner_phone=phone)
            period_lbl     = dashboard_period_label(period_key) if period_key else "all time"

            tx_rows = (
                get_owner_transaction_query(db, phone, period_key)
                .order_by(Transaction.created_at.desc()).limit(100).all()
            )
            cids = [r.customer_id for r in tx_rows if r.customer_id]
            customer_map = (
                {c.id: c.name for c in db.query(Customer).filter(Customer.id.in_(cids)).all()}
                if cids else {}
            )
            transactions = [
                {
                    "type": t.type, "customer": customer_map.get(t.customer_id),
                    "product": t.product, "amount": _money(t.amount), "created_at": t.created_at,
                }
                for t in tx_rows if not t.is_voided
            ]
            stock_items = [
                {
                    "name": item.name, "unit": item.unit,
                    "quantity": item.quantity or 0,
                    "selling_price": _money(item.selling_price) if item.selling_price else 0,
                }
                for item in (
                    db.query(InventoryItem)
                    .filter(InventoryItem.owner_phone == phone, InventoryItem.is_available == True)
                    .order_by(InventoryItem.name).all()
                )
            ]
            pdf_bytes = generate_loan_statement(
                owner=owner, summary=summary, transactions=transactions,
                debtors=debtors_raw, stock_items=stock_items,
                period_label=period_lbl, period=period_key,
            )
            biz_slug = (owner_user.name or "business").replace(" ", "_")[:20]
            filename = f"CreditVoice_Statement_{biz_slug}.pdf"
            return StreamingResponse(
                iter([pdf_bytes]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/loan-statement")
    def web_loan_statement(
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str]      = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """Generate and return a loan-ready business statement PDF."""
        from loan_statement import generate_loan_statement
        from reports import (
            get_dashboard_summary, get_unpaid_debtors, get_owner_transaction_query,
            dashboard_period_label,
        )
        db = SessionLocal()
        try:
            from admin import is_app_admin
            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            if owner_phone and session_user and is_app_admin(session_user.phone, db):
                phone = owner_phone
            else:
                phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None

            owner_user = db.query(User).filter(User.phone == phone).first()
            if not owner_user:
                raise HTTPException(status_code=404, detail="Business not found.")

            owner = {
                "name":               owner_user.name or phone,
                "phone":              phone,
                "business_type_label": owner_user.business_type_label,
                "business_category":  owner_user.business_category,
            }

            summary          = get_dashboard_summary(db, owner_phone=phone, period=period_key)
            debtors_raw, _   = get_unpaid_debtors(db, owner_phone=phone)
            period_lbl  = dashboard_period_label(period_key) if period_key else "all time"

            tx_rows = (
                get_owner_transaction_query(db, phone, period_key)
                .order_by(Transaction.created_at.desc())
                .limit(100)
                .all()
            )
            customer_map = {}
            cids = [r.customer_id for r in tx_rows if r.customer_id]
            if cids:
                customer_map = {
                    c.id: c.name
                    for c in db.query(Customer).filter(Customer.id.in_(cids)).all()
                }

            transactions = [
                {
                    "type":       t.type,
                    "customer":   customer_map.get(t.customer_id),
                    "product":    t.product,
                    "amount":     _money(t.amount),
                    "created_at": t.created_at,
                }
                for t in tx_rows
                if not t.is_voided
            ]

            stock_items = [
                {
                    "name":          item.name,
                    "unit":          item.unit,
                    "quantity":      item.quantity or 0,
                    "selling_price": _money(item.selling_price) if item.selling_price else 0,
                }
                for item in (
                    db.query(InventoryItem)
                    .filter(InventoryItem.owner_phone == phone, InventoryItem.is_available == True)
                    .order_by(InventoryItem.name)
                    .all()
                )
            ]

            pdf_bytes = generate_loan_statement(
                owner        = owner,
                summary      = summary,
                transactions = transactions,
                debtors      = debtors_raw,
                stock_items  = stock_items,
                period_label = period_lbl,
                period       = period_key,
            )

            biz_slug = (owner_user.name or "business").replace(" ", "_")[:20]
            filename = f"CreditVoice_Statement_{biz_slug}_{period_lbl.replace(' ', '_')}.pdf"
            return StreamingResponse(
                iter([pdf_bytes]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()
