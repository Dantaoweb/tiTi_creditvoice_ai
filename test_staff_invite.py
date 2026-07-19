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


def test_accept_works_when_phone_format_differs():
    # Owner invites using local format; staff accepts using international format.
    owner_cookies = _pro_owner("2348055550007")
    inv = client.post("/app/api/staff/invite", cookies=owner_cookies,
                      json={"name": "Bisi", "phone": "08055550008"})
    assert inv.status_code == 200, inv.text
    code = inv.json()["invite_code"]

    # Accept with international format
    acc = client.post("/app/api/staff/accept", json={"phone": "2348055550008", "code": code})
    assert acc.status_code == 200, acc.text

    # And the reverse: owner invites international, staff accepts local.
    inv2 = client.post("/app/api/staff/invite", cookies=owner_cookies,
                       json={"name": "Kola", "phone": "2348055550009"})
    acc2 = client.post("/app/api/staff/accept",
                       json={"phone": "08055550009", "code": inv2.json()["invite_code"]})
    assert acc2.status_code == 200, acc2.text


def test_accept_rejects_wrong_code():
    owner_cookies = _pro_owner("2348055550003")
    staff_phone = "2348055550004"
    client.post("/app/api/staff/invite", cookies=owner_cookies,
                json={"name": "Tunde", "phone": staff_phone})
    bad = client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": "WRONGCODE"})
    assert bad.status_code == 400


def test_owner_can_grant_and_revoke_full_access():
    owner_cookies = _pro_owner("2348055550005")
    staff_phone = "2348055550006"
    code = client.post("/app/api/staff/invite", cookies=owner_cookies,
                       json={"name": "Ada", "phone": staff_phone}).json()["invite_code"]
    client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": code})

    member = next(m for m in client.get("/app/api/staff/members", cookies=owner_cookies).json()["members"]
                  if m["phone"] == staff_phone)
    assert member["full_access"] is False

    grant = client.post(f"/app/api/staff/{member['id']}/access",
                        cookies=owner_cookies, json={"full_access": True})
    assert grant.status_code == 200 and grant.json()["full_access"] is True

    member = next(m for m in client.get("/app/api/staff/members", cookies=owner_cookies).json()["members"]
                  if m["phone"] == staff_phone)
    assert member["full_access"] is True

    revoke = client.post(f"/app/api/staff/{member['id']}/access",
                         cookies=owner_cookies, json={"full_access": False})
    assert revoke.json()["full_access"] is False
