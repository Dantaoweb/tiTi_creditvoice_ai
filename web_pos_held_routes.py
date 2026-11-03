"""
Held sales at the till (pos_held.py): list, hold / update, delete.
Saving a held cart as a sale removes it (web_pos_routes, PosSaveRequest.held_id).
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from web_auth import require_web_auth
from web_common import _require_can_record, _scoped_read, _session_owner_phone, _session_user


class HoldRequest(BaseModel):
    id: Optional[int] = None                     # update this held cart
    items: list[dict] = Field(max_length=200)
    discount: Optional[dict] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = Field(default=None, max_length=120)
    customer_phone: Optional[str] = Field(default=None, max_length=20)
    label: Optional[str] = Field(default=None, max_length=80)
    total: int = 0
    branch_id: Optional[int] = None


def register_pos_held_routes(app):
    import pos_held
    from web_pos_routes import _recording_branch

    def _scope(db, session):
        user = _session_user(db, session)
        owner_phone = _session_owner_phone(db, session)
        eff_branch, rec_by = _scoped_read(db, session)
        return user, owner_phone, pos_held.visible(db, user, owner_phone, eff_branch, rec_by)

    @app.get("/app/api/pos/held")
    def web_pos_held_list(branch_id: Optional[int] = None, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _user, _owner, q = _scope(db, session)
            from models import HeldSale
            if branch_id is not None:
                q = q.filter((HeldSale.branch_id == branch_id) | (HeldSale.branch_id == None))  # noqa: E711
            rows = q.order_by(HeldSale.created_at.asc()).all()
            return {"held": [pos_held.serialize(db, h) for h in rows]}
        finally:
            db.close()

    @app.post("/app/api/pos/held")
    def web_pos_hold(payload: HoldRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)   # holding isn't a sale
            user, owner_phone, q = _scope(db, session)
            branch = _recording_branch(db, session, owner_phone, payload.branch_id)
            h = pos_held.hold(
                db, user, owner_phone, branch, held_id=payload.id, items=payload.items,
                discount=payload.discount, customer_id=payload.customer_id,
                customer_name=payload.customer_name, customer_phone=payload.customer_phone,
                label=payload.label, total=payload.total, scope=q,
            )
            return pos_held.serialize(db, h)
        except pos_held.HeldError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        finally:
            db.close()

    @app.delete("/app/api/pos/held/{held_id}")
    def web_pos_held_delete(held_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _user, owner_phone, q = _scope(db, session)
            from models import HeldSale
            if not q.filter(HeldSale.id == held_id).first():
                raise HTTPException(status_code=404, detail="That held sale is gone.")
            pos_held.release(db, owner_phone, held_id)
            return {"ok": True}
        finally:
            db.close()
