"""
POS + invoice routes: product lookup, save sale, receipts list, single receipt,
and the invoice list/issue/send flow.

Split out of web_routes.py. Register with register_pos_routes(app); shared
helpers come from web_common.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, InventoryItem, Branch, Transaction, Customer
from reports import get_owner_transaction_query
from web_pos import get_pos_receipt, save_pos_sale
from web_auth import require_web_auth
from web_common import (
    _session_owner_phone, _money, _iso, _scoped_read, _session_user,
    _require_tx_in_scope, _send_web_receipt, _require_can_record,
)


class PosCartItem(BaseModel):
    inventory_item_id: Optional[int] = None
    name: str = Field(max_length=120)
    qty: float = 1.0
    unit: Optional[str] = Field(default=None, max_length=30)
    unit_price: int = 0
    sold_unit: Optional[str] = Field(default=None, max_length=30)
    fraction: Optional[float] = 1.0


class PosSaveRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    customer_id: Optional[int] = None
    customer_name: Optional[str] = Field(default=None, max_length=120)   # inline new/unlisted customer
    customer_phone: Optional[str] = Field(default=None, max_length=20)   # optional, not required
    items: list[PosCartItem] = Field(max_length=200)  # max 200 line items per sale
    payment_amount: int = 0
    debt_payment: int = 0   # extra collected at checkout to clear the customer's prior debt
    branch_id: Optional[int] = None
    due_date: Optional[datetime] = None
    service_date: Optional[datetime] = None   # promised delivery / ready-by date


def _selling_branch(db, session, owner_phone, requested_branch_id):
    """The branch a sale is happening from — you can only sell stock that belongs
    to it. Branch staff are locked to their own branch; an owner may pick any of
    their branches and otherwise falls back to their default branch. Returns None
    for single-location businesses (no branches → no filtering)."""
    scope_branch, _rec = _scoped_read(db, session)
    if scope_branch is not None:
        return scope_branch
    if requested_branch_id is not None:
        b = db.query(Branch).filter(
            Branch.id == requested_branch_id, Branch.owner_phone == owner_phone
        ).first()
        if b:
            return b.id
    from transaction_save import _get_default_branch_id
    return _get_default_branch_id(db, owner_phone)


def register_pos_routes(app):

    @app.get("/app/api/pos/products")
    def web_pos_products(
        q: Optional[str] = Query(default=None),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            query = db.query(InventoryItem).filter(
                InventoryItem.is_available == True,
                InventoryItem.owner_phone == owner_phone,
                InventoryItem.selling_price != None,
            )
            # Only show stock that belongs to the branch being sold from, so a
            # branch can't sell another branch's (or the default branch's) stock.
            eff_branch = _selling_branch(db, session, owner_phone, branch_id)
            if eff_branch is not None:
                query = query.filter(InventoryItem.branch_id == eff_branch)
            if q:
                query = query.filter(InventoryItem.name.ilike(f"%{q}%"))
            rows = query.order_by(InventoryItem.name).limit(50).all()
            # Monthly transaction usage — lets the POS warn as the Basic cap nears.
            from subscriptions import get_business_subscription, monthly_transaction_usage
            _sub = get_business_subscription(db, _session_user(db, session))
            _count, _limit, _remaining = monthly_transaction_usage(db, owner_phone, _sub)
            return {
                "products": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "unit": item.unit,
                        "quantity": item.quantity or 0,
                        "selling_price": _money(item.selling_price),
                        "cost_price": _money(item.cost_price),
                        "is_service": item.quantity is None or item.category == "service",
                        "retail_unit": item.retail_unit,
                        "retail_per_base": item.retail_per_base,
                        "retail_price": _money(item.retail_price) if item.retail_price else None,
                    }
                    for item in rows
                ],
                "monthly_transactions": {"count": _count, "limit": _limit, "remaining": _remaining},
            }
        finally:
            db.close()

    @app.post("/app/api/pos/save")
    def web_pos_save(
        payload: PosSaveRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            _require_can_record(db, session)
            owner_phone = _session_owner_phone(db, session)
            items = [it.model_dump() for it in payload.items]
            # Don't trust a client-supplied branch: a branch staff records into
            # THEIR branch; an owner may pick a branch but only one of their own.
            scope_branch, _rec = _scoped_read(db, session)
            if scope_branch is not None:
                eff_branch = scope_branch
            elif payload.branch_id is not None:
                _b = db.query(Branch).filter(
                    Branch.id == payload.branch_id, Branch.owner_phone == owner_phone
                ).first()
                eff_branch = _b.id if _b else None
            else:
                from transaction_save import _get_recording_branch_id
                eff_branch = _get_recording_branch_id(db, owner_phone, _session_user(db, session))

            # Enforce branch gating server-side: you cannot sell an item that
            # belongs to a different branch. Business-wide items (no branch) are
            # sellable from anywhere.
            if eff_branch is not None:
                ids = [it["inventory_item_id"] for it in items if it.get("inventory_item_id")]
                if ids:
                    wrong = db.query(InventoryItem).filter(
                        InventoryItem.owner_phone == owner_phone,
                        InventoryItem.id.in_(ids),
                        InventoryItem.branch_id != None,
                        InventoryItem.branch_id != eff_branch,
                    ).first()
                    if wrong:
                        raise HTTPException(
                            status_code=400,
                            detail=f"'{wrong.name.title()}' belongs to another branch and can't be sold from here.",
                        )
            result = save_pos_sale(
                db,
                owner_phone,
                session["user_id"],
                payload.customer_id,
                items,
                payload.payment_amount,
                branch_id=eff_branch,
                due_date=payload.due_date,
                customer_name=payload.customer_name,
                customer_phone=payload.customer_phone,
                service_date=payload.service_date,
            )
            # Settle the customer's prior debt in the same checkout, when they paid
            # extra to clear it (POS "Settle previous debt" line). Recorded as a
            # normal PAY so it reduces their balance exactly like a manual payment.
            if payload.debt_payment and payload.debt_payment > 0 and payload.customer_id:
                import uuid as _uuid
                from web_pos import next_receipt_number
                cust = db.query(Customer).filter(
                    Customer.id == payload.customer_id,
                    Customer.owner_phone == owner_phone,
                ).first()
                if cust:
                    owed_now = max(0, int(cust.balance or 0))   # never overpay the debt
                    amt = min(int(payload.debt_payment), owed_now)
                    if amt > 0:
                        db.add(Transaction(
                            customer_id=cust.id,
                            type="PAY",
                            amount=amt,
                            product="Debt settled at checkout",
                            recorded_by_id=session["user_id"],
                            message_id=f"web-pos-debt-{_uuid.uuid4()}",
                            branch_id=eff_branch,
                            receipt_number=next_receipt_number(db, owner_phone),
                        ))
                        db.commit()

            # Send the customer their receipt on WhatsApp (like the WhatsApp flow)
            _send_web_receipt(db, owner_phone, result.get("receipt_id"))
            return result
        except HTTPException:
            raise
        except Exception:
            # Log the detail server-side; don't leak internals to the client.
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=400, detail="Could not save the sale. Please check the items and try again.")
        finally:
            db.close()

    @app.get("/app/api/pos/receipts")
    def web_pos_receipts(session: dict = Depends(require_web_auth)):
        """List past receipts (SALE / credit BUY) for this business, newest first."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            q = get_owner_transaction_query(db, owner_phone, None, include_voided=False)
            rows = q.filter(Transaction.type.in_(["SALE", "BUY"])).order_by(
                Transaction.created_at.desc()
            ).limit(100).all()
            cust_ids = [r.customer_id for r in rows if r.customer_id]
            customers = {}
            if cust_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()}
            return {
                "receipts": [
                    {
                        "id": r.id,
                        "created_at": _iso(r.created_at),
                        "customer": customers[r.customer_id].name if customers.get(r.customer_id) else None,
                        "total": _money(r.amount),
                        "type": r.type,
                        "due_date": _iso(r.due_date),
                    }
                    for r in rows
                ]
            }
        finally:
            db.close()

    @app.get("/app/api/pos/receipt/{tx_id}")
    def web_pos_receipt(tx_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            # Verify the transaction belongs to this business
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            receipt = get_pos_receipt(db, tx_id, user=owner_user or session_user)
            if not receipt:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            return receipt
        finally:
            db.close()

    @app.get("/app/api/invoices")
    def web_list_invoices(status: str = None, session: dict = Depends(require_web_auth)):
        """List this business's issued invoices with a derived status.
        Optional ?status=open|overdue|paid filter."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            from invoices import list_business_invoices
            status_filter = status.lower() if status else None
            if status_filter and status_filter not in ("open", "overdue", "paid"):
                status_filter = None
            invoices = list_business_invoices(db, owner_phone, status_filter)
            summary = {"open": 0, "overdue": 0, "paid": 0, "total_due": 0}
            # Summary is computed over all invoices, independent of the filter.
            for row in (list_business_invoices(db, owner_phone) if status_filter else invoices):
                summary[row["status"]] += 1
                summary["total_due"] += row["outstanding"]
            return {"invoices": invoices, "summary": summary}
        finally:
            db.close()

    @app.post("/app/api/invoices/{tx_id}/issue")
    def web_issue_invoice(tx_id: int, session: dict = Depends(require_web_auth)):
        """Assign a sale its formal invoice number (once) and return the invoice
        document. The number is system-generated per business — never typed by a
        user — so two invoices can never collide."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Sale not found.")
            # Verify the sale belongs to this business (mirrors web_pos_receipt)
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=404, detail="Sale not found.")
            # A limited staff may only invoice sales within their own scope.
            _require_tx_in_scope(db, session, tx)

            from invoices import issue_invoice_number
            issue_invoice_number(db, tx, owner_phone)
            db.commit()

            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            receipt = get_pos_receipt(db, tx_id, user=owner_user or session_user)
            if not receipt:
                raise HTTPException(status_code=404, detail="Sale not found.")
            return receipt
        finally:
            db.close()

    @app.post("/app/api/invoices/{tx_id}/send")
    def web_send_invoice(tx_id: int, session: dict = Depends(require_web_auth)):
        """Send the invoice to the customer's WhatsApp and record it as sent.
        Assigns the invoice number first if needed."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Sale not found.")
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=404, detail="Sale not found.")
            # A limited staff may only send invoices for sales within their scope.
            _require_tx_in_scope(db, session, tx)

            customer = db.query(Customer).filter(Customer.id == tx.customer_id).first() if tx.customer_id else None
            if not customer or not customer.customer_phone:
                raise HTTPException(
                    status_code=400,
                    detail="No phone on file for this customer. You can still print or download the invoice.",
                )

            from invoices import issue_invoice_number, format_invoice_text
            issue_invoice_number(db, tx, owner_phone)
            db.commit()

            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            receipt = get_pos_receipt(db, tx_id, user=owner_user or session_user)
            if not receipt:
                raise HTTPException(status_code=404, detail="Sale not found.")

            from whatsapp_client import send_whatsapp_message
            send_whatsapp_message(customer.customer_phone, format_invoice_text(receipt))

            tx.invoice_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return {
                "id": tx.id,
                "invoice_number": tx.invoice_number,
                "sent_at": tx.invoice_sent_at.isoformat(),
            }
        finally:
            db.close()
