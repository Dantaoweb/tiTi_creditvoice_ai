"""
Marketer routes (marketers.py):
  admin     GET  /app/api/admin/marketers, POST …, PUT …/{id}, GET …/{id},
            POST …/{id}/pay, PUT /app/api/admin/marketer-settings
  marketer  GET  /app/api/marketer/me
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Marketer
from web_auth import require_web_auth
from web_common import _admin_rate_check, _session_user


class MarketerIn(BaseModel):
    name: str = Field(max_length=100)
    phone: str = Field(max_length=20)
    percent: Optional[float] = None
    code: Optional[str] = Field(default=None, max_length=16)
    note: Optional[str] = Field(default=None, max_length=200)


class MarketerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    percent: Optional[float] = None
    use_default_percent: bool = False
    status: Optional[str] = Field(default=None, max_length=10)
    note: Optional[str] = Field(default=None, max_length=200)


class PayIn(BaseModel):
    earning_ids: Optional[list[int]] = Field(default=None, max_length=1000)   # None = all owed
    reference: Optional[str] = Field(default=None, max_length=80)


class SettingsIn(BaseModel):
    default_percent: float


def register_marketer_routes(app):
    import marketers as mk

    def _admin(db, session):
        from admin import is_app_admin
        user = _session_user(db, session)
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only.")
        if not _admin_rate_check(user.phone):
            raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
        return user

    def _err(fn):
        try:
            return fn()
        except mk.MarketerError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def _get(db, marketer_id):
        m = db.query(Marketer).filter(Marketer.id == marketer_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Marketer not found.")
        return m

    @app.get("/app/api/admin/marketers")
    def admin_marketers(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _admin(db, session)
            return mk.admin_overview(db)
        finally:
            db.close()

    @app.post("/app/api/admin/marketers")
    def admin_add_marketer(payload: MarketerIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            me = _admin(db, session)
            m = _err(lambda: mk.add_marketer(db, payload.name, payload.phone, payload.percent, payload.code,
                                             payload.note, by=me.phone))
            return mk.summary(db, m)
        finally:
            db.close()

    @app.get("/app/api/admin/marketers/{marketer_id}")
    def admin_marketer(marketer_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _admin(db, session)
            return mk.summary(db, _get(db, marketer_id), with_detail=True)
        finally:
            db.close()

    @app.put("/app/api/admin/marketers/{marketer_id}")
    def admin_update_marketer(marketer_id: int, payload: MarketerUpdate, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _admin(db, session)
            m = _get(db, marketer_id)
            pct = None if payload.use_default_percent else (payload.percent if payload.percent is not None else "keep")
            _err(lambda: mk.update_marketer(db, m, payload.name, pct, payload.status, payload.note))
            return mk.summary(db, m)
        finally:
            db.close()

    @app.post("/app/api/admin/marketers/{marketer_id}/pay")
    def admin_pay_marketer(marketer_id: int, payload: PayIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            me = _admin(db, session)
            m = _get(db, marketer_id)
            total, n = _err(lambda: mk.mark_paid(db, m, payload.earning_ids, payload.reference, by=me.phone))
            return {"paid": total, "count": n, "marketer": mk.summary(db, m)}
        finally:
            db.close()

    @app.put("/app/api/admin/marketer-settings")
    def admin_marketer_settings(payload: SettingsIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            me = _admin(db, session)
            return {"default_percent": _err(lambda: mk.set_default_percent(db, payload.default_percent, me.phone))}
        finally:
            db.close()

    @app.get("/app/api/marketer/me")
    def marketer_me(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            m = mk.for_user(db, _session_user(db, session))
            if not m:
                raise HTTPException(status_code=403, detail="This account isn't a CreditVoice marketer.")
            return mk.summary(db, m, with_detail=True)
        finally:
            db.close()
