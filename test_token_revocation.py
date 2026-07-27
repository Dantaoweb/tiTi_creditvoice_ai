"""
Token revocation via per-user session epoch (token_version):
- log out of all devices kills the current token
- bumping token_version invalidates existing tokens; a fresh login works
- an owner can sign a staff out of all their devices
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-token-revocation-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _tok(phone, pin="5678"):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies.get("cv_session")


def _owner():
    n = next(_seq)
    phone = f"234802222{n:04d}"
    client.post("/app/api/auth/register", json={"name": "O", "phone": phone, "pin": "5678"})
    return phone, _tok(phone)


def _me(tok):
    return client.get("/app/api/auth/me", cookies={"cv_session": tok}).status_code


def test_logout_all_kills_current_session():
    phone, tok = _owner()
    assert _me(tok) == 200
    assert client.post("/app/api/auth/logout-all", cookies={"cv_session": tok}).status_code == 200
    assert _me(tok) == 401                      # old token now dead


def test_bumping_version_revokes_then_relogin_works():
    phone, tok = _owner()
    assert _me(tok) == 200
    db = SessionLocal(); u = db.query(User).filter(User.phone == phone).first()
    u.token_version = (u.token_version or 0) + 1; db.commit(); db.close()
    assert _me(tok) == 401                      # stale epoch rejected
    assert _me(_tok(phone)) == 200              # a fresh login is valid again


def test_owner_revokes_staff_sessions():
    owner_phone, otok = _owner()
    n = next(_seq)
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
    staff_phone = f"234809999{n:04d}"
    staff = User(phone=staff_phone, name="S", role="delegate", parent_id=owner.id,
                 recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE")
    db.add(staff); db.commit(); staff_id = staff.id; db.close()

    stok = _tok(staff_phone, "1234")
    assert _me(stok) == 200
    r = client.post(f"/app/api/staff/{staff_id}/revoke-sessions", cookies={"cv_session": otok})
    assert r.status_code == 200, r.text
    assert _me(stok) == 401                     # staff signed out everywhere


def test_staff_cannot_revoke_via_endpoint():
    # a non-owner hitting the owner endpoint is rejected
    owner_phone, _o = _owner()
    n = next(_seq)
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    owner_id = owner.id
    sp = f"234808888{n:04d}"
    staff = User(phone=sp, name="S2", role="delegate", parent_id=owner_id,
                 recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE")
    db.add(staff); db.commit(); db.close()
    stok = _tok(sp, "1234")
    r = client.post(f"/app/api/staff/{owner_id}/revoke-sessions", cookies={"cv_session": stok})
    assert r.status_code == 403
