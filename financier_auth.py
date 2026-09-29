"""
Logins for financier staff — a separate world from business logins.

A financier token carries its own prefix and rides its own cookie, so a
financier session can never be accepted where a business session is expected,
and a business session can never reach the portal. Same signing secret and the
same PBKDF2 PIN hashing as the main app; nothing new invented.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from fastapi import Cookie, Header, HTTPException, Response

from models import FinancePartner, FinancierUser, utcnow

_SECRET = os.getenv("WEB_SECRET_KEY", "dev-secret-change-me")
_TTL = int(os.getenv("FINANCIER_SESSION_TTL", str(12 * 3600)))   # 12h, shorter than a business session
_SECURE_COOKIE = os.getenv("ENVIRONMENT", "production") != "development"
COOKIE_NAME = "cv_financier"

# The prefix is what keeps the two token families apart.
_PREFIX = "fin1"


def _sign(payload: str) -> str:
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_token(user_id: str, partner_id: str, ttl: int = _TTL, token_version: int = 0) -> str:
    exp = int(time.time()) + ttl
    payload = f"{_PREFIX}|{user_id}|{partner_id}|{exp}|{token_version}"
    return base64.urlsafe_b64encode(f"{payload}|{_sign(payload)}".encode()).decode()


def verify_token(token: str) -> Optional[dict]:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit("|", 1)
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        prefix, user_id, partner_id, exp, ver = payload.split("|")
        if prefix != _PREFIX:          # a business token must never pass here
            return None
        if int(time.time()) > int(exp):
            return None
        return {"user_id": user_id, "partner_id": partner_id, "ver": int(ver)}
    except Exception:
        return None


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True, secure=_SECURE_COOKIE,
        samesite="lax", max_age=_TTL, path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True,
                           secure=_SECURE_COOKIE, samesite="lax")


def require_financier(
    cv_financier: Optional[str] = Cookie(default=None),
    authorization: str = Header(default=""),
) -> dict:
    """The session of a signed-in financier user. 401 otherwise."""
    token = cv_financier or authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    claims = verify_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
    return claims


def load_financier(db, session: dict):
    """(user, partner) for a session, rejecting deactivated accounts and stale
    tokens (a bumped token_version logs them out everywhere)."""
    user = db.query(FinancierUser).filter(FinancierUser.id == session["user_id"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="This account is no longer active.")
    if int(user.token_version or 0) != int(session.get("ver", 0)):
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
    partner = db.query(FinancePartner).filter(
        FinancePartner.id == user.finance_partner_id).first()
    if not partner:
        raise HTTPException(status_code=401, detail="Financier record is missing.")
    return user, partner


def generate_invite_code() -> str:
    """Short, quotable, no look-alike characters — read out over a phone call."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "FIN-" + "".join(secrets.choice(alphabet) for _ in range(6))


def invite_expiry(days: int = 7):
    from datetime import timedelta
    return utcnow() + timedelta(days=days)
