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
_TTL       = 7 * 24 * 3600  # 7 days — regular users
_ADMIN_TTL = 8 * 3600        # 8 hours — admin users
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
    _msg = (
        "WEB_SECRET_KEY is weak or a placeholder — session tokens would be "
        "forgeable (anyone could mint an admin session). Generate a strong value "
        "with: python -c \"import secrets; print(secrets.token_hex(32))\" and set "
        "it in the environment."
    )
    # Fail closed in production: refuse to start rather than run with a session
    # secret that lets tokens be forged. Development still only warns.
    if os.getenv("ENVIRONMENT", "production") != "development":
        raise RuntimeError(_msg + " Refusing to start in production.")
    import warnings
    warnings.warn(_msg, stacklevel=1)

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


def create_web_token(user_id: str, phone: str, ttl: int = _TTL, token_version: int = 0) -> str:
    exp = int(time.time()) + ttl
    payload = f"{user_id}|{phone}|{exp}|{token_version}"
    sig = _sign(payload)
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_web_token(token: str) -> dict | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit("|", 1)
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        parts = payload.split("|")
        # payload = user_id|phone|exp[|ver]. ver was added for revocation; tokens
        # minted before it default to 0 (they stay valid until their epoch is bumped).
        if len(parts) < 3:
            return None
        user_id, phone, exp = parts[0], parts[1], parts[2]
        ver = int(parts[3]) if len(parts) > 3 else 0
        if int(time.time()) > int(exp):
            return None
        return {"user_id": user_id, "phone": phone, "ver": ver}
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
    response.delete_cookie(
        key="cv_session",
        path="/",
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="lax",
    )


def require_web_auth(
    cv_session: Optional[str] = Cookie(default=None),
    authorization: str = Header(default=""),
) -> dict:
    # Cookie is the primary auth method; Authorization header kept for backwards compat
    token = cv_session or authorization.removeprefix("Bearer ").strip()
    payload = verify_web_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    # Revocation check: the token's session epoch must still match the user's.
    # Bumping user.token_version (logout-all, PIN reset, owner revoke) kills every
    # token issued before the bump. One indexed lookup per request.
    from database import SessionLocal
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == payload["user_id"]).first()
        if not user or user.deleted_at or (user.token_version or 0) != payload.get("ver", 0):
            raise HTTPException(status_code=401, detail="Session ended. Please log in again.")
    finally:
        db.close()
    return payload


def phone_candidates(phone: str) -> list:
    """Both the raw and normalized (0803… ⇄ 234803…) forms of a phone, for
    matching a stored phone regardless of which format was used to write it."""
    from parser import normalize_phone
    raw = (phone or "").strip()
    candidates = {raw}
    norm = normalize_phone(raw)
    if norm:
        candidates.add(norm)
    candidates.discard("")
    return list(candidates)


def user_by_phone(db: Session, phone: str):
    """Find a user by phone, tolerant of local vs international format so a number
    entered either way (0803… or 234803…) resolves to the same account. Additive:
    it only widens matching, so users stored in either format keep working."""
    candidates = phone_candidates(phone)
    if not candidates:
        return None
    return db.query(User).filter(User.phone.in_(candidates)).first()


def web_login(db: Session, phone: str, pin: str, ip: str = None) -> dict:
    from audit import audit
    if not _auth_rate_check(phone):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait 15 minutes.")
    user = user_by_phone(db, phone)
    # Treat a soft-deleted (admin-removed) account as not registered — don't
    # reveal that it exists, and never issue it a token.
    if not user or user.deleted_at:
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
    return _build_auth_response(user, db=db)


def get_otp_channels(db: Session, phone: str) -> dict:
    """Return what OTP delivery channels are available for this phone."""
    from email_service import mask_email
    user = user_by_phone(db, phone)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Phone number not registered. Create an account first.",
        )
    return {
        "email_hint": mask_email(user.email) if user.email else None,
        "has_whatsapp": True,  # always — we can always send to their phone number
        "has_email": bool(user.email),
    }


