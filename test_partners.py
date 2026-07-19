"""
#4: partner/investor invite works end-to-end and stores equity/investment.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-partners-tests-0000000000")

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
    u.subscription_plan = "PRO"
    u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_partner_sees_and_accepts_invite_despite_phone_format():
    # Owner invites the partner in international format; the partner's own
    # account is registered in local format. They must still see and accept it.
    owner_cookies = _pro_owner("2348066660020")
    # Partner registers with the LOCAL format of the same number.
    client.post("/app/api/auth/register", json={"name": "Ade", "phone": "08066660021", "pin": "5678"})
    partner_cookies = client.post("/app/api/auth/login",
                                  json={"phone": "08066660021", "pin": "5678"}).cookies

    inv = client.post("/app/api/partners/invite", cookies=owner_cookies, json={
        "partner_phone": "2348066660021", "role": "investor", "investment_amount": 100000,
    })
    assert inv.status_code == 200, inv.text

    # The invite shows up in the partner's "Businesses I'm In"
    roles = client.get("/app/api/partners", cookies=partner_cookies).json()["as_partner"]
    assert len(roles) == 1 and roles[0]["status"] == "pending", roles

    # And they can accept it
    acc = client.post(f"/app/api/partners/{roles[0]['id']}/accept", cookies=partner_cookies)
    assert acc.status_code == 200 and acc.json()["status"] == "active", acc.text


def test_owner_invites_investor_with_details():
    cookies = _pro_owner("2348066660001")
    r = client.post("/app/api/partners/invite", cookies=cookies, json={
        "partner_phone": "2348066660002",
        "role": "investor",
        "equity_percent": 25.0,
        "investment_amount": 500000,
        "notes": "Seed investor",
    })
    assert r.status_code == 200, r.text

    data = client.get("/app/api/partners", cookies=cookies).json()
    partners = data["partners"]
    assert len(partners) == 1
    p = partners[0]
    assert p["partner_phone"] == "2348066660002"
    assert p["role"] == "investor"
    assert p["equity_percent"] == 25.0
    assert p["investment_amount"] == 500000
