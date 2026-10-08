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
from sqlalchemy import func

from database import SessionLocal
from models import User, InventoryItem, Branch, Transaction, Customer
from reports import get_owner_transaction_query
from web_pos import get_pos_receipt, save_pos_sale
from web_auth import require_web_auth
from web_common import (
    _session_owner_phone, _money, _iso, _scoped_read, _session_user,
    _require_tx_in_scope, _send_web_receipt, _require_can_record, _like_pattern,
    _require_stock_manager,
)

# Priced products the POS preloads for on-phone search. ~5,000 gzips to roughly
# what 1,000 used to cost uncompressed; bigger catalogues fall back to `q`.
POS_CATALOGUE_LIMIT = 5000


class AttachBarcodeRequest(BaseModel):
    item_id: int
    code: str = Field(max_length=48)


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
    discount: int = 0       # naira off the whole sale
    branch_id: Optional[int] = None
    due_date: Optional[datetime] = None
    service_date: Optional[datetime] = None   # promised delivery / ready-by date


class InvoiceCreateRequest(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = Field(default=None, max_length=120)
    customer_phone: Optional[str] = Field(default=None, max_length=20)
    items: list[PosCartItem] = Field(max_length=200)
    due_date: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=500)
    branch_id: Optional[int] = None


class InvoiceUpdateRequest(BaseModel):
    items: list[PosCartItem] = Field(max_length=200)
    due_date: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=500)


class InvoicePayRequest(BaseModel):
    amount: int = 0


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


def _recording_branch(db, session, owner_phone, requested_branch_id):
    """The branch a sale or invoice is recorded into. Don't trust a
    client-supplied branch: a branch staff records into THEIR branch; an owner
    may pick a branch but only one of their own."""
    scope_branch, _rec = _scoped_read(db, session)
    if scope_branch is not None:
        return scope_branch
    if requested_branch_id is not None:
        b = db.query(Branch).filter(
            Branch.id == requested_branch_id, Branch.owner_phone == owner_phone
        ).first()
        return b.id if b else None
    from transaction_save import _get_recording_branch_id
    return _get_recording_branch_id(db, owner_phone, _session_user(db, session))


def _require_items_in_branch(db, owner_phone, items, eff_branch):
    """You cannot sell an item that belongs to a different branch. Business-wide
    items (no branch) are sellable from anywhere."""
    if eff_branch is None:
        return
    ids = [it["inventory_item_id"] for it in items if it.get("inventory_item_id")]
    if not ids:
        return
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


