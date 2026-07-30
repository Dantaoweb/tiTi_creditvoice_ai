"""
Supplier routes: list suppliers with balances + recent purchases.

Split out of web_routes.py. Register with register_supplier_routes(app);
shared helpers come from web_common.
"""
from datetime import datetime, timezone

from fastapi import Depends

from database import SessionLocal
from models import Supplier, SupplierPurchase, SupplierPayment
from web_auth import require_web_auth
from web_common import _session_owner_phone, _owner_filter, _iso, _money


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
