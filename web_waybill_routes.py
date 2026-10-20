"""
Waybills / loading orders on the web (waybills.py), and keeping a customer's
goods aside in the store.

- Anyone who records sales may make and print a waybill — loaders and sales
  staff need to.
- Cancelling a waybill and keeping goods aside / releasing them is for the
  owner and authorised staff (full access), like the stock settings.
"""
from typing import List, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Customer, Invoice, Transaction, User, Waybill
from web_auth import require_web_auth
from web_common import (
    _require_can_record, _require_tx_in_scope, _scoped_read, _session_owner_phone, _session_user,
)


class WaybillLineIn(BaseModel):
    line_id: Optional[int] = None                    # receipt / invoice line
    key: Optional[str] = Field(default=None, max_length=200)   # a customer's product (Deliveries)
    quantity: float = 0


class WaybillRequest(BaseModel):
    tx_id: Optional[int] = None
    invoice_id: Optional[int] = None
    customer_id: Optional[int] = None
    lines: List[WaybillLineIn] = Field(default_factory=list, max_length=200)
    driver_name: Optional[str] = Field(default=None, max_length=120)
    driver_phone: Optional[str] = Field(default=None, max_length=40)
    vehicle: Optional[str] = Field(default=None, max_length=60)
    loaders: Optional[str] = Field(default=None, max_length=300)
    address: Optional[str] = Field(default=None, max_length=300)
    note: Optional[str] = Field(default=None, max_length=300)
    notify: bool = True                              # send the customer the WhatsApp note


class WaybillCancelRequest(BaseModel):
    reason: str = Field(default="", max_length=300)


class KeepAsideRequest(BaseModel):
    customer_id: int
    key: str = Field(max_length=200)
    kept: float