def register_pos_routes(app):

    @app.get("/app/api/pos/products")
    def web_pos_products(
        q: Optional[str] = Query(default=None, max_length=120),
        branch_id: Optional[int] = Query(default=None),
        limit: int = Query(default=POS_CATALOGUE_LIMIT, ge=1, le=POS_CATALOGUE_LIMIT),
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
            term = (q or "").strip().lower()
            if term:
                query = query.filter(func.lower(InventoryItem.name).like(_like_pattern(term), escape="\\"))
            # The POS loads the catalogue once and searches it on the phone (instant,
            # and keeps working if the connection drops mid-shift). A catalogue
            # bigger than the preload is flagged `truncated`; the POS then also
            # searches here (`q`) so no product is silently unsellable.
            total = query.count()
            rows = query.order_by(InventoryItem.name).limit(limit).all()
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
                        "wholesale_price": _money(item.wholesale_price) if item.wholesale_price else None,
                        "wholesale_min_qty": item.wholesale_min_qty or None,
                        # The POS matches a scan against this on the phone, so
                        # scanning keeps working when the connection drops.
                        "barcode": item.barcode,
                    }
                    for item in rows
                ],
                "total": total,
                "truncated": total > len(rows),
                "monthly_transactions": {"count": _count, "limit": _limit, "remaining": _remaining},
            }
        finally:
            db.close()

    @app.get("/app/api/pos/scan")
    def web_pos_scan(
        code: str = Query(max_length=48),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """What a scan means. The POS matches against its own catalogue first;
        this is for a code it has not got — a product added since it loaded, or
        one belonging to another branch."""
        import barcodes
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            eff_branch = _selling_branch(db, session, owner_phone, branch_id)
            item = barcodes.find(db, owner_phone, code, eff_branch)
            if not item:
                return {"found": False, "code": barcodes.clean(code)}
            return {
                "found": True,
                "product": {
                    "id": item.id, "name": item.name, "unit": item.unit,
                    "quantity": item.quantity or 0,
                    "selling_price": _money(item.selling_price),
                    "barcode": item.barcode,
                    "sellable": item.selling_price is not None and bool(item.is_available),
                },
            }
        finally:
            db.close()

    @app.post("/app/api/pos/scan/attach")
    def web_pos_attach_barcode(
        payload: AttachBarcodeRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Teach a product the code just scanned — how a shop builds its
        barcode list at the till rather than in a data-entry session."""
        import barcodes
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            try:
                item = barcodes.attach(db, owner_phone, payload.item_id, payload.code)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            return {"id": item.id, "name": item.name, "barcode": item.barcode}
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
            eff_branch = _recording_branch(db, session, owner_phone, payload.branch_id)
            _require_items_in_branch(db, owner_phone, items, eff_branch)
            # What the customer owed BEFORE this sale — the ceiling for a
            # "settle previous debt" payment. Read now: once the sale is saved
            # the balance also carries this sale's unpaid part, and capping
            # against that let the settlement eat into the new sale and then
            # print as "Previous debt settled".
            owed_before_sale = 0
            if payload.debt_payment and payload.debt_payment > 0 and payload.customer_id:
                _c = db.query(Customer).filter(
                    Customer.id == payload.customer_id,
                    Customer.owner_phone == owner_phone,
                ).first()
                owed_before_sale = max(0, int((_c.balance if _c else 0) or 0))

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
                discount=payload.discount,
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
                    # Never overpay, and never beyond what was owed before this sale.
                    amt = min(int(payload.debt_payment), owed_before_sale, max(0, int(cust.balance or 0)))
                    if amt > 0:
                        # Tag the PAY with the sale's id so the sale receipt can show
                        # the prior debt that was cleared in the same checkout.
                        sale_tx_id = result.get("receipt_id")
                        db.add(Transaction(
                            customer_id=cust.id,
                            type="PAY",
                            amount=amt,
                            product=f"Prior debt — POS #{sale_tx_id}",
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
        """List past receipts for this business, newest first: sales (SALE / credit
        BUY) and standalone debt payments (PAY). Payments that are internal to a
        sale — a POS part-payment, a checkout debt-settle, or a WhatsApp buy+pay —
        are excluded, since the sale itself already appears as its own receipt."""
        from sqlalchemy import or_, and_
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            q = get_owner_transaction_query(db, owner_phone, None, include_voided=False)
            rows = q.filter(
                or_(
                    Transaction.type.in_(["SALE", "BUY"]),
                    and_(
                        Transaction.type == "PAY",
                        or_(Transaction.product.is_(None), ~Transaction.product.like("%POS #%")),
                        or_(Transaction.message_id.is_(None), ~Transaction.message_id.like("%_pay")),
                    ),
                )
            ).order_by(
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
        """Every invoice this business has: the ones written on the Invoices
        page, and the older ones that were numbers put on credit sales.
        Optional ?status=open|overdue|part_paid|paid|cancelled filter."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            from invoices import list_business_invoices, list_new_invoices
            scope_branch, scope_rec = _scoped_read(db, session)
            rows = list_new_invoices(db, owner_phone, branch_id=scope_branch, created_by_id=scope_rec)
            rows += [dict(r, kind="sale", delivered=True) for r in list_business_invoices(db, owner_phone)]
            rows.sort(key=lambda r: (r["invoice_number"] or 0), reverse=True)

            # "Open" is everything still waiting for money that isn't late yet.
            open_states = ("draft", "sent", "open")
            summary = {"open": 0, "overdue": 0, "part_paid": 0, "paid": 0, "cancelled": 0, "total_due": 0}
            for r in rows:
                summary["open" if r["status"] in open_states else r["status"]] += 1
                summary["total_due"] += r["outstanding"]

            want = (status or "").lower()
            if want == "open":
                rows = [r for r in rows if r["status"] in open_states]
            elif want in ("overdue", "part_paid", "paid", "cancelled"):
                rows = [r for r in rows if r["status"] == want]
            return {"invoices": rows, "summary": summary}
        finally:
            db.close()

    def _load_invoice(db, session, invoice_id):
        """This business's invoice, within the caller's branch / own-records
        scope. 404 otherwise, so it doesn't reveal that the invoice exists."""
        from models import Invoice
        owner_phone = _session_owner_phone(db, session)
        inv = db.query(Invoice).filter(
            Invoice.id == invoice_id, Invoice.owner_phone == owner_phone,
        ).first()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        scope_branch, scope_rec = _scoped_read(db, session)
        if scope_branch is not None and inv.branch_id != scope_branch:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        if scope_rec is not None and inv.created_by_id != scope_rec:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        return inv

    def _invoice_action(fn):
        """Run an invoice change, turning a refusal into a message for the user."""
        from invoices import InvoiceError
        try:
            return fn()
        except InvoiceError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/app/api/invoices/new")
    def web_create_invoice(payload: InvoiceCreateRequest, session: dict = Depends(require_web_auth)):
        """Write an invoice. It is not a sale and not a debt: nothing is owed
        and no stock moves until it is paid or delivered."""
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            owner_phone = _session_owner_phone(db, session)
            items = [it.model_dump() for it in payload.items]
            eff_branch = _recording_branch(db, session, owner_phone, payload.branch_id)
            _require_items_in_branch(db, owner_phone, items, eff_branch)
            from invoices import create_invoice, invoice_document
            inv = _invoice_action(lambda: create_invoice(
                db, owner_phone, session["user_id"], payload.customer_id, items,
                due_date=payload.due_date, note=payload.note, branch_id=eff_branch,
                customer_name=payload.customer_name, customer_phone=payload.customer_phone,
            ))
            return invoice_document(db, inv)
        finally:
            db.close()

    @app.get("/app/api/invoices/doc/{invoice_id}")
    def web_get_invoice(invoice_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from invoices import invoice_document
            return invoice_document(db, _load_invoice(db, session, invoice_id))
        finally:
            db.close()

    @app.put("/app/api/invoices/doc/{invoice_id}")
    def web_update_invoice(invoice_id: int, payload: InvoiceUpdateRequest,
                           session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            inv = _load_invoice(db, session, invoice_id)
            items = [it.model_dump() for it in payload.items]
            _require_items_in_branch(db, inv.owner_phone, items, inv.branch_id)
            from invoices import update_invoice, invoice_document
            _invoice_action(lambda: update_invoice(db, inv, items, due_date=payload.due_date, note=payload.note))
            return invoice_document(db, inv)
        finally:
            db.close()

    @app.post("/app/api/invoices/doc/{invoice_id}/send")
    def web_send_invoice_doc(invoice_id: int, session: dict = Depends(require_web_auth)):
        """Send the invoice to the customer's WhatsApp and record when."""
        db = SessionLocal()
        try:
            inv = _load_invoice(db, session, invoice_id)
            from invoices import invoice_document, format_invoice_doc_text
            doc = invoice_document(db, inv)
            if doc["status"] == "cancelled":
                raise HTTPException(status_code=400, detail="This invoice was cancelled.")
            phone = (doc.get("customer") or {}).get("phone")
            if not phone:
                raise HTTPException(
                    status_code=400,
                    detail="No phone on file for this customer. You can still print or download the invoice.",
                )
            from whatsapp_client import send_whatsapp_message
            send_whatsapp_message(phone, format_invoice_doc_text(doc))
            inv.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return invoice_document(db, inv)
        finally:
            db.close()

    @app.post("/app/api/invoices/doc/{invoice_id}/deliver")
    def web_deliver_invoice(invoice_id: int, session: dict = Depends(require_web_auth)):
        """The goods have gone to the customer — take them out of stock."""
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            inv = _load_invoice(db, session, invoice_id)
            from invoices import deliver_invoice, invoice_document
            _invoice_action(lambda: deliver_invoice(db, inv, session["user_id"]))
            return invoice_document(db, inv)
        finally:
            db.close()

    @app.post("/app/api/invoices/doc/{invoice_id}/pay")
    def web_pay_invoice(invoice_id: int, payload: InvoicePayRequest,
                        session: dict = Depends(require_web_auth)):
        """Record what the customer paid. The invoice becomes a sale with a
        receipt; whatever was not paid becomes their debt."""
        db = SessionLocal()
        try:
            _require_can_record(db, session)
            inv = _load_invoice(db, session, invoice_id)
            from invoices import pay_invoice, invoice_document
            _inv, result = _invoice_action(lambda: pay_invoice(db, inv, session["user_id"], payload.amount))
            _send_web_receipt(db, inv.owner_phone, result.get("receipt_id"))
            return invoice_document(db, inv)
        finally:
            db.close()

    @app.post("/app/api/invoices/doc/{invoice_id}/cancel")
    def web_cancel_invoice(invoice_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            inv = _load_invoice(db, session, invoice_id)
            from invoices import cancel_invoice, invoice_document
            _invoice_action(lambda: cancel_invoice(db, inv))
            return invoice_document(db, inv)
        finally:
            db.close()

    @app.post("/app/api/invoices/{tx_id}/issue")
    def web_issue_invoice(tx_id: int, session: dict = Depends(require_web_auth)):
        """Return an older invoice — a number once put on a credit sale. New
        numbers are no longer handed out this way: a sale already recorded is
        not a request to pay, so invoices are written on the Invoices page."""
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
            _require_tx_in_scope(db, session, tx)
            if not tx.invoice_number:
                raise HTTPException(
                    status_code=400,
                    detail="Invoices are written on the Invoices page now, not made from a sale.",
                )

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
        """Send an older invoice (a number once put on a credit sale) to the
        customer's WhatsApp and record it as sent."""
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

            if not tx.invoice_number:
                raise HTTPException(
                    status_code=400,
                    detail="Invoices are written on the Invoices page now, not made from a sale.",
                )
            from invoices import format_invoice_text

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
