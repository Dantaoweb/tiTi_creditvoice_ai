"""
Distributor / van sales routes (distributors.py). The stock rule applies: the
owner and staff allowed to manage stock.
"""
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from web_auth import require_web_auth
from web_common import _require_stock_manager, _scoped_read, _session_owner_phone


class OutLine(BaseModel):
    item_id: int
    qty: float
    unit_price: Optional[int] = None


class SendOutIn(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = Field(default=None, max_length=120)
    customer_phone: Optional[str] = Field(default=None, max_length=20)
    lines: list[OutLine] = Field(max_length=100)
    note: Optional[str] = Field(default=None, max_length=200)


class SettleIn(BaseModel):
    returns: dict[str, dict] = Field(default_factory=dict)    # {line id: {"back": n, "spoilt": n}}
    paid: int = 0
    due_date: Optional[str] = None
    spoilt_reason: str = Field(default="expired", max_length=20)


def register_distributor_routes(app):
    import distributors as dv

    def _ctx(db, session):
        user = _require_stock_manager(db, session)
        branch, _rec = _scoped_read(db, session)
        return user, _session_owner_phone(db, session), branch

    def _err(fn):
        try:
            return fn()
        except dv.VanError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/app/api/distributors")
    def web_distributors(days: int = 30, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _u, owner_phone, branch = _ctx(db, session)
            return dv.overview(db, owner_phone, max(1, min(int(days), 366)), branch)
        finally:
            db.close()

    @app.post("/app/api/distributors/send-out")
    def web_distributor_send_out(payload: SendOutIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user, owner_phone, branch = _ctx(db, session)
            run = _err(lambda: dv.send_out(db, owner_phone, user.id, [l.model_dump() for l in payload.lines],
                                           payload.customer_id, payload.customer_name, payload.customer_phone,
                                           payload.note, branch))
            return dv.run_dict(db, run)
        finally:
            db.close()

    @app.post("/app/api/distributors/runs/{run_id}/settle")
    def web_distributor_settle(run_id: int, payload: SettleIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user, owner_phone, _b = _ctx(db, session)
            due = None
            if payload.due_date:
                try:
                    due = datetime.strptime(payload.due_date[:10], "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Pick a valid date.")
            if payload.spoilt_reason not in ("expired", "damaged", "stolen", "other"):
                raise HTTPException(status_code=400, detail="Pick why the returned goods can't be sold.")
            run = _err(lambda: dv.settle(db, owner_phone, user.id, run_id, payload.returns, payload.paid, due,
                                         payload.spoilt_reason))
            if run.sale_tx_id:
                from web_common import _send_web_receipt
                _send_web_receipt(db, owner_phone, run.sale_tx_id)
            return dv.run_dict(db, run)
        finally:
            db.close()
