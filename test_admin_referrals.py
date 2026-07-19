"""
#10: admin can see referrers and each one's earned bonus.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-admin-referrals-000000000000")
ADMIN_PHONE = "2348099991001"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Referral, ReferralSettings

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    # Set here (not just at import) so a sibling admin test module that also sets
    # APP_ADMIN_PHONES can't clobber ours — app_admin_phones() reads env live.
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _login(phone):
    client.post("/app/api/auth/register", json={"name": "U", "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_admin_referrals_lists_referrers_and_bonus():
    admin_cookies = _login(ADMIN_PHONE)

    db = SessionLocal()
    db.add(ReferralSettings(cashback_amount=500))
    # A GO referrer with two invitees, one of whom is active GO
    referrer = User(name="Ada", phone="2348099991010", role="owner",
                    referral_code="ADA1", subscription_plan="GO", subscription_status="ACTIVE")
    db.add(referrer)
    db.add(User(name="Inv1", phone="2348099991011", role="owner",
                subscription_plan="GO", subscription_status="ACTIVE"))
    db.add(User(name="Inv2", phone="2348099991012", role="owner",
                subscription_plan="BASIC", subscription_status="ACTIVE"))
    db.add(Referral(referral_code="ADA1", referrer_phone="2348099991010", referee_phone="2348099991011"))
    db.add(Referral(referral_code="ADA1", referrer_phone="2348099991010", referee_phone="2348099991012"))
    db.commit(); db.close()

    r = client.get("/app/api/admin/referrals", cookies=admin_cookies)
    assert r.status_code == 200, r.text
    data = r.json()
    row = next(x for x in data["referrers"] if x["referral_code"] == "ADA1")
    assert row["total_invited"] == 2
    assert row["active_go"] == 1
    assert row["bonus"] == 500          # 1 active GO x 500, referrer on GO
    assert data["total_bonus"] >= 500


def test_admin_referrals_forbidden_for_non_admin():
    cookies = _login("2348099991002")
    assert client.get("/app/api/admin/referrals", cookies=cookies).status_code == 403
