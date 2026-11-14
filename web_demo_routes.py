"""
Demo business routes (demo_business.py). Opening one moves the session to the
demo business and keeps the real login aside in the cv_return cookie; Exit
puts it back.
"""
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import (
    _SECURE_COOKIE, _TTL, _build_auth_response, require_web_auth, set_auth_cookie, verify_web_token,
)
from web_common import _session_user


class DemoIn(BaseModel):
    business_type: Optional[str] = Field(default=None, max_length=60)


def _keep_return(response, token):
    response.set_cookie(key="cv_return", value=token, httponly=True, secure=_SECURE_COOKIE,
                        samesite="lax", max_age=_TTL, path="/")


def register_demo_routes(app):
    import demo_business as demo

    def _demo_dict(db, d):
        return {"business_type": d.business_type, "label": d.business_type_label, "phone": d.phone} if d else None

    @app.get("/app/api/demo")
    def web_demo_state(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            me = _session_user(db, session)
            if me.is_demo:
                return {"in_demo": True, "demo": _demo_dict(db, me), "types": demo.type_list()}
            if not demo.can_demo(db, me):
                raise HTTPException(status_code=403, detail="The demo business is for CreditVoice admins and marketers.")
            return {"in_demo": False, "demo": _demo_dict(db, demo.current_demo(db, me)), "types": demo.type_list()}
        finally:
            db.close()

    @app.post("/app/api/demo/open")
    def web_demo_open(payload: DemoIn, response: Response, session: dict = Depends(require_web_auth),
                      cv_session: Optional[str] = Cookie(default=None)):
        """From your real account into your demo business (made now if you pick a
        type or have none yet)."""
        db = SessionLocal()
        try:
            me = _session_user(db, session)
            if me.is_demo:
                raise HTTPException(status_code=400, detail="You're already in the demo business.")
            if not demo.can_demo(db, me):
                raise HTTPException(status_code=403, detail="The demo business is for CreditVoice admins and marketers.")
            d = demo.current_demo(db, me)
            try:
                if payload.business_type or not d:
                    d = demo.create_demo(db, me, payload.business_type or "bakery")
            except demo.DemoError as e:
                raise HTTPException(status_code=400, detail=str(e))
            if cv_session:
                _keep_return(response, cv_session)
            result = _build_auth_response(d, db=db)
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.post("/app/api/demo/switch")
    def web_demo_switch(payload: DemoIn, response: Response, session: dict = Depends(require_web_auth)):
        """Inside the demo: show it as another kind of business (or the same one,
        fresh — Reset)."""
        db = SessionLocal()
        try:
            me = _session_user(db, session)
            if not me.is_demo:
                raise HTTPException(status_code=400, detail="Open the demo business first.")
            owner = db.query(User).filter(User.id == me.demo_owner_id).first()
            try:
                d = demo.create_demo(db, owner, payload.business_type or me.business_type)
            except demo.DemoError as e:
                raise HTTPException(status_code=400, detail=str(e))
            result = _build_auth_response(d, db=db)
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.post("/app/api/demo/exit")
    def web_demo_exit(response: Response, cv_session: Optional[str] = Cookie(default=None),
                      cv_return: Optional[str] = Cookie(default=None)):
        """Back to your real account."""
        back = verify_web_token(cv_return or "")
        here = verify_web_token(cv_session or "")
        db = SessionLocal()
        try:
            real = db.query(User).filter(User.id == back["user_id"]).first() if back else None
            if not real or real.deleted_at or (real.token_version or 0) != back.get("ver", 0) or real.is_demo:
                raise HTTPException(status_code=401, detail="Please log in again to your own account.")
            cur = db.query(User).filter(User.id == here["user_id"]).first() if here else None
            if cur and cur.is_demo and cur.demo_owner_id != real.id:
                raise HTTPException(status_code=403, detail="That isn't your demo business.")
            set_auth_cookie(response, cv_return)
            response.delete_cookie(key="cv_return", path="/", httponly=True, secure=_SECURE_COOKIE, samesite="lax")
            return _strip(_build_auth_response(real, db=db))
        finally:
            db.close()


def _strip(result):
    result.pop("_token", None)
    return result
