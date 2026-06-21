"""
Stateless HMAC-signed session tokens for the web app.
No external dependencies — uses Python's built-in hmac + hashlib.
"""
import base64
import hashlib
import hmac
import os
import random
import string
import time
from datetime import datetime, timedelta, timezone

from typing import Optional

from fastapi import Cookie, Header, HTTPException, Response
from sqlalchemy.orm import Session

from models import PendingAction, User
from recovery_commands import _hash_pin, _verify_pin

_SECRET = os.getenv("WEB_SECRET_KEY", "cv-web-secret-change-in-production")
_TTL = 7 * 24 * 3600  # 7 days
_OTP_ACTION = "WEB_OTP"
_SECURE_COOKIE = os.getenv("ENVIRONMENT", "production") != "development"

_WEAK_KEYS = {
    "cv-web-secret-change-in-production",
    "your_web_secret_key",
    "change_me",
    "secret",
    "replace_with_64_char_hex_secret",
}
if _SECRET in _WEAK_KEYS or len(_SECRET) < 32:
    import warnings
    warnings.warn(
        "WEB_SECRET_KEY is weak or a placeholder. "
        "Generate a strong value with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and set it in your environment before going to production.",
        stacklevel=1,
    )

# ── Simple in-memory rate limiter for auth endpoints ─────────────────────────
import threading
from collections import defaultdict

_auth_lock = threading.Lock()
_auth_attempts: dict[str, list[float]] = defaultdict(list)
_AUTH_LIMIT  = 10   # max attempts
_AUTH_WINDOW = 900  # per 15 minutes

# Tighter limits for OTP verification to prevent brute-force of 6-digit codes
_OTP_VERIFY_LIMIT  = 5   # max wrong guesses per code
_OTP_VERIFY_WINDOW = 600 # 10 minutes (matches OTP validity)

# Registration: 5 accounts per IP per hour
_REG_LIMIT  = 5
_REG_WINDOW = 3600

# OTP-channels probe: 30 phone lookups per IP per 10 minutes
_PROBE_LIMIT  = 30
_PROBE_WINDOW = 600


def _auth_rate_check(key: str) -> bool:
    """Return True if allowed, False if rate-limited. Key = phone or IP."""
    now = time.time()
    cutoff = now - _AUTH_WINDOW
    with _auth_lock:
        _auth_attempts[key] = [t for t in _auth_attempts[key] if t > cutoff]
        if len(_auth_attempts[key]) >= _AUTH_LIMIT:
            return False
        _auth_attempts[key].append(now)
        return True


def _rate_check(key: str, limit: int, window: int) -> bool:
    """Generic sliding-window rate check backed by the same _auth_attempts store."""
    now = time.time()
    cutoff = now - window
    with _auth_lock:
        _auth_attempts[key] = [t for t in _auth_attempts[key] if t > cutoff]
        if len(_auth_attempts[key]) >= limit:
            return False
        _auth_attempts[key].append(now)
        return True


