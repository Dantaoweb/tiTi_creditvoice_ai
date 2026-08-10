"""
Auth + account routes: login, register, business categories, OTP config /
channels / request, set-pin, logout(+all), profile edit, NDPR erasure & DSAR,
and the /auth/me session bootstrap.

Split out of web_routes.py. Register with register_auth_routes(app); shared
helpers come from web_common. Auth primitives come from web_auth.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import (
    clear_auth_cookie, get_otp_channels, require_web_auth,
    set_auth_cookie, web_login, web_register, request_web_otp, verify_otp_and_set_pin,
)
from web_common import _session_user, _session_subscription


class LoginRequest(BaseModel):
    phone: str = Field(max_length=20)
    pin: str = Field(max_length=10)


class RegisterRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: str = Field(max_length=20)
    pin: str = Field(max_length=10)
    email: Optional[str] = Field(default=None, max_length=254)
    newsletter_consent: bool = False
    business_category: Optional[str] = Field(default=None, max_length=60)
    business_type: Optional[str] = Field(default=None, max_length=60)
    business_type_label: Optional[str] = Field(default=None, max_length=120)
    ref_code: Optional[str] = Field(default=None, max_length=20)


class OtpRequest(BaseModel):
    phone: str = Field(max_length=20)
    channel: str = Field(default="auto", max_length=20)
    email: str = Field(default="", max_length=200)


class SetPinRequest(BaseModel):
    phone: str = Field(max_length=20)
    otp: str = Field(max_length=10)
    new_pin: str = Field(max_length=10)


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    business_type_label: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=300)


class DeleteAccountRequest(BaseModel):
    pin: str


def register_auth_routes(app):

    @app.post("/app/api/auth/login")
    def web_auth_login(payload: LoginRequest, response: Response, request: Request):
        db = SessionLocal()
        try:
            ip = request.client.host if request.client else None
            result = web_login(db, payload.phone.strip(), payload.pin.strip(), ip=ip)
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.get("/app/api/auth/business-categories")
    def web_business_categories():
        from business_templates import BUSINESS_CATEGORIES
        return {
            "categories": [
                {
                    "key": c["key"],
                    "label": c["label"],
                    "businesses": [
                        {"key": b[0], "label": b[1]} for b in c["businesses"]
                    ],
                }
                for c in BUSINESS_CATEGORIES
            ]
        }

    @app.post("/app/api/auth/register")
    def web_auth_register(payload: RegisterRequest, response: Response, request: Request):
        db = SessionLocal()
        try:
            client_ip = request.client.host if request.client else "unknown"
            result = web_register(
                db,
                payload.name.strip(),
                payload.phone.strip(),
                payload.pin.strip(),
                email=payload.email,
                newsletter_consent=payload.newsletter_consent,
                business_category=payload.business_category,
                business_type=payload.business_type,
                business_type_label=payload.business_type_label,
                ref_code=payload.ref_code,
                client_ip=client_ip,
            )
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.get("/app/api/auth/config")
    def web_auth_config():
        import os
        titi_number = os.getenv("TITI_WHATSAPP", "").strip()
        from web_push import VAPID_PUBLIC_KEY, push_enabled
        return {
            "titi_whatsapp": titi_number,
            "push_enabled": push_enabled(),
            "vapid_public_key": VAPID_PUBLIC_KEY if push_enabled() else "",
        }

    @app.get("/app/api/auth/otp-channels")
    def web_otp_channels(phone: str = Query(...), request: Request = None):
        from web_auth import _rate_check, _PROBE_LIMIT, _PROBE_WINDOW
        client_ip = request.client.host if request and request.client else "unknown"
        if not _rate_check(f"probe:{client_ip}", _PROBE_LIMIT, _PROBE_WINDOW):
            raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
        db = SessionLocal()
        try:
            return get_otp_channels(db, phone.strip())
        finally:
            db.close()

    @app.post("/app/api/auth/request-otp")
    def web_request_otp(payload: OtpRequest):
        db = SessionLocal()
        try:
            return request_web_otp(db, payload.phone.strip(), payload.channel,
                                   email=payload.email.strip() if payload.email else None)
        finally:
            db.close()

    @app.post("/app/api/auth/set-pin")
    def web_set_pin(payload: SetPinRequest, response: Response):
        db = SessionLocal()
        try:
            result = verify_otp_and_set_pin(db, payload.phone.strip(), payload.otp.strip(), payload.new_pin.strip())
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.post("/app/api/auth/logout")
    def web_auth_logout(response: Response):
        clear_auth_cookie(response)
        return {"ok": True}

    @app.post("/app/api/auth/logout-all")
    def web_auth_logout_all(response: Response, session: dict = Depends(require_web_auth)):
        """Sign out of every device: bump the user's session epoch so all tokens
        issued so far stop working immediately."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if user:
                user.token_version = (user.token_version or 0) + 1
                db.commit()
            clear_auth_cookie(response)
            return {"ok": True, "message": "Signed out of all devices."}
        finally:
            db.close()

    @app.put("/app/api/auth/profile")
    def web_update_profile(payload: ProfileUpdateRequest, session: dict = Depends(require_web_auth)):
        """Edit the signed-in user's profile. Everyone may change their own
        display name; the business label/address (which appear on receipts) are
        the owner's, so only a business owner can change those."""
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            if payload.name is not None and payload.name.strip():
                user.name = payload.name.strip()
            is_owner = user.parent_id is None
            if is_owner:
                if payload.business_type_label is not None:
                    user.business_type_label = payload.business_type_label.strip() or None
                if payload.address is not None:
                    user.address = payload.address.strip() or None
            db.commit()
            return {
                "ok": True,
                "name": user.name,
                "business_type_label": user.business_type_label,
                "address": user.address,
            }
        finally:
            db.close()

    # ── NDPR: right to erasure ────────────────────────────────────────────────
    @app.delete("/app/api/account")
    def web_delete_account(
        payload: DeleteAccountRequest,
        response: Response,
        session: dict = Depends(require_web_auth),
    ):
        """Permanently anonymise the caller's account (NDPR s.2.6 right to erasure).

        PII cleared: name, email, recovery_pin_hash, referral_code, shop_tag,
        newsletter_consent. Phone replaced with a non-reversible placeholder.
        Raw message logs (parse_logs, failed_parses) deleted. The User row is
        kept so that transaction foreign keys remain intact; deleted_at marks it
        as erased.  Logs the deletion in audit_log and clears the session cookie.
        """
        from recovery_commands import _verify_pin
        from audit import audit
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found.")
            if user.deleted_at:
                raise HTTPException(status_code=409, detail="Account already deleted.")
            if not user.recovery_pin_hash or not _verify_pin(payload.pin.strip(), user.recovery_pin_hash):
                raise HTTPException(status_code=401, detail="Incorrect PIN.")

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            anon_phone = f"DELETED_{user.id}"

            # Anonymise PII fields on the user record
            user.name               = "Deleted User"
            user.email              = None
            user.recovery_pin_hash  = None
            user.referral_code      = None
            user.shop_tag           = None
            user.newsletter_consent = False
            user.whatsapp_linked    = False
            user.pin_attempts       = 0
            user.pin_locked_until   = None
            user.deleted_at         = now

            # Replace phone with a non-reversible placeholder so the unique
            # constraint is freed and the original phone can re-register later
            from models import ParseLog, FailedParse
            db.query(ParseLog).filter(ParseLog.phone == user.phone).delete()
            db.query(ParseLog).filter(ParseLog.owner_phone == user.phone).delete()
            db.query(FailedParse).filter(FailedParse.phone == user.phone).delete()
            db.query(FailedParse).filter(FailedParse.owner_phone == user.phone).delete()

            audit(db, action="ACCOUNT_DELETION", actor_id=user.id,
                  actor_phone=user.phone, resource=f"user:{user.id}")

            user.phone = anon_phone
            db.commit()
            clear_auth_cookie(response)
            return {"ok": True, "message": "Your account and personal data have been deleted."}
        finally:
            db.close()

    # ── NDPR: data subject access request (DSAR) ─────────────────────────────
    @app.get("/app/api/account/personal-data")
    def web_personal_data(session: dict = Depends(require_web_auth)):
        """Return a copy of all personal data held for this user (NDPR s.2.5)."""
        from models import Customer, Transaction, ParseLog
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found.")

            tx_count  = db.query(Transaction).filter(Transaction.owner_phone == user.phone).count()
            cust_count= db.query(Customer).filter(Customer.owner_phone == user.phone).count()
            log_count = db.query(ParseLog).filter(ParseLog.phone == user.phone).count()

            return {
                "personal_data": {
                    "name":                user.name,
                    "phone":               user.phone,
                    "email":               user.email,
                    "created_at":          user.created_at.isoformat() if user.created_at else None,
                    "newsletter_consent":  bool(user.newsletter_consent),
                    "whatsapp_linked":     bool(user.whatsapp_linked),
                    "subscription_plan":   user.subscription_plan,
                    "wallet_balance_ngn":  (user.wallet_balance or 0) / 100,
                },
                "data_held": {
                    "transactions":        tx_count,
                    "customers":           cust_count,
                    "message_logs":        log_count,
                },
                "your_rights": (
                    "Under the Nigeria Data Protection Regulation (NDPR) you have the right "
                    "to access, correct, and erase your personal data. To delete your account "
                    "and all associated personal data, use DELETE /app/api/account with your PIN."
                ),
            }
        finally:
            db.close()

    @app.get("/app/api/auth/me")
    def web_auth_me(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")

            # Resolve the plan from the business owner (follows parent_id) and
            # apply expiry — the same source of truth as the WhatsApp side and
            # /subscription/status. This keeps web feature-gating in sync with
            # upgrades made on WhatsApp, and lets staff inherit the owner's plan.
            sub = _session_subscription(db, session)

            from business_templates import menu_group_for_user, template_examples_for_user
            from admin import is_app_admin
            try:
                examples = [str(e) for e in (template_examples_for_user(user) or [])][:4]
            except Exception:
                examples = []
            return {
                "id": user.id,
                "name": user.name,
                "phone": user.phone,
                "email": user.email,
                "role": user.role,
                # Admin-ness lives in APP_ADMIN_PHONES / AppAdminRole, not user.role —
                # the frontend gates the Admin menu on this flag.
                "is_app_admin": bool(is_app_admin(user.phone, db)),
                "plan": sub["plan"],
                "subscription_plan": sub["plan"],
                "subscription_expires_at": sub["expires_at"].isoformat() if sub["expires_at"] else None,
                "examples": examples,
                "business_category": user.business_category,
                "business_type": user.business_type,
                "business_type_label": user.business_type_label,
                "address": user.address,
                "menu_group": menu_group_for_user(user),
                "whatsapp_linked": bool(user.whatsapp_linked),
                "newsletter_consent": bool(user.newsletter_consent),
                # A staff/sub-account has a parent; owners don't. The Staff page
                # gates the invite UI on this.
                "parent_id": user.parent_id,
                # Owner or branch admin — may manage stock, branches, etc.
                "full_access": user.parent_id is None or bool(user.can_view_all_transactions),
            }
        finally:
            db.close()
