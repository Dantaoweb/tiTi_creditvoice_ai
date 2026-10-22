"""
Expiry on the web (expiry.py): what's expired or expiring soon, and writing
expired goods off as a loss (owner and branch admins — like other stock
changes).
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from database import SessionLocal
from models import InventoryItem
from web_auth import require_web_auth
from web_common import _require_stock_manager, _scoped_read, _session_owner_phone


class WriteOffRequest(BaseModel):
    quantity: float


def register_expiry_routes(app):
    from app_settings import business_setting
    from expiry import ExpiryError, expiring, write_off_expired

    @app.get("/app/api/inventory/expiry")
    def web_expiry(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            days = business_setting(db, owner_phone, "expiry_warn_days")
            branch, _rec = _scoped_read(db, session)
            rows = expiring(db, owner_phone, days, branch_id=branch)
            return {"warn_days": days, "items": rows,
                    "expired": sum(1 for r in rows if r["expired_qty"]),
                    "soon": sum(1 for r in rows if r["soon_qty"])}
        finally:
            db.close()

    @app.post("/app/api/inventory/{item_id}/write-off-expired")
    def web_write_off_expired(item_id: int, payload: WriteOffRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_stock_manager(db, session)
            item = db.query(InventoryItem).filter(InventoryItem.id == item_id,
                                                  InventoryItem.owner_phone == _session_owner_phone(db, session)).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found.")
            try:
                write_off_expired(db, item.owner_phone, item, payload.quantity, user.id)
            except ExpiryError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return {"ok": True, "quantity": item.quantity}
        finally:
            db.close()