def _sign(payload: str) -> str:
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_web_token(user_id: str, phone: str) -> str:
    exp = int(time.time()) + _TTL
    payload = f"{user_id}|{phone}|{exp}"
    sig = _sign(payload)
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_web_token(token: str) -> dict | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit("|", 1)
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        user_id, phone, exp = payload.split("|", 2)
        if int(time.time()) > int(exp):
            return None
        return {"user_id": user_id, "phone": phone}
    except Exception:
        return None


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the session token as an httpOnly cookie."""
    response.set_cookie(
        key="cv_session",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="lax",
        max_age=_TTL,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key="cv_session", path="/")


def require_web_auth(
    cv_session: Optional[str] = Cookie(default=None),
    authorization: str = Header(default=""),
) -> dict:
    # Cookie is the primary auth method; Authorization header kept for backwards compat
    token = cv_session or authorization.removeprefix("Bearer ").strip()
    payload = verify_web_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return payload


def web_login(db: Session, phone: str, pin: str, ip: str = None) -> dict:
    from audit import audit
    if not _auth_rate_check(phone):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait 15 minutes.")
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=401, detail="Phone number not registered. Create an account first.")

    if not user.recovery_pin_hash:
        raise HTTPException(
            status_code=401,
            detail="No PIN set yet. Use 'Forgot PIN' below to set one.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if user.pin_locked_until and user.pin_locked_until > now:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 1 hour.")

    if not _verify_pin(pin, user.recovery_pin_hash):
        user.pin_attempts = (user.pin_attempts or 0) + 1
        if user.pin_attempts >= 5:
            user.pin_locked_until = now + timedelta(hours=1)
            user.pin_attempts = 0
        audit(db, action="LOGIN_FAIL", actor_phone=phone, ip=ip)
        db.commit()
        raise HTTPException(status_code=401, detail="Incorrect PIN.")

    user.pin_attempts = 0
    user.pin_locked_until = None
    audit(db, action="LOGIN_OK", actor_id=user.id, actor_phone=user.phone, ip=ip)
    db.commit()
    return _build_auth_response(user)


def get_otp_channels(db: Session, phone: str) -> dict:
    """Return what OTP delivery channels are available for this phone."""
    from email_service import mask_email
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Phone number not registered. Create an account first.",
        )
    return {
        "email_hint": mask_email(user.email) if user.email else None,
        "has_whatsapp": bool(user.whatsapp_linked),
    }


def request_web_otp(db: Session, phone: str, channel: str = "auto") -> dict:
    """Send a 6-digit OTP via email or WhatsApp depending on channel."""
    if not _auth_rate_check(f"otp:{phone}"):
        raise HTTPException(status_code=429, detail="Too many OTP requests. Please wait 15 minutes.")

    from email_service import send_otp_email
    from whatsapp_client import send_whatsapp_message

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Phone number not registered. Create an account first.",
        )

    has_email     = bool(user.email)
    has_whatsapp  = bool(user.whatsapp_linked)

    # "auto" sends to BOTH channels when both are available (stronger recovery)
    if channel == "auto":
        if has_email and has_whatsapp:
            channel = "both"
        elif has_email:
            channel = "email"
        else:
            channel = "whatsapp"

    if channel == "email" and not has_email:
        raise HTTPException(status_code=400, detail="No email address on this account. Use WhatsApp instead.")
    if channel == "whatsapp" and not has_whatsapp:
        raise HTTPException(status_code=400, detail="WhatsApp not linked yet. Use email instead.")

    # Clear old OTP
    db.query(PendingAction).filter(
        PendingAction.phone == phone,
        PendingAction.action == _OTP_ACTION,
    ).delete()

    otp = "".join(random.choices(string.digits, k=6))
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)

    db.add(PendingAction(
        phone=phone,
        customer_name="",
        last_customer="",
        action=_OTP_ACTION,
        product=otp,
        due_date=expiry,
    ))
    db.commit()

    sent_channels = []

    if channel in ("email", "both") and has_email:
        ok = send_otp_email(user.email, otp)
        if ok:
            sent_channels.append("email")

    if channel in ("whatsapp", "both") and has_whatsapp:
        try:
            send_whatsapp_message(
                phone,
                f"Your CreditVoice PIN reset code: *{otp}*\n\nValid for 10 minutes. Do not share this with anyone.",
            )
            sent_channels.append("whatsapp")
        except Exception:
            pass

    if not sent_channels:
        raise HTTPException(
            status_code=500,
            detail="Could not send the OTP. Check your email and WhatsApp settings.",
        )

    from audit import audit
    audit(db, action="OTP_REQUEST", actor_phone=phone,
          resource=",".join(sent_channels))
    db.commit()
    hint = user.email[:3] + "***" if "email" in sent_channels and user.email else phone
    return {"sent": True, "channel": sent_channels[0], "channels": sent_channels, "hint": hint}


def verify_otp_and_set_pin(db: Session, phone: str, otp: str, new_pin: str) -> dict:
    if not new_pin or len(new_pin.strip()) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 digits.")

    if not _rate_check(f"otp-verify:{phone}", _OTP_VERIFY_LIMIT, _OTP_VERIFY_WINDOW):
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new code.")

    pending = db.query(PendingAction).filter(
        PendingAction.phone == phone,
        PendingAction.action == _OTP_ACTION,
    ).first()

    if not pending:
        raise HTTPException(status_code=400, detail="No code found. Request a new one.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if pending.due_date and pending.due_date < now:
        db.delete(pending)
        db.commit()
        raise HTTPException(status_code=400, detail="Code expired. Request a new one.")

    if not hmac.compare_digest(pending.product, otp.strip()):
        # Track wrong guesses via the rate limiter bucket; burn OTP after 5 wrong attempts
        pending.quantity = (pending.quantity or 0) + 1
        if pending.quantity >= 5:
            db.delete(pending)
            db.commit()
            raise HTTPException(status_code=400, detail="Too many wrong attempts. Request a new code.")
        db.commit()
        raise HTTPException(status_code=400, detail="Incorrect code. Try again.")

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    from audit import audit
    user.recovery_pin_hash = _hash_pin(new_pin.strip())
    user.pin_attempts = 0
    user.pin_locked_until = None
    db.delete(pending)
    audit(db, action="PIN_RESET", actor_id=user.id, actor_phone=user.phone)
    db.commit()
    return _build_auth_response(user)


_REFERRAL_TRIAL_DAYS = 14
_REFERRAL_INVITE_LIMIT_BASIC = 2


def web_register(db: Session, name: str, phone: str, pin: str,
                 email: str = None, newsletter_consent: bool = False,
                 business_category: str = None, business_type: str = None,
                 business_type_label: str = None, ref_code: str = None,
                 client_ip: str = "unknown") -> dict:
    from email_service import send_welcome_email
    from models import Referral, ReferralSettings

    if not _rate_check(f"register:{client_ip}", _REG_LIMIT, _REG_WINDOW):
        raise HTTPException(status_code=429, detail="Too many registrations from this network. Try again later.")

    if not name.strip():
        raise HTTPException(status_code=400, detail="Full name is required.")
    if not phone.strip():
        raise HTTPException(status_code=400, detail="Phone number is required.")
    if not pin.strip() or len(pin.strip()) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 digits.")

    if db.query(User).filter(User.phone == phone.strip()).first():
        raise HTTPException(status_code=409, detail="This phone number is already registered. Sign in instead.")

    clean_email = email.strip().lower() if email and email.strip() else None
    if clean_email and db.query(User).filter(User.email == clean_email).first():
        raise HTTPException(status_code=409, detail="This email is already registered.")

    # Validate referral code
    referrer = None
    clean_ref = ref_code.strip().upper() if ref_code and ref_code.strip() else None
    if clean_ref:
        referrer = db.query(User).filter(User.referral_code == clean_ref).first()
        if not referrer:
            raise HTTPException(status_code=404, detail="Referral code not found.")
        if referrer.phone == phone.strip():
            raise HTTPException(status_code=400, detail="You can't use your own referral code.")
        referrer_plan = (referrer.subscription_plan or "BASIC").upper()
        if referrer_plan == "BASIC":
            used = db.query(Referral).filter(Referral.referral_code == clean_ref).count()
            if used >= _REFERRAL_INVITE_LIMIT_BASIC:
                raise HTTPException(status_code=403, detail="This referral code has reached its invite limit.")

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(tzinfo=None)
    plan = "GO" if referrer else "BASIC"
    expires_at = (now + __import__("datetime").timedelta(days=_REFERRAL_TRIAL_DAYS)) if referrer else None

    user = User(
        name=name.strip(),
        phone=phone.strip(),
        email=clean_email,
        newsletter_consent=newsletter_consent,
        role="owner",
        subscription_plan=plan,
        subscription_status="ACTIVE",
        subscription_expires_at=expires_at,
        business_category=business_category or None,
        business_type=business_type or None,
        business_type_label=business_type_label or None,
        recovery_pin_hash=_hash_pin(pin.strip()),
        whatsapp_linked=False,
        referred_by_code=clean_ref,
    )
    db.add(user)
    db.flush()

    if referrer:
        db.add(Referral(
            referral_code=clean_ref,
            referrer_phone=referrer.phone,
            referee_phone=user.phone,
            referee_name=user.name,
            status="pending",
        ))

    db.commit()
    db.refresh(user)

    if clean_email:
        send_welcome_email(clean_email, user.name)

    return _build_auth_response(user)


def _build_auth_response(user: User) -> dict:
    from business_templates import menu_group_for_user
    token = create_web_token(user.id, user.phone)
    session_expires_at = datetime.fromtimestamp(
        int(time.time()) + _TTL, tz=timezone.utc
    ).isoformat()
    return {
        "_token": token,  # used internally to set the cookie — not returned to client
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "email": user.email,
            "role": user.role,
            "plan": user.subscription_plan,
            "business_category": user.business_category,
            "business_type": user.business_type,
            "business_type_label": user.business_type_label,
            "menu_group": menu_group_for_user(user),
            "whatsapp_linked": bool(user.whatsapp_linked),
            "newsletter_consent": bool(user.newsletter_consent),
            "subscription_plan": user.subscription_plan,
            "subscription_expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
            "session_expires_at": session_expires_at,
        },
    }
