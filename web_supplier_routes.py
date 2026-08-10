"""
Supplier routes: list suppliers with balances + recent purchases.

Split out of web_routes.py. Register with register_supplier_routes(app);
shared helpers come from web_common.
"""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Supplier, SupplierPurchase, SupplierPayment, utcnow
from web_auth import require_web_auth
from web_common import _session_owner_phone, _owner_filter, _iso, _money, _require_stock_manager


class SupplierPayRequest(BaseModel):
    amount: int = Field(gt=0)
    note: str = Field(default="", max_length=200)


def _supplier_balance(db, supplier_id):
    """(total_bought, total_paid, balance) for a supplier."""
    purchases = db.query(SupplierPurchase).filter(SupplierPurchase.supplier_id == supplier_id).all()
    payments = db.query(SupplierPayment).filter(SupplierPayment.supplier_id == supplier_id).all()
    total_bought = sum(p.total or 0 for p in purchases)
    total_paid = sum(p.paid_amount or 0 for p in purchases) + sum(p.amount or 0 for p in payments)
    return total_bought, total_paid, max(0, total_bought - total_paid)


def register_supplier_routes(app):

    @app.get("/app/api/suppliers")
    def web_suppliers(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(Supplier), Supplier, owner_phone)
            suppliers = query.order_by(Supplier.name).all()

            result = []
            for sup in suppliers:
                purchases = db.query(SupplierPurchase).filter(
                    SupplierPurchase.supplier_id == sup.id
                ).all()
                payments = db.query(SupplierPayment).filter(
                    SupplierPayment.supplier_id == sup.id
                ).all()

                total_bought = sum(p.total or 0 for p in purchases)
                paid_via_purchase = sum(p.paid_amount or 0 for p in purchases)
                paid_via_payment = sum(p.amount or 0 for p in payments)
                total_paid = paid_via_purchase + paid_via_payment
                balance = max(0, total_bought - total_paid)

                now = datetime.now(timezone.utc)
                due_dates = [
                    p.due_date for p in purchases
                    if p.due_date and (p.total or 0) > (p.paid_amount or 0)
                ]
                has_overdue = any(d < now for d in due_dates)
                next_due = min(due_dates, default=None)

                result.append({
                    "id": sup.id,
                    "name": sup.name,
                    "purchases": len(purchases),
                    "total_bought": total_bought,
                    "total_paid": total_paid,
                    "balance": balance,
                    "has_overdue": has_overdue,
                    "next_due": _iso(next_due),
                    "created_at": _iso(sup.created_at),
                })

            recent_query = db.query(SupplierPurchase)
            if owner_phone:
                recent_query = recent_query.filter(SupplierPurchase.owner_phone == owner_phone)
            recent = recent_query.order_by(SupplierPurchase.created_at.desc()).limit(50).all()
            sup_names = {s.id: s.name for s in suppliers}

            return {
                "suppliers": sorted(result, key=lambda r: r["balance"], reverse=True),
                "recent_purchases": [
                    {
                        "id": p.id,
                        "supplier": sup_names.get(p.supplier_id, "Unknown"),
                        "product": p.product,
                        "quantity": p.quantity,
                        "unit": p.unit,
                        "total": _money(p.total),
                        "paid_amount": _money(p.paid_amount),
                        "due_date": _iso(p.due_date),
                        "created_at": _iso(p.created_at),
                    }
                    for p in recent
                ],
            }
        finally:
            db.close()

    @app.get("/app/api/suppliers/{supplier_id}")
    def web_supplier_detail(supplier_id: int, session: dict = Depends(require_web_auth)):
        """A supplier's purchase + payment history with a running balance."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            sup = db.query(Supplier).filter(
                Supplier.id == supplier_id, Supplier.owner_phone == owner_phone,
            ).first()
            if not sup:
                raise HTTPException(status_code=404, detail="Supplier not found.")

            purchases = db.query(SupplierPurchase).filter(
                SupplierPurchase.supplier_id == sup.id
            ).order_by(SupplierPurchase.created_at.desc()).all()
            payments = db.query(SupplierPayment).filter(
                SupplierPayment.supplier_id == sup.id
            ).order_by(SupplierPayment.created_at.desc()).all()
            total_bought, total_paid, balance = _supplier_balance(db, sup.id)

            return {
                "id": sup.id,
                "name": sup.name,
                "total_bought": total_bought,
                "total_paid": total_paid,
                "balance": balance,
                "purchases": [
                    {
                        "id": p.id, "product": p.product, "quantity": p.quantity, "unit": p.unit,
                        "total": _money(p.total), "paid_amount": _money(p.paid_amount),
                        "due_date": _iso(p.due_date), "created_at": _iso(p.created_at),
                    }
                    for p in purchases
                ],
                "payments": [
                    {
                        "id": p.id, "amount": _money(p.amount),
                        "product": p.product, "created_at": _iso(p.created_at),
                    }
                    for p in payments
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/suppliers/{supplier_id}/pay")
    def web_supplier_pay(
        supplier_id: int,
        payload: SupplierPayRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Record a payment to a supplier (pays down what you owe them). Mirrors
        the WhatsApp supplier-payment flow. Owner / branch-admin only."""
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            sup = db.query(Supplier).filter(
                Supplier.id == supplier_id, Supplier.owner_phone == owner_phone,
            ).first()
            if not sup:
                raise HTTPException(status_code=404, detail="Supplier not found.")

            db.add(SupplierPayment(
                supplier_id=sup.id,
                owner_phone=owner_phone,
                amount=payload.amount,
                product=(payload.note.strip() or None),
                recorded_by_id=session["user_id"],
                created_at=utcnow(),
            ))
            db.commit()
            _bought, _paid, balance = _supplier_balance(db, sup.id)
            return {"ok": True, "supplier": sup.name.title(), "balance": balance}
        finally:
            db.close()
