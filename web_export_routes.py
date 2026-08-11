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

    @app.get("/app/api/reports/bought-vs-sold")
    def web_bought_vs_sold(
        from_: Optional[str] = Query(default=None, alias="from"),
        to: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """Business-wide Bought-vs-Sold trading report PDF over a period: who
        supplied what (per supplier), what was sold for how much (per product),
        and the reconciliation between them."""
        from datetime import datetime, timedelta
        from models import Supplier, SupplierPurchase
        from reports import get_owner_transaction_query
        from bought_vs_sold_report import generate_bought_vs_sold
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            u = db.query(User).filter(User.phone == owner_phone).first()
            if not u:
                raise HTTPException(status_code=404, detail="Business not found.")
            owner = {
                "name": u.name or owner_phone,
                "phone": owner_phone,
                "business_type_label": u.business_type_label,
                "business_category": u.business_category,
            }

            def _parse(s, end=False):
                if not s:
                    return None
                try:
                    d = datetime.strptime(s[:10], "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD.")
                return d + timedelta(days=1) if end else d
            from_dt = _parse(from_)
            to_dt = _parse(to, end=True)

            # ── Bought side: supplier purchases in the window ──────────────────
            pq = db.query(SupplierPurchase).filter(SupplierPurchase.owner_phone == owner_phone)
            if from_dt:
                pq = pq.filter(SupplierPurchase.created_at >= from_dt)
            if to_dt:
                pq = pq.filter(SupplierPurchase.created_at < to_dt)
            purchases = pq.all()
            sup_names = {
                s.id: s.name
                for s in db.query(Supplier).filter(Supplier.owner_phone == owner_phone).all()
            }

            by_sup, bought_by_product = {}, {}
            for p in purchases:
                sname = (sup_names.get(p.supplier_id) or "-").title()
                prod = (p.product or "-").title()
                key = (sname, prod, p.unit or "")
                row = by_sup.setdefault(key, {
                    "supplier": sname, "product": prod, "unit": p.unit or "",
                    "qty": 0, "spend": 0, "owed": 0,
                })
                row["qty"] += p.quantity or 0
                row["spend"] += p.total or 0
                row["owed"] += max(0, (p.total or 0) - (p.paid_amount or 0))
                bp = bought_by_product.setdefault(prod, {"qty_bought": 0, "spend": 0})
                bp["qty_bought"] += p.quantity or 0
                bp["spend"] += p.total or 0

            total_spend = sum(p.total or 0 for p in purchases)
            total_paid_suppliers = sum(p.paid_amount or 0 for p in purchases)
            owed_suppliers = sum(max(0, (p.total or 0) - (p.paid_amount or 0)) for p in purchases)

            # ── Sold side: SALE / BUY transactions in the window ───────────────
            sq = get_owner_transaction_query(db, owner_phone).filter(Transaction.type.in_(["SALE", "BUY"]))
            if from_dt:
                sq = sq.filter(Transaction.created_at >= from_dt)
            if to_dt:
                sq = sq.filter(Transaction.created_at < to_dt)
            sold_by_product, total_revenue = {}, 0
            for t in sq.all():
                prod = (t.product or "-").title()
                sp = sold_by_product.setdefault(prod, {"qty_sold": 0, "revenue": 0})
                sp["qty_sold"] += t.quantity or 0
                sp["revenue"] += t.amount or 0
                total_revenue += t.amount or 0

            products = sorted(set(list(bought_by_product) + list(sold_by_product)))
            by_product = []
            for prod in products:
                b = bought_by_product.get(prod, {"qty_bought": 0, "spend": 0})
                s = sold_by_product.get(prod, {"qty_sold": 0, "revenue": 0})
                by_product.append({
                    "product": prod,
                    "qty_bought": b["qty_bought"], "spend": b["spend"],
                    "qty_sold": s["qty_sold"], "revenue": s["revenue"],
                    "margin": (s["revenue"] or 0) - (b["spend"] or 0),
                })

            by_supplier = sorted(by_sup.values(), key=lambda r: r["spend"], reverse=True)
            summary = {
                "total_spend": total_spend,
                "total_paid_suppliers": total_paid_suppliers,
                "owed_suppliers": owed_suppliers,
                "total_revenue": total_revenue,
                "trading_margin": total_revenue - total_spend,
            }

            def _lbl(s):
                return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d %b %Y") if s else None
            period_label = (
                f"{_lbl(from_) or 'Start'} - {_lbl(to) or 'Today'}" if (from_ or to) else "All time"
            )

            pdf_bytes = generate_bought_vs_sold(owner, summary, by_supplier, by_product, period_label)
            biz_slug = (u.name or "business").replace(" ", "_")[:20]
            filename = f"CreditVoice_BoughtVsSold_{biz_slug}.pdf"
            return StreamingResponse(
                iter([pdf_bytes]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()
