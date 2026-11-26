"""
Stock transfers between branches (stock_transfers.py): list, send, view the
transfer note, receive (when the receiving branch confirms), cancel.

Stock managers only (the owner, admins allowed to change stock). An admin kept
to their branch sends only from it and receives only into it.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Branch, StockTransfer
from web_auth import require_web_auth
from web_common import _require_stock_manager, _scoped_read, _session_owner_phone


class TransferLineIn(BaseModel):
    item_id: int
    quantity: float


class CreateTransferRequest(BaseModel):
    from_branch_id: int
    to_branch_id: int
    lines: list[TransferLineIn] = Field(max_length=200)
    carried_by: Optional[str] = Field(default=None, max_length=80)
    carrier_phone: Optional[str] = Field(default=None, max_length=30)
    note: Optional[str] = Field(default=None, max_length=300)


class ReceiveTransferRequest(BaseModel):
    received: dict[int, float] = Field(default_factory=dict)   # line id → what arrived
    note: Optional[str] = Field(default=None, max_length=300)


class CancelTransferRequest(BaseModel):
    reason: str = Field(max_length=300)


def register_transfer_routes(app):
    import stock_transfers as st

    def _get(db, session, transfer_id):
        owner_phone = _session_owner_phone(db, session)
        scope, _rec = _scoped_read(db, session)
        tr = st.visible(db, owner_phone, scope).filter(StockTransfer.id == transfer_id).first()
        if not tr:
            raise HTTPException(status_code=404, detail="Transfer not found.")
        return owner_phone, scope, tr

    def _branches(db, owner_phone):
        return {b.id: b.name for b in db.query(Branch).filter(Branch.owner_phone == owner_phone).all()}

    def _can(user, scope, branch_id):
        return bool(user) and (scope is None or scope == branch_id)

    @app.get("/app/api/transfers")
    def web_transfers(session: dict = Depends(require_web_auth),
                      status: Optional[str] = Query(default=None, pattern="^(on_the_way|received|cancelled)$"),
                      limit: int = Query(default=100, ge=1, le=500)):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            scope, _rec = _scoped_read(db, session)
            q = st.visible(db, owner_phone, scope)
            on_way = q.filter(StockTransfer.status == "on_the_way")
            to_receive = on_way if scope is None else on_way.filter(StockTransfer.to_branch_id == scope)
            if status:
                q = q.filter(StockTransfer.status == status)
            names = _branches(db, owner_phone)
            rows = q.order_by(StockTransfer.id.desc()).limit(limit).all()
            from app_settings import business_setting
            return {"transfers": [st.summary(db, t, names) for t in rows],
                    "to_receive": to_receive.count(),
                    "confirm": bool(business_setting(db, owner_phone, "transfer_confirm"))}
        finally:
            db.close()

    @app.post("/app/api/transfers")
    def web_create_transfer(payload: CreateTransferRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            scope, _rec = _scoped_read(db, session)
            if scope is not None and payload.from_branch_id != scope:
                raise HTTPException(status_code=403, detail="You can send stock only from your own branch.")
            from app_settings import business_setting
            try:
                tr = st.create_transfer(
                    db, owner_phone, user, payload.from_branch_id, payload.to_branch_id,
                    [line.model_dump() for line in payload.lines],
                    carried_by=payload.carried_by, carrier_phone=payload.carrier_phone, note=payload.note,
                    confirm=bool(business_setting(db, owner_phone, "transfer_confirm")))
            except st.TransferError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return st.summary(db, tr, _branches(db, owner_phone))
        finally:
            db.close()

    @app.get("/app/api/transfers/{transfer_id}")
    def web_transfer(transfer_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_stock_manager(db, session)
            _owner, scope, tr = _get(db, session, transfer_id)
            doc = st.document(db, tr)
            waiting = tr.status == "on_the_way"
            doc["can_receive"] = waiting and _can(user, scope, tr.to_branch_id)
            doc["can_cancel"] = waiting and _can(user, scope, tr.from_branch_id)
            return doc
        finally:
            db.close()

    @app.post("/app/api/transfers/{transfer_id}/receive")
    def web_receive_transfer(transfer_id: int, payload: ReceiveTransferRequest,
                             session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_stock_manager(db, session)
            _owner, scope, tr = _get(db, session, transfer_id)
            if not _can(user, scope, tr.to_branch_id):
                raise HTTPException(status_code=403, detail="Only the receiving branch can confirm what arrived.")
            try:
                st.receive(db, tr, user, payload.received or None, payload.note)
            except st.TransferError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return st.document(db, tr)
        finally:
            db.close()

    @app.post("/app/api/transfers/{transfer_id}/cancel")
    def web_cancel_transfer(transfer_id: int, payload: CancelTransferRequest,
                            session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_stock_manager(db, session)
            _owner, scope, tr = _get(db, session, transfer_id)
            if not _can(user, scope, tr.from_branch_id):
                raise HTTPException(status_code=403, detail="Only the sending branch can cancel it.")
            try:
                st.cancel(db, tr, user, payload.reason)
            except st.TransferError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return st.document(db, tr)
        finally:
            db.close()
