"""
Purchase orders on the web (purchase_orders.py). The owner and authorised
staff — the people who manage stock — write, send, receive and close them.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import PurchaseOrder
from web_auth import require_web_auth
from web_common import _require_stock_manager, _scoped_read, _session_owner_phone


class POLineIn(BaseModel):
    inventory_item_id: Optional[int] = None
    product: Optional[str] = Field(default=None, max_length=120)
    unit: Optional[str] = Field(default=None, max_length=30)
    quantity: float = 0
    unit_cost: Optional[int] = None


class PORequest(BaseModel):
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = Field(default=None, max_length=120)
    lines: List[POLineIn] = Field(default_factory=list, max_length=200)
    expected_date: Optional[str] = Field(default=None, max_length=20)
    note: Optional[str] = Field(default=None, max_length=300)


class ArrivedIn(BaseModel):
    line_id: int
    quantity: float = 0
    expiry_date: Optional[str] = Field(default=None, max_length=20)
    batch_no: Optional[str] = Field(default=None, max_length=60)


class ReceiveRequest(BaseModel):
    lines: List[ArrivedIn] = Field(default_factory=list, max_length=200)
    paid_now: Optional[int] = None          # None = all paid; less = owed to the supplier
    due_date: Optional[str] = Field(default=None, max_length=20)


class CloseRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


def _date(v, what):
    if not v:
        return None
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {what}. Use YYYY-MM-DD.")


def register_po_routes(app):
    from purchase_orders import (
        POError, cancel_po, close_po, create_po, list_pos, mark_sent, po_document, po_text, receive,
        reorder_suggestions, update_po,
    )

    def _load(db, session, po_id):
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id,
                                            PurchaseOrder.owner_phone == _session_owner_phone(db, session)).first()
        branch, _rec = _scoped_read(db, session)
        if not po or (branch is not None and po.branch_id != branch):
            raise HTTPException(status_code=404, detail="Purchase order not found.")
        return po

    def _run(db, fn):
        try:
            out = fn()
        except POError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:                 # expiry date format
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        db.commit()
        return out

    @app.get("/app/api/purchase-orders")
    def web_pos_list(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            branch, _rec = _scoped_read(db, session)
            return {"orders": list_pos(db, _session_owner_phone(db, session), branch_id=branch)}
        finally:
            db.close()

    @app.get("/app/api/purchase-orders/suggestions")
    def web_po_suggestions(session: dict = Depends(require_web_auth)):
        """Low-stock products by usual supplier — to start an order."""
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            branch, _rec = _scoped_read(db, session)
            return {"groups": reorder_suggestions(db, _session_owner_phone(db, session), branch_id=branch)}
        finally:
            db.close()

    @app.post("/app/api/purchase-orders")
    def web_po_create(payload: PORequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_stock_manager(db, session)
            branch, _rec = _scoped_read(db, session)
            po = _run(db, lambda: create_po(
                db, _session_owner_phone(db, session), user.id, [l.model_dump() for l in payload.lines],
                supplier_id=payload.supplier_id, supplier_name=payload.supplier_name,
                expected_date=_date(payload.expected_date, "expected date"), note=payload.note, branch_id=branch))
            return po_document(db, po)
        finally:
            db.close()

    @app.get("/app/api/purchase-orders/{po_id}")
    def web_po_get(po_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            doc = po_document(db, _load(db, session, po_id))
            doc["message"] = po_text(doc)
            return doc
        finally:
            db.close()

    @app.put("/app/api/purchase-orders/{po_id}")
    def web_po_update(po_id: int, payload: PORequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            po = _load(db, session, po_id)
            _run(db, lambda: update_po(db, po, [l.model_dump() for l in payload.lines],
                                       supplier_id=payload.supplier_id, supplier_name=payload.supplier_name,
                                       expected_date=_date(payload.expected_date, "expected date"),
                                       note=payload.note))
            return po_document(db, po)
        finally:
            db.close()

    @app.post("/app/api/purchase-orders/{po_id}/send")
    def web_po_send(po_id: int, session: dict = Depends(require_web_auth)):
        """Send it to the supplier's WhatsApp; when WhatsApp can't reach them,
        a link to send it from the owner's own phone."""
        from customer_statement import self_send_url
        from whatsapp_client import send_whatsapp_message
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            po = _load(db, session, po_id)
            _run(db, lambda: mark_sent(db, po))
            doc = po_document(db, po)
            text = po_text(doc)
            phone = (doc.get("supplier") or {}).get("phone")
            sent = False
            if phone:
                try:
                    sent = bool(send_whatsapp_message(phone, text))
                except Exception:
                    sent = False
            return {**doc, "message": text, "sent": sent, "has_phone": bool(phone),
                    "wa_link": None if sent or not phone else self_send_url(phone, text)}
        finally:
            db.close()

    @app.post("/app/api/purchase-orders/{po_id}/receive")
    def web_po_receive(po_id: int, payload: ReceiveRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_stock_manager(db, session)
            po = _load(db, session, po_id)
            _run(db, lambda: receive(db, po, user.id, [l.model_dump() for l in payload.lines],
                                     paid_now=payload.paid_now, due_date=_date(payload.due_date, "due date")))
            return po_document(db, po)
        finally:
            db.close()

    @app.post("/app/api/purchase-orders/{po_id}/close")
    def web_po_close(po_id: int, payload: CloseRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            po = _load(db, session, po_id)
            _run(db, lambda: close_po(db, po, payload.reason))
            return po_document(db, po)
        finally:
            db.close()

    @app.post("/app/api/purchase-orders/{po_id}/cancel")
    def web_po_cancel(po_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            po = _load(db, session, po_id)
            _run(db, lambda: cancel_po(db, po))
            return po_document(db, po)
        finally:
            db.close()
