"""
Premium plan tier + Pro caps:
  - Pro unlocks branches/partners/investors but caps each at 1.
  - Premium removes the caps (unlimited).
  - Basic/Go cannot use these features at all (feature-gated).
  - Premium price is N10,000.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-premium-caps-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(2000, 3000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(plan):
    n = next(_seq)
    phone = f"234807{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    if plan:
        db = SessionLocal()
        u = db.query(User).filter(User.phone == phone).first()
        u.subscription_plan = plan
        u.subscription_status = "ACTIVE"
        db.commit(); db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


# ── Branch caps ───────────────────────────────────────────────────────────────

def test_pro_allows_one_branch_blocks_second():
    _p, cook = _owner("PRO")
    r1 = client.post("/app/api/branches", cookies=cook, json={"name": "Main"})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/app/api/branches", cookies=cook, json={"name": "Second"})
    assert r2.status_code == 403
    assert "Premium" in r2.json()["detail"]


def test_premium_allows_multiple_branches():
    _p, cook = _owner("PREMIUM")
    for name in ("Main", "Ikeja", "Lekki"):
        r = client.post("/app/api/branches", cookies=cook, json={"name": name})
        assert r.status_code == 200, r.text


def test_basic_cannot_create_branch():
    _p, cook = _owner(None)  # defaults to BASIC
    r = client.post("/app/api/branches", cookies=cook, json={"name": "Main"})
    assert r.status_code == 403
    # Feature-gated, not a count cap.
    assert "upgrade" in r.json()["detail"].lower()


def test_go_cannot_create_branch():
    _p, cook = _owner("GO")
    r = client.post("/app/api/branches", cookies=cook, json={"name": "Main"})
    assert r.status_code == 403


# ── Partner / investor caps ───────────────────────────────────────────────────

def test_pro_allows_one_partner_and_one_investor():
    _p, cook = _owner("PRO")
    # One partner
    r1 = client.post("/app/api/partners/invite", cookies=cook,
                     json={"partner_phone": "2348090000001", "role": "partner"})
    assert r1.status_code == 200, r1.text
    # Second partner blocked
    r2 = client.post("/app/api/partners/invite", cookies=cook,
                     json={"partner_phone": "2348090000002", "role": "partner"})
    assert r2.status_code == 403 and "partner" in r2.json()["detail"].lower()
    # One investor still allowed (separate bucket)
    r3 = client.post("/app/api/partners/invite", cookies=cook,
                     json={"partner_phone": "2348090000003", "role": "investor"})
    assert r3.status_code == 200, r3.text
    # Second investor blocked
    r4 = client.post("/app/api/partners/invite", cookies=cook,
                     json={"partner_phone": "2348090000004", "role": "investor"})
    assert r4.status_code == 403 and "investor" in r4.json()["detail"].lower()


def test_premium_allows_multiple_partners():
    _p, cook = _owner("PREMIUM")
    for i in range(3):
        r = client.post("/app/api/partners/invite", cookies=cook,
                        json={"partner_phone": f"234809100000{i}", "role": "partner"})
        assert r.status_code == 200, r.text


def test_basic_cannot_invite_partner():
    _p, cook = _owner(None)
    r = client.post("/app/api/partners/invite", cookies=cook,
                    json={"partner_phone": "2348092000001", "role": "partner"})
    assert r.status_code == 403


# ── Pricing ───────────────────────────────────────────────────────────────────

def test_premium_price():
    from messages import get_plan_price
    assert get_plan_price("PREMIUM") == 10000
    assert get_plan_price("PRO") == 7000
    assert get_plan_price("GO") == 3000
