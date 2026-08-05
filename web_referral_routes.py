"""
Referral routes: referrer dashboard, set custom code, admin cashback settings
(get + set), and the admin per-referrer summary.

Split out of web_routes.py. Register with register_referral_routes(app);
shared helpers come from web_common.
"""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, Referral, ReferralSettings
from plans import PAID_PLANS, is_paid_plan
from web_auth import require_web_auth
from web_common import _admin_rate_check


def _get_cashback_amount(db) -> int:
    cfg = db.query(ReferralSettings).order_by(ReferralSettings.id.desc()).first()
    return cfg.cashback_amount if cfg else 500


def _count_active_go_invitees(db, referral_code: str) -> int:
    """Count how many of a referrer's invitees currently have an active paid
    (GO/PRO/PREMIUM) subscription."""
    if not referral_code:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    referee_phones = [
        r.referee_phone
        for r in db.query(Referral).filter(Referral.referral_code == referral_code).all()
    ]
    if not referee_phones:
        return 0
    return db.query(User).filter(
        User.phone.in_(referee_phones),
        User.subscription_plan.in_(PAID_PLANS),
        User.subscription_status == "ACTIVE",
        (User.subscription_expires_at == None) | (User.subscription_expires_at > now),
    ).count()


class SetReferralCodeRequest(BaseModel):
    code: str = Field(max_length=20)


class ReferralSettingsRequest(BaseModel):
    cashback_amount: int


def register_referral_routes(app):

    @app.get("/app/api/referral")
    def web_referral_get(session: dict = Depends(require_web_auth)):
        import os
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)

            plan = (user.subscription_plan or "BASIC").upper()
            referrals = db.query(Referral).filter(
                Referral.referral_code == user.referral_code
            ).all() if user.referral_code else []

            invite_limit = None if is_paid_plan(plan) else 2
            invite_used = len(referrals)
            cashback_per_referral = _get_cashback_amount(db)

            # Live active count — invitees currently on an active paid subscription
            active_go = _count_active_go_invitees(db, user.referral_code)
            not_yet_go = invite_used - active_go
            credit_this_month = active_go * cashback_per_referral if is_paid_plan(plan) else 0

            base_url = os.getenv("APP_BASE_URL", "").rstrip("/") or ""
            titi_wa = os.getenv("TITI_WHATSAPP", "").strip()
            link = f"{base_url}/app/login?mode=register&ref={user.referral_code}" if user.referral_code else None
            wa_link = f"https://wa.me/{titi_wa}?text=join%20{user.referral_code}" if user.referral_code and titi_wa else None

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            referee_phones = {r.referee_phone for r in referrals}
            referee_users = {u.phone: u for u in db.query(User).filter(User.phone.in_(referee_phones)).all()} if referee_phones else {}

            return {
                "referral_code": user.referral_code,
                "link": link,
                "wa_link": wa_link,
                "plan": plan,
                "invite_limit": invite_limit,
                "invite_used": invite_used,
                "active_go": active_go,
                "not_yet_go": not_yet_go,
                "cashback_per_referral": cashback_per_referral,
                "credit_this_month": credit_this_month,
                "referrals": [
                    {
                        "referee_name": r.referee_name,
                        "referee_phone": r.referee_phone,
                        "active": (
                            referee_users.get(r.referee_phone) is not None
                            and is_paid_plan(referee_users[r.referee_phone].subscription_plan)
                            and referee_users[r.referee_phone].subscription_status == "ACTIVE"
                            and (
                                referee_users[r.referee_phone].subscription_expires_at is None
                                or referee_users[r.referee_phone].subscription_expires_at > now
                            )
                        ),
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in referrals
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/referral/set-code")
    def web_referral_set_code(
        payload: SetReferralCodeRequest,
        session: dict = Depends(require_web_auth),
    ):
        import re
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            clean = payload.code.strip().upper()
            if not re.match(r"^[A-Z0-9]{3,20}$", clean):
                raise HTTPException(status_code=400, detail="Code must be 3–20 letters and numbers only, no spaces.")
            existing = db.query(User).filter(User.referral_code == clean, User.id != user.id).first()
            if existing:
                raise HTTPException(status_code=409, detail="That code is already taken. Try another.")
            user.referral_code = clean
            db.commit()
            return {"referral_code": clean}
        finally:
            db.close()

    @app.get("/app/api/admin/referral-settings")
    def web_admin_referral_settings_get(session: dict = Depends(require_web_auth)):
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
            amount = _get_cashback_amount(db)
            return {"cashback_amount": amount}
        finally:
            db.close()

    @app.post("/app/api/admin/referral-settings")
    def web_admin_referral_settings_set(
        payload: ReferralSettingsRequest,
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
            if payload.cashback_amount < 0:
                raise HTTPException(status_code=400, detail="Amount must be >= 0")
            cfg = ReferralSettings(
                cashback_amount=payload.cashback_amount,
                updated_by=user.phone,
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(cfg)
            from audit import audit
            audit(db, action="ADMIN_SETTINGS_CHANGE", actor_id=user.id,
                  actor_phone=user.phone,
                  resource=f"referral_cashback:{payload.cashback_amount}")
            db.commit()
            return {"cashback_amount": payload.cashback_amount}
        finally:
            db.close()

    @app.get("/app/api/admin/referrals")
    def web_admin_referrals(session: dict = Depends(require_web_auth)):
        """Per-referrer summary for the admin dashboard: who referred how many,
        how many are active GO/PRO, and the bonus each has earned."""
        from admin import is_app_admin
        from collections import defaultdict
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            rate = _get_cashback_amount(db)
            by_code = defaultdict(list)
            for r in db.query(Referral).all():
                by_code[r.referral_code].append(r)

            rows = []
            for code, rs in by_code.items():
                referrer = db.query(User).filter(User.referral_code == code).first()
                referrer_plan = (referrer.subscription_plan or "BASIC").upper() if referrer else "—"
                active_go = _count_active_go_invitees(db, code)
                # Bonus mirrors the user-facing credit: active paid invitees ×
                # rate, credited only while the referrer is on a paid plan.
                bonus = active_go * rate if is_paid_plan(referrer_plan) else 0
                rows.append({
                    "referral_code": code,
                    "referrer_phone": referrer.phone if referrer else (rs[0].referrer_phone if rs else None),
                    "referrer_name": referrer.name if referrer else None,
                    "referrer_plan": referrer_plan,
                    "total_invited": len(rs),
                    "active_go": active_go,
                    "bonus": bonus,
                })
            rows.sort(key=lambda x: (x["bonus"], x["total_invited"]), reverse=True)
            return {
                "referrers": rows,
                "cashback_per_referral": rate,
                "total_bonus": sum(r["bonus"] for r in rows),
                "total_referrals": sum(r["total_invited"] for r in rows),
            }
        finally:
            db.close()