def request_web_otp(db: Session, phone: str, channel: str = "auto", email: str = None) -> dict:
    """Send a 6-digit OTP via email or WhatsApp depending on channel.

    WhatsApp is always available (we have the phone number).
    Email is available when on record, or when the caller supplies one now.
    """
    if not _auth_rate_check(f"otp:{phone}"):
        raise HTTPException(status_code=429, detail="Too many OTP requests. Please wait 15 minutes.")

    from email_service import send_otp_email
    from whatsapp_client import send_whatsapp_message

    user = user_by_phone(db, phone)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Phone number not registered. Create an account first.",
        )

    # If caller supplies an email and user has none, save it now
    if email and not user.email:
        clean = email.strip().lower()
        if "@" in clean and "." in clean:
            user.email = clean
            db.commit()

    has_email = bool(user.email)
    # WhatsApp is always available — we know their phone number
    has_whatsapp = True

    # "auto" prefers both when email is available, otherwise just WhatsApp
    if channel == "auto":
        channel = "both" if has_email else "whatsapp"

    if channel == "email" and not has_email:
        raise HTTPException(status_code=400, detail="No email address on this account. Please enter your email below.")

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
            ok = send_whatsapp_message(
                phone,
                f"Your CreditVoice PIN reset code: *{otp}*\n\nValid for 10 minutes. Do not share this with anyone.",
            )
            if ok:
                sent_channels.append("whatsapp")
        except Exception:
            pass

    if not sent_channels:
        # Clean up the undelivered OTP so it doesn't linger
        db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action == _OTP_ACTION,
        ).delete()
        db.commit()
        if channel == "email":
            raise HTTPException(
                status_code=500,
                detail="Could not send the code by email. Please check that your email address is correct, or switch to WhatsApp and try again.",
            )
        if has_email:
            raise HTTPException(
                status_code=500,
                detail="Could not send via WhatsApp. Please select Email delivery and try again.",
            )
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not send the code via WhatsApp. This usually happens when you haven't "
                "messaged TiTi on WhatsApp recently (WhatsApp only allows us to message you "
                "if you messaged us in the last 24 hours). Please send any message to TiTi "
                "first, then try again — or add your email address to your account."
            ),
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

    user = user_by_phone(db, phone)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    from audit import audit
    user.recovery_pin_hash = _hash_pin(new_pin.strip())
    user.pin_attempts = 0
    user.pin_locked_until = None
    # Resetting the PIN ends every other session — the point of a reset after a
    # lost/stolen phone. The fresh token below carries the new epoch.
    user.token_version = (user.token_version or 0) + 1
    db.delete(pending)
    audit(db, action="PIN_RESET", actor_id=user.id, actor_phone=user.phone)
    db.commit()
    return _build_auth_response(user, db=db)


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
        raise HTTPException(status_code=400, detail="Business name is required.")
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

    return _build_auth_response(user, db=db)


def _build_auth_response(user: User, db=None) -> dict:
    from business_templates import menu_group_for_user
    from admin import is_app_admin
    user_is_admin = bool(db is not None and is_app_admin(user.phone, db))
    ttl = _ADMIN_TTL if user_is_admin else _TTL
    token = create_web_token(user.id, user.phone, ttl=ttl, token_version=user.token_version or 0)
    session_expires_at = datetime.fromtimestamp(
        int(time.time()) + ttl, tz=timezone.utc
    ).isoformat()

    # Resolve the plan from the business owner (follows parent_id) so staff /
    # sub-accounts inherit the owner's plan, and expiry is applied — the same
    # source of truth the WhatsApp side and /subscription/status use.
    plan = user.subscription_plan
    expires_at = user.subscription_expires_at
    if db is not None:
        from subscriptions import get_business_subscription
        sub = get_business_subscription(db, user)
        plan = sub["plan"]
        expires_at = sub["expires_at"]

    # Per-business-type example prompts (mirror WhatsApp's industry examples)
    try:
        from business_templates import template_examples_for_user
        examples = [str(e) for e in (template_examples_for_user(user) or [])][:4]
    except Exception:
        examples = []

    return {
        "_token": token,  # used internally to set the cookie — not returned to client
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "email": user.email,
            "role": user.role,
            # Admin-ness lives in APP_ADMIN_PHONES / AppAdminRole, not user.role —
            # the frontend gates the Admin menu on this flag.
            "is_app_admin": user_is_admin,
            "plan": plan,
            "business_category": user.business_category,
            "business_type": user.business_type,
            "business_type_label": user.business_type_label,
            "menu_group": menu_group_for_user(user),
            "whatsapp_linked": bool(user.whatsapp_linked),
            "newsletter_consent": bool(user.newsletter_consent),
            "parent_id": user.parent_id,
            "full_access": user.parent_id is None or bool(user.can_view_all_transactions),
            "address": user.address,
            "subscription_plan": plan,
            "subscription_expires_at": expires_at.isoformat() if expires_at else None,
            "examples": examples,
            "session_expires_at": session_expires_at,
        },
    }
