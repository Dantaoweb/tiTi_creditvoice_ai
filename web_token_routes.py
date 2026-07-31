"""
Token-code routes: admin generate (CSV), admin list, and user redeem.

Split out of web_routes.py. Register with register_token_routes(app); shared
helpers come from web_common. Generate/list are app-admin only; redeem is any
authenticated user (rate-limited).
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, TokenCode
from web_auth import require_web_auth
from web_common import _admin_rate_check, _redeem_rate_check, _safe_filename


class TokenGenerateRequest(BaseModel):
    plan: str = Field(max_length=10)
    duration_days: int
    count: int
    batch_label: str = Field(default="", max_length=60)
    expires_in_days: Optional[int] = None


class TokenRedeemRequest(BaseModel):
    code: str = Field(max_length=20)


def register_token_routes(app):

    @app.post("/app/api/admin/token-codes/generate")
    def web_admin_token_generate(
        payload: TokenGenerateRequest,
        session: dict = Depends(require_web_auth),
    ):
        import secrets, io, csv as _csv
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            plan = payload.plan.upper()
            if plan not in ("GO", "PRO"):
                raise HTTPException(status_code=400, detail="plan must be GO or PRO")
            if not (1 <= payload.count <= 1000):
                raise HTTPException(status_code=400, detail="count must be 1–1000")
            if payload.duration_days < 1:
                raise HTTPException(status_code=400, detail="duration_days must be >= 1")

            expires_at = None
            if payload.expires_in_days:
                expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=payload.expires_in_days)

            codes = []
            for _ in range(payload.count):
                while True:
                    raw = secrets.token_urlsafe(6).upper().replace("-", "").replace("_", "")[:8]
                    code_str = f"{plan}-{raw}"
                    if not db.query(TokenCode).filter(TokenCode.code == code_str).first():
                        break
                tc = TokenCode(
                    code=code_str,
                    plan=plan,
                    duration_days=payload.duration_days,
                    batch_label=payload.batch_label or None,
                    issued_by=user.phone,
                    expires_at=expires_at,
                )
                db.add(tc)
                codes.append(code_str)
            from audit import audit
            audit(db, action="ADMIN_TOKEN_GENERATE", actor_id=user.id,
                  actor_phone=user.phone,
                  resource=f"{plan}×{payload.count} {payload.duration_days}d")
            db.commit()

            buf = io.StringIO()
            w = _csv.writer(buf)
            from export_utils import _csv_safe
            w.writerow(["Code", "Plan", "Duration (days)", "Batch", "Expires"])
            for c in codes:
                w.writerow([_csv_safe(v) for v in (c, plan, payload.duration_days, payload.batch_label or "", expires_at or "")])
            buf.seek(0)
            filename = f"tokens_{plan}_{payload.batch_label or 'batch'}.csv"
            return StreamingResponse(
                iter([buf.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/admin/token-codes")
    def web_admin_token_list(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=50, le=200),
        batch: str = Query(default=""),
        session: dict = Depends(require_web_auth),
    ):
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            q = db.query(TokenCode)
            if batch:
                q = q.filter(TokenCode.batch_label.ilike(f"%{batch}%"))
            total = q.count()
            rows = q.order_by(TokenCode.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
            return {
                "total": total,
                "page": page,
                "rows": [
                    {
                        "id": r.id,
                        "code": r.code,
                        "plan": r.plan,
                        "duration_days": r.duration_days,
                        "batch_label": r.batch_label,
                        "redeemed": r.redeemed_at is not None,
                        "redeemed_by": r.redeemed_by_phone,
                        "redeemed_at": r.redeemed_at.isoformat() if r.redeemed_at else None,
                        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/token-codes/redeem")
    def web_token_redeem(
        payload: TokenRedeemRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="Not authenticated")

            if not _redeem_rate_check(str(session["user_id"])):
                raise HTTPException(status_code=429, detail="Too many attempts. Try again in an hour.")

            _INVALID = HTTPException(status_code=400, detail="Invalid or expired code.")

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            import re as _re
            from sqlalchemy import func as _func
            # Normalise the typed code (drop hyphens/spaces, uppercase) and match it
            # against the stored code with its hyphen removed, so a code entered
            # without the hyphen ("GOAB12CD34") still activates.
            _code_norm = _re.sub(r"[^A-Z0-9]", "", payload.code.upper())
            tc = db.query(TokenCode).filter(
                _func.upper(_func.replace(TokenCode.code, "-", "")) == _code_norm
            ).first()
            # Collapse all failure states into one generic error to prevent enumeration.
            if not tc or tc.redeemed_at or (tc.expires_at and tc.expires_at < now):
                raise _INVALID

            tc.redeemed_at = now
            tc.redeemed_by_phone = user.phone

            # Extend or set plan expiry
            current_expiry = user.subscription_expires_at
            if current_expiry and current_expiry > now:
                new_expiry = current_expiry + timedelta(days=tc.duration_days)
            else:
                new_expiry = now + timedelta(days=tc.duration_days)

            user.subscription_plan = tc.plan
            user.subscription_status = "ACTIVE"
            user.subscription_expires_at = new_expiry
            db.commit()

            return {
                "plan": tc.plan,
                "duration_days": tc.duration_days,
                "expires_at": new_expiry.isoformat(),
                "message": f"Activated! Your plan is now {tc.plan} for {tc.duration_days} days.",
            }
        finally:
            db.close()