def _require_full_access(db, session, what):
    user = _session_user(db, session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    if user.parent_id is not None and not user.can_view_all_transactions:
        raise HTTPException(status_code=403, detail=f"Only the owner or an authorised staff member can {what}.")
    return user


def register_waybill_routes(app):

    def _sale(db, session, tx_id):
        from reports import get_owner_transaction_query
        tx = (get_owner_transaction_query(db, _session_owner_phone(db, session))
              .filter(Transaction.id == tx_id, Transaction.type.in_(("SALE", "BUY")),
                      Transaction.amount > 0).first())
        if not tx:
            raise HTTPException(status_code=404, detail="Sale not found.")
        _require_tx_in_scope(db, session, tx)
        return tx

    def _invoice(db, session, invoice_id):
        inv = db.query(Invoice).filter(Invoice.id == invoice_id,
                                       Invoice.owner_phone == _session_owner_phone(db, session)).first()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        branch, rec = _scoped_read(db, session)
        if (branch is not None and inv.branch_id != branch) or (rec is not None and inv.created_by_id != rec):
            raise HTTPException(status_code=404, detail="Invoice not found.")
        return inv

    def _customer(db, session, customer_id):
        c = db.query(Customer).filter(Customer.id == customer_id,
                                      Customer.owner_phone == _session_owner_phone(db, session)).first()
        if not c:
            raise HTTPException(status_code=404, detail="Customer not found.")
        return c

    def _waybill(db, session, waybill_id):
        wb = db.query(Waybill).filter(Waybill.id == waybill_id,
                                      Waybill.owner_phone == _session_owner_phone(db, session)).first()
        if not wb:
            raise HTTPException(status_code=404, detail="Waybill not found.")
        branch, rec = _scoped_read(db, session)
        if branch is not None and wb.branch_id != branch:
            raise HTTPException(status_code=404, detail="Waybill not found.")
        if rec is not None and wb.created_by_id != rec:
            tx = db.query(Transaction).filter(Transaction.id == wb.transaction_id).first() \
                if wb.transaction_id else None
            if not tx or tx.recorded_by_id != rec:
                raise HTTPException(status_code=404, detail="Waybill not found.")
        return wb

    @app.get("/app/api/waybills/new")
    def web_waybill_form(
        tx_id: Optional[int] = Query(default=None),
        invoice_id: Optional[int] = Query(default=None),
        customer_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """What the waybill form starts with: the lines (how many can go now)
        and the driver details from the last waybill."""
        from deliveries import goods_to_deliver
        from waybills import invoice_waybill_lines, last_details, sale_waybill_lines
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            if tx_id:
                tx = _sale(db, session, tx_id)
                cust_id, lines = tx.customer_id, sale_waybill_lines(db, owner_phone, tx)
                title = f"Receipt #{tx.receipt_number or tx.id}"
            elif invoice_id:
                from invoices import format_invoice_number
                inv = _invoice(db, session, invoice_id)
                cust_id, lines = inv.customer_id, invoice_waybill_lines(db, inv)
                title = format_invoice_number(inv.number)
            elif customer_id:
                cust = _customer(db, session, customer_id)
                cust_id, title = cust.id, None
                lines = [{"key": g["key"], "product": g["product"], "unit": g["unit"], "bought": g["bought"],
                          "handed_over": False, "to_deliver": g["remaining"], "max": g["can_send"],
                          "kept": g["kept"]}
                         for g in goods_to_deliver(db, owner_phone, cust.id, scope=_scoped_read(db, session))]
            else:
                raise HTTPException(status_code=400, detail="Make the waybill from a receipt, an invoice or a customer.")
            cust = db.query(Customer).filter(Customer.id == cust_id).first() if cust_id else None
            return {
                "title": title, "lines": lines,
                "customer": {"id": cust.id, "name": (cust.name or "").title(),
                             "phone": cust.customer_phone} if cust else None,
                "details": last_details(db, owner_phone, cust_id),
            }
        finally:
            db.close()

    @app.post("/app/api/waybills")
    def web_create_waybill(payload: WaybillRequest, session: dict = Depends(require_web_auth)):
        """Make a waybill: goods still to deliver leave stock now, and the
        customer gets a WhatsApp note of what is on its way."""
        from customer_statement import self_send_url
        from waybills import WaybillError, create_waybill, waybill_document, waybill_note_text
        from whatsapp_client import send_whatsapp_message
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            owner_phone = _session_owner_phone(db, session)
            tx = _sale(db, session, payload.tx_id) if payload.tx_id else None
            inv = _invoice(db, session, payload.invoice_id) if payload.invoice_id else None
            cust_id = _customer(db, session, payload.customer_id).id \
                if (payload.customer_id and not tx and not inv) else None
            try:
                wb = create_waybill(
                    db, owner_phone, session["user_id"], tx=tx, inv=inv, customer_id=cust_id,
                    lines=[l.model_dump() for l in payload.lines],
                    details=payload.model_dump(include={"driver_name", "driver_phone", "vehicle",
                                                        "loaders", "address", "note"}),
                    scope=_scoped_read(db, session),
                )
            except WaybillError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            doc = waybill_document(db, wb)
            text = waybill_note_text(doc)
            phone = (doc.get("customer") or {}).get("phone")
            sent = False
            if phone and payload.notify:
                try:
                    sent = bool(send_whatsapp_message(phone, text))
                except Exception:
                    sent = False
            return {**doc, "message": text, "sent": sent, "has_phone": bool(phone),
                    "wa_link": None if sent or not phone else self_send_url(phone, text)}
        finally:
            db.close()

    @app.get("/app/api/waybills")
    def web_list_waybills(
        tx_id: Optional[int] = Query(default=None),
        invoice_id: Optional[int] = Query(default=None),
        customer_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        from waybills import list_waybills
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            if tx_id:
                _sale(db, session, tx_id)
            if invoice_id:
                _invoice(db, session, invoice_id)
            branch, rec = _scoped_read(db, session)
            rows = list_waybills(db, owner_phone, tx_id=tx_id, invoice_id=invoice_id,
                                 customer_id=customer_id, branch_id=branch)
            if rec is not None and not tx_id and not invoice_id:
                mine = {w.id for w in db.query(Waybill.id).filter(Waybill.owner_phone == owner_phone,
                                                                  Waybill.created_by_id == rec).all()}
                rows = [r for r in rows if r["id"] in mine]
            return {"waybills": rows}
        finally:
            db.close()

    @app.get("/app/api/waybills/{waybill_id}")
    def web_get_waybill(waybill_id: int, session: dict = Depends(require_web_auth)):
        from waybills import waybill_document, waybill_note_text
        db = SessionLocal()
        try:
            doc = waybill_document(db, _waybill(db, session, waybill_id))
            user = _session_user(db, session)
            doc["can_cancel"] = bool(user and (user.parent_id is None or user.can_view_all_transactions))
            doc["message"] = waybill_note_text(doc)
            return doc
        finally:
            db.close()

    @app.post("/app/api/waybills/{waybill_id}/cancel")
    def web_cancel_waybill(waybill_id: int, payload: WaybillCancelRequest,
                           session: dict = Depends(require_web_auth)):
        """The goods did not go: back in the store, back on the customer's list."""
        from waybills import WaybillError, cancel_waybill, waybill_document
        db = SessionLocal()
        try:
            user = _require_full_access(db, session, "cancel a waybill")
            wb = _waybill(db, session, waybill_id)
            try:
                cancel_waybill(db, wb.owner_phone, user.id, wb, payload.reason)
            except WaybillError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return waybill_document(db, wb)
        finally:
            db.close()

    @app.post("/app/api/deliveries/goods/keep")
    def web_keep_aside(payload: KeepAsideRequest, session: dict = Depends(require_web_auth)):
        """Keep a customer's goods aside in the store (or release them: 0)."""
        from deliveries import DeliveryError, set_kept_aside
        db = SessionLocal()
        try:
            _require_full_access(db, session, "keep goods aside or release them")
            owner_phone = _session_owner_phone(db, session)
            cust = _customer(db, session, payload.customer_id)
            try:
                done = set_kept_aside(db, owner_phone, cust.id, payload.key, payload.kept,
                                      scope=_scoped_read(db, session))
            except DeliveryError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return done
        finally:
            db.close()

    @app.get("/app/api/inventory/{item_id}/waiting")
    def web_item_waiting(item_id: int, session: dict = Depends(require_web_auth)):
        """Customers still waiting for this product — shown after adding stock
        so the owner can keep some aside for them."""
        from deliveries import free_in_store, goods_to_deliver
        from models import InventoryItem
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            item = db.query(InventoryItem).filter(InventoryItem.id == item_id,
                                                  InventoryItem.owner_phone == owner_phone).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found.")
            rows = [g for g in goods_to_deliver(db, owner_phone, scope=_scoped_read(db, session))
                    if g["inventory_item_id"] == item.id]
            free = free_in_store(db, owner_phone, item)
            return {"item": {"id": item.id, "name": item.name.title(), "unit": item.unit,
                             "in_store": item.quantity, "free": free},
                    "waiting": [{"customer_id": g["customer_id"], "customer": g["customer"], "key": g["key"],
                                 "remaining": g["remaining"], "kept": g["kept"]} for g in rows]}
        finally:
            db.close()
