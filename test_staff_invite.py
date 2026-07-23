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


def test_expired_invite_keeps_pending_and_resend_works():
    from datetime import datetime, timezone, timedelta
    owner_cookies = _pro_owner("2348055550010")
    staff_phone = "2348055550011"
    orig = client.post("/app/api/staff/invite", cookies=owner_cookies,
                       json={"name": "Femi", "phone": staff_phone}).json()["invite_code"]

    # Expire the invite
    db = SessionLocal()
    u = db.query(User).filter(User.phone == staff_phone).first()
    u.invite_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    db.commit(); mid = u.id; db.close()

    # Accepting the expired code fails...
    assert client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": orig}).status_code == 410

    # ...but the staff is STILL pending in the roster (not de-provisioned)
    members = client.get("/app/api/staff/members", cookies=owner_cookies).json()["members"]
    assert any(m["phone"] == staff_phone and m["pending"] for m in members)

    # Owner resends a fresh code, staff accepts with it
    res = client.post(f"/app/api/staff/{mid}/resend-invite", cookies=owner_cookies)
    assert res.status_code == 200
    new_code = res.json()["invite_code"]
    assert new_code and new_code != orig
    assert client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": new_code}).status_code == 200


def test_branch_aware_invite_preassigns_branch_and_admin():
    from models import Branch
    owner_cookies = _pro_owner("2348055550020")
    staff_phone = "2348055550021"

    db = SessionLocal()
    owner = db.query(User).filter(User.phone == "2348055550020").first()
    br = Branch(owner_phone=owner.phone, name="Ikeja", is_default=True)
    db.add(br); db.commit(); br_id = br.id; db.close()

    inv = client.post("/app/api/staff/invite", cookies=owner_cookies,
                      json={"name": "Uche", "phone": staff_phone,
                            "branch_id": br_id, "as_branch_admin": True})
    assert inv.status_code == 200, inv.text
    code = inv.json()["invite_code"]

    # Pre-assigned before they even accept
    db = SessionLocal()
    u = db.query(User).filter(User.phone == staff_phone).first()
    assert u.branch_id == br_id and u.can_view_all_transactions is True
    db.close()

    assert client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": code}).status_code == 200

    members = {m["phone"]: m for m in client.get("/app/api/staff/members", cookies=owner_cookies).json()["members"]}
    assert members[staff_phone]["branch_id"] == br_id
    assert members[staff_phone]["full_access"] is True


def test_invite_rejects_branch_from_another_owner():
    from models import Branch
    a_cookies = _pro_owner("2348055550022")
    _b_cookies = _pro_owner("2348055550023")
    db = SessionLocal()
    b_owner = db.query(User).filter(User.phone == "2348055550023").first()
    b_branch = Branch(owner_phone=b_owner.phone, name="NotYours", is_default=True)
    db.add(b_branch); db.commit(); b_branch_id = b_branch.id; db.close()

    # Owner A cannot invite into owner B's branch
    r = client.post("/app/api/staff/invite", cookies=a_cookies,
                    json={"name": "X", "phone": "2348055550024", "branch_id": b_branch_id})
    assert r.status_code == 404


def test_first_time_staff_sets_pin_at_accept_and_can_log_in():
    """A brand-new staff must not need an OTP: WhatsApp's 24h window is closed
    for someone who never messaged tiTi, and the invite code is consumed by
    accept — so without this they could never set a PIN."""
    owner_cookies = _pro_owner("2348055550030")
    staff_phone = "2348055550031"
    code = client.post("/app/api/staff/invite", cookies=owner_cookies,
                       json={"name": "Ngozi", "phone": staff_phone}).json()["invite_code"]

    acc = client.post("/app/api/staff/accept",
                      json={"phone": staff_phone, "code": code, "new_pin": "4321"})
    assert acc.status_code == 200, acc.text
    body = acc.json()
    assert body["signed_in"] is True and body["has_pin"] is True

    # They can now sign in with their OWN phone + PIN (never the owner's)
    login = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "4321"})
    assert login.status_code == 200, login.text


def test_accept_rejects_short_pin():
    owner_cookies = _pro_owner("2348055550032")
    staff_phone = "2348055550033"
    code = client.post("/app/api/staff/invite", cookies=owner_cookies,
                       json={"name": "Tobi", "phone": staff_phone}).json()["invite_code"]
    r = client.post("/app/api/staff/accept",
                    json={"phone": staff_phone, "code": code, "new_pin": "12"})
    assert r.status_code == 400


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
