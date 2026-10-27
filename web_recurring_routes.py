"""
Repeat invoices on the web (recurring_invoices.py). Anyone who can write
invoices can set one to repeat, change, pause or stop it; branch staff see
their branch's repeats.
"""
from typing import List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Invoice, RecurringInvoice
from web_auth import require_web_auth
from web_common import _require_can_record, _scoped_read, _session_owner_phone


class RepeatRequest(BaseModel):
    every: str = Field(max_length=10)
    start: str = Field(max_length=10)                  # YYYY-MM-DD: the first repeat / the next one
    stop_after: Optional[int] = None
    stop_on: Optional[str] = Field(default=None, max_length=10)
    auto_send: bool = True


class RepeatItem(BaseModel):
    inventory_item_id: Optional[int] = None
    name: str = Field(max_length=120)
    qty: float = 1
    unit: Optional[str] = Field(default=None, max_length=30)
    unit_price: int = 0


class RepeatUpdate(RepeatRequest):
    items: Optional[List[RepeatItem]] = Field(default=None, max_length=100)
    discount: Optional[int] = None


class RepeatAction(BaseModel):
    action: str = Field(max_length=10)                 # pause | resume | stop


def register_recurring_routes(app):
    from recurring_invoices import RepeatError, list_repeats, make_repeat, row, set_status, update_repeat

    def _run(db, fn):
        try:
            out = fn()
        except RepeatError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        db.commit()
        return out

    def _load(db, session, model, obj_id, label):
        obj = db.query(model).filter(model.id == obj_id, model.owner_phone == _session_owner_phone(db, session)).first()
        branch, _rec = _scoped_read(db, session)
        if not obj or (branch is not None and obj.branch_id != branch):
            raise HTTPException(status_code=404, detail=f"{label} not found.")
        return obj

    @app.post("/app/api/invoices/doc/{invoice_id}/repeat")
    def web_make_repeat(invoice_id: int, payload: RepeatRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_can_record(db, session, count_sale=False)
            inv = _load(db, session, Invoice, invoice_id, "Invoice")
            r = _run(db, lambda: make_repeat(db, inv, user.id, every=payload.every, start=payload.start,
                                             stop_after=payload.stop_after, stop_on=payload.stop_on,
                                             auto_send=payload.auto_send))
            return row(db, r)
        finally:
            db.close()

    @app.get("/app/api/recurring-invoices")
    def web_list_repeats(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            branch, _rec = _scoped_read(db, session)
            return {"repeats": list_repeats(db, _session_owner_phone(db, session), branch_id=branch)}
        finally:
            db.close()

    @app.put("/app/api/recurring-invoices/{repeat_id}")
    def web_update_repeat(repeat_id: int, payload: RepeatUpdate, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            r = _load(db, session, RecurringInvoice, repeat_id, "Repeat invoice")
            _run(db, lambda: update_repeat(
                db, r, every=payload.every, next_date=payload.start, stop_after=payload.stop_after,
                stop_on=payload.stop_on, auto_send=payload.auto_send,
                items=[i.model_dump() for i in payload.items] if payload.items is not None else None,
                discount=payload.discount))
            return row(db, r)
        finally:
            db.close()

    @app.post("/app/api/recurring-invoices/{repeat_id}/status")
    def web_repeat_status(repeat_id: int, payload: RepeatAction, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            r = _load(db, session, RecurringInvoice, repeat_id, "Repeat invoice")
            _run(db, lambda: set_status(db, r, payload.action))
            return row(db, r)
        finally:
            db.close()
