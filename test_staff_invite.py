"""
#2: staff invite → accept works end-to-end, and an invite link carries the code.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-staff-invite-tests-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _pro_owner(phone):
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PRO"       # staff management requires Pro
    u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_invite_then_accept():
    owner_cookies = _pro_owner("2348055550001")
    staff_phone = "2348055550002"

    inv = client.post("/app/api/staff/invite", cookies=owner_cookies,
                      json={"name": "Sade", "phone": staff_phone})
    assert inv.status_code == 200, inv.text
    code = inv.json()["invite_code"]
    assert code

    # Staff appears as pending on the owner's roster
    members = client.get("/app/api/staff/members", cookies=owner_cookies).json()["members"]
    assert any(m["phone"] == staff_phone and m["pending"] for m in members)

    # Staff accepts with phone + code (what the invite link pre-fills)
    acc = client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": code})
    assert acc.status_code == 200, acc.text

    # No longer pending
    members = client.get("/app/api/staff/members", cookies=owner_cookies).json()["members"]
    assert any(m["phone"] == staff_phone and not m["pending"] for m in members)


def test_accept_rejects_wrong_code():
    owner_cookies = _pro_owner("2348055550003")
    staff_phone = "2348055550004"
    client.post("/app/api/staff/invite", cookies=owner_cookies,
                json={"name": "Tunde", "phone": staff_phone})
    bad = client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": "WRONGCODE"})
    assert bad.status_code == 400
