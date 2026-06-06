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

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from models import PendingAction, User
from recovery_commands import _hash_pin, _verify_pin

_SECRET = os.getenv("WEB_SECRET_KEY", "cv-web-secret-change-in-production")
_TTL = 7 * 24 * 3600  # 7 days
_OTP_ACTION = "WEB_OTP"


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


def require_web_auth(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_web_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return payload


def web_login(db: Session, phone: str, pin: str) -> dict:
    """Validate phone + PIN and return token + user info."""
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=401, detail="Phone number not registered. Start on WhatsApp first.")

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
        db.commit()
        raise HTTPException(status_code=401, detail="Incorrect PIN.")

    user.pin_attempts = 0
    user.pin_locked_until = None
    db.commit()

    return _build_auth_response(user)


def request_web_otp(db: Session, phone: str) -> dict:
    """Send a 6-digit OTP to the user's WhatsApp for PIN set/reset."""
    from whatsapp_client import send_whatsapp_message

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Phone number not registered. Message tiTi on WhatsApp first to create your account.",
        )

    # Remove any existing OTP for this phone
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

    send_whatsapp_message(
        phone,
        f"Your CreditVoice PIN reset code is: *{otp}*\n\nValid for 10 minutes. Do not share this with anyone.",
    )
    return {"sent": True, "phone": phone}


def verify_otp_and_set_pin(db: Session, phone: str, otp: str, new_pin: str) -> dict:
    """Verify OTP code then hash and save the new PIN. Returns auth token on success."""
    if not new_pin or len(new_pin.strip()) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 digits.")

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

    if pending.product != otp.strip():
        raise HTTPException(status_code=400, detail="Incorrect code. Try again.")

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.recovery_pin_hash = _hash_pin(new_pin.strip())
    user.pin_attempts = 0
    user.pin_locked_until = None
    db.delete(pending)
    db.commit()

    # Auto-login after PIN set
    return _build_auth_response(user)


def web_register(db: Session, name: str, phone: str, pin: str,
                 business_category: str = None, business_type: str = None,
                 business_type_label: str = None) -> dict:
    """Create a new user account from the web and return an auth token."""
    if not name.strip():
        raise HTTPException(status_code=400, detail="Full name is required.")
    if not phone.strip():
        raise HTTPException(status_code=400, detail="Phone number is required.")
    if not pin.strip() or len(pin.strip()) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 digits.")

    existing = db.query(User).filter(User.phone == phone.strip()).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="This phone number is already registered. Sign in instead.",
        )

    user = User(
        name=name.strip(),
        phone=phone.strip(),
        role="owner",
        subscription_plan="BASIC",
        subscription_status="ACTIVE",
        business_category=business_category or None,
        business_type=business_type or None,
        business_type_label=business_type_label or None,
        recovery_pin_hash=_hash_pin(pin.strip()),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _build_auth_response(user)


def _build_auth_response(user: User) -> dict:
    token = create_web_token(user.id, user.phone)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "role": user.role,
            "plan": user.subscription_plan,
            "business_category": user.business_category,
        },
    }
