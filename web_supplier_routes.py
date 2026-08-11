"""
Supplier routes: list suppliers with balances + recent purchases.

Split out of web_routes.py. Register with register_supplier_routes(app);
shared helpers come from web_common.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from database import SessionLocal
from models import Supplier, SupplierPurchase, SupplierPayment, User, utcnow
from web_auth import require_web_auth
from web_common import _session_owner_phone, _owner_filter, _iso, _money, _require_stock_manager


def _biz_name(db, owner_phone):
    u = db.query(User).filter(User.phone == owner_phone).first()
    return (u.business_type_label or u.name or "Your business") if u else "Your business"


def _owner_header(db, owner_phone):
    """Business header block shared by supplier receipts (same fields the sale
    receipt uses)."""
    u = db.query(User).filter(User.phone == owner_phone).first()
    return {
        "biz_name": (u.business_type_label or u.name) if u else "Your business",
        "biz_address": getattr(u, "address", None) if u else None,
        "biz_phone": owner_phone,
        "recorded_by": (u.name if u else None),
    }


class SupplierPayRequest(BaseModel):
    amount: int = Field(gt=0)
    note: str = Field(default="", max_length=200)


class AddSupplierRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: str = Field(default="", max_length=20)


class EditSupplierRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: str = Field(default="", max_length=20)


class SupplierPurchaseDueRequest(BaseModel):
    due_date: Optional[str] = None   # "YYYY-MM-DD", or null to clear


class SupplierPurchaseEditRequest(BaseModel):
    quantity: Optional[float] = None
    unit_price: Optional[int] = None   # cost per unit; recomputes total


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

                # Stored due_date values are naive UTC (from strptime), so compare
                # against a naive now — mixing naive/aware raises TypeError → 500.
                now = utcnow()
                due_dates = [
                    p.due_date for p in purchases
                    if p.due_date and (p.total or 0) > (p.paid_amount or 0)
                ]
                has_overdue = any(d < now for d in due_dates)
                next_due = min(due_dates, default=None)

                result.append({
                    "id": sup.id,
                    "name": sup.name,
                    "phone": sup.phone,
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

    # ── Supplier receipts (stock-received purchases + payments) ───────────────
    # Registered before /suppliers/{supplier_id} so the literal path wins.
    @app.get("/app/api/suppliers/receipts")
    def web_supplier_receipts(session: dict = Depends(require_web_auth)):
        """List supplier receipts (purchases + payments) for the Receipts menu."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            sup_names = {s.id: s.name for s in db.query(Supplier).filter(Supplier.owner_phone == owner_phone).all()}
            purchases = db.query(SupplierPurchase).filter(
                SupplierPurchase.owner_phone == owner_phone
            ).order_by(SupplierPurchase.created_at.desc()).limit(100).all()
            payments = db.query(SupplierPayment).filter(
                SupplierPayment.owner_phone == owner_phone
            ).order_by(SupplierPayment.created_at.desc()).limit(100).all()

            rows = []
            for p in purchases:
                rows.append({
                    "kind": "purchase", "id": p.id,
                    "supplier": (sup_names.get(p.supplier_id) or "").title() or "—",
                    "label": p.product, "amount": _money(p.total),
                    "balance": max(0, (p.total or 0) - (p.paid_amount or 0)),
                    "created_at": _iso(p.created_at),
                })
            for p in payments:
                rows.append({
                    "kind": "payment", "id": p.id,
                    "supplier": (sup_names.get(p.supplier_id) or "").title() or "—",
                    "label": "Payment", "amount": _money(p.amount),
                    "balance": 0, "created_at": _iso(p.created_at),
                })
            rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
            return {"receipts": rows}
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
                "phone": sup.phone,
                "total_bought": total_bought,
                "total_paid": total_paid,
                "balance": balance,
                "purchases": [
                    {
                        "id": p.id, "product": p.product, "quantity": p.quantity, "unit": p.unit,
                        "unit_price": _money(p.unit_price),
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

            pay = SupplierPayment(
                supplier_id=sup.id,
                owner_phone=owner_phone,
                amount=payload.amount,
                product=(payload.note.strip() or None),
                recorded_by_id=session["user_id"],
                created_at=utcnow(),
            )
            db.add(pay)
            db.commit()
            db.refresh(pay)
            _bought, _paid, balance = _supplier_balance(db, sup.id)
            return {"ok": True, "supplier": sup.name.title(), "balance": balance, "payment_id": pay.id}
        finally:
            db.close()

    @app.post("/app/api/suppliers")
    def web_add_supplier(payload: AddSupplierRequest, session: dict = Depends(require_web_auth)):
        """Create a supplier manually (before any purchase). Owner/branch-admin."""
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            name = payload.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Supplier name is required.")
            existing = db.query(Supplier).filter(
                Supplier.owner_phone == owner_phone,
                func.lower(Supplier.name) == name.lower(),
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="A supplier with that name already exists.")
            sup = Supplier(name=name.lower(), phone=(payload.phone.strip() or None), owner_phone=owner_phone)
            db.add(sup)
            db.commit()
            db.refresh(sup)
            return {"ok": True, "id": sup.id, "name": sup.name.title(), "phone": sup.phone}
        finally:
            db.close()

    @app.put("/app/api/suppliers/{supplier_id}")
    def web_edit_supplier(
        supplier_id: int,
        payload: EditSupplierRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Edit a supplier's name and phone. Owner/branch-admin only."""
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            sup = db.query(Supplier).filter(
                Supplier.id == supplier_id, Supplier.owner_phone == owner_phone,
            ).first()
            if not sup:
                raise HTTPException(status_code=404, detail="Supplier not found.")
            name = payload.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Supplier name is required.")
            clash = db.query(Supplier).filter(
                Supplier.owner_phone == owner_phone,
                func.lower(Supplier.name) == name.lower(),
                Supplier.id != sup.id,
            ).first()
            if clash:
                raise HTTPException(status_code=409, detail="Another supplier already has that name.")
            sup.name = name.lower()
            sup.phone = payload.phone.strip() or None
            db.commit()
            return {"ok": True, "id": sup.id, "name": sup.name.title(), "phone": sup.phone}
        finally:
            db.close()

    @app.put("/app/api/suppliers/purchases/{purchase_id}/due-date")
    def web_set_purchase_due(
        purchase_id: int,
        payload: SupplierPurchaseDueRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Set or clear the due date on a credit purchase (drives the overdue view)."""
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            p = db.query(SupplierPurchase).filter(
                SupplierPurchase.id == purchase_id,
                SupplierPurchase.owner_phone == owner_phone,
            ).first()
            if not p:
                raise HTTPException(status_code=404, detail="Purchase not found.")
            if payload.due_date:
                try:
                    p.due_date = datetime.strptime(payload.due_date[:10], "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD.")
            else:
                p.due_date = None
            db.commit()
            return {"ok": True, "due_date": _iso(p.due_date)}
        finally:
            db.close()

    @app.put("/app/api/suppliers/purchases/{purchase_id}")
    def web_edit_purchase(
        purchase_id: int,
        payload: SupplierPurchaseEditRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Correct a purchase's quantity and/or cost. Recomputes the total,
        keeps paid_amount within it, and syncs the physical stock + the linked
        stock movement by the quantity delta so the two never drift apart."""
        from models import InventoryItem, InventoryMovement
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            p = db.query(SupplierPurchase).filter(
                SupplierPurchase.id == purchase_id,
                SupplierPurchase.owner_phone == owner_phone,
            ).first()
            if not p:
                raise HTTPException(status_code=404, detail="Purchase not found.")

            old_qty = p.quantity or 0
            new_qty = old_qty if payload.quantity is None else payload.quantity
            if new_qty is not None and new_qty <= 0:
                raise HTTPException(status_code=400, detail="Quantity must be greater than zero.")
            if payload.unit_price is not None:
                p.unit_price = max(0, int(payload.unit_price))
            p.quantity = new_qty

            # Recompute total from cost × qty; never let paid exceed the new total.
            p.total = int(round((p.unit_price or 0) * (new_qty or 0)))
            p.paid_amount = max(0, min(p.paid_amount or 0, p.total))

            # Keep physical stock in step with the corrected quantity.
            delta = (new_qty or 0) - old_qty
            if delta:
                mv = db.query(InventoryMovement).filter(
                    InventoryMovement.source_type == "SUPPLIER_PURCHASE",
                    InventoryMovement.source_id == p.id,
                    InventoryMovement.owner_phone == owner_phone,
                ).first()
                if mv:
                    item = db.query(InventoryItem).filter(InventoryItem.id == mv.item_id).first()
                    if item:
                        item.quantity = (item.quantity or 0) + delta
                        item.updated_at = utcnow()
                    mv.quantity = new_qty
            db.commit()
            balance = max(0, (p.total or 0) - (p.paid_amount or 0))
            return {
                "ok": True,
                "quantity": p.quantity, "unit_price": p.unit_price,
                "total": p.total, "paid_amount": p.paid_amount, "balance": balance,
            }
        except HTTPException:
            raise
        except Exception:
            import traceback; traceback.print_exc()
            db.rollback()
            raise HTTPException(status_code=400, detail="Could not update purchase. Please try again.")
        finally:
            db.close()

    @app.get("/app/api/suppliers/receipt/{kind}/{item_id}")
    def web_supplier_receipt(kind: str, item_id: int, session: dict = Depends(require_web_auth)):
        """Rich supplier receipt (same shape/style as a sale receipt) for a
        stock-received purchase or a supplier payment."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            header = _owner_header(db, owner_phone)

            if kind == "purchase":
                p = db.query(SupplierPurchase).filter(
                    SupplierPurchase.id == item_id, SupplierPurchase.owner_phone == owner_phone,
                ).first()
                if not p:
                    raise HTTPException(status_code=404, detail="Receipt not found.")
                sup = db.query(Supplier).filter(Supplier.id == p.supplier_id).first()
                total = p.total or 0
                paid = p.paid_amount or 0
                return {
                    **header,
                    "kind": "purchase",
                    "id": p.id,
                    "title": "Stock Received",
                    "supplier": {"name": (sup.name.title() if sup else "—"), "phone": (sup.phone if sup else None)},
                    "created_at": _iso(p.created_at),
                    "items": [{
                        "product": (p.product or "").title(), "qty": p.quantity, "unit": p.unit,
                        "unit_price": _money(p.unit_price), "total": _money(total),
                    }],
                    "total": total, "paid": paid, "balance": max(0, total - paid),
                    "due_date": _iso(p.due_date),
                }

            if kind == "payment":
                pay = db.query(SupplierPayment).filter(
                    SupplierPayment.id == item_id, SupplierPayment.owner_phone == owner_phone,
                ).first()
                if not pay:
                    raise HTTPException(status_code=404, detail="Receipt not found.")
                sup = db.query(Supplier).filter(Supplier.id == pay.supplier_id).first()
                _b, _p, balance = _supplier_balance(db, pay.supplier_id)
                return {
                    **header,
                    "kind": "payment",
                    "id": pay.id,
                    "title": "Supplier Payment",
                    "supplier": {"name": (sup.name.title() if sup else "—"), "phone": (sup.phone if sup else None)},
                    "created_at": _iso(pay.created_at),
                    "amount": _money(pay.amount),
                    "balance": balance,
                    "note": pay.product,
                }

            raise HTTPException(status_code=400, detail="Unknown receipt kind.")
        finally:
            db.close()
