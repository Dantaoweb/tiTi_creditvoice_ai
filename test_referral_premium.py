"""
Referrals must count PREMIUM the same as GO/PRO. Regression: after Premium was
added (and existing Pro users grandfathered to Premium), the referral logic
hard-coded ["GO","PRO"], so Premium referrers/invitees stopped counting — active
referrals and bonuses collapsed to zero in both the user and admin views.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("APP_ADMIN_PHONES", "2348230000001")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-referral-prem-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Referral

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _mk(phone, plan=None, code=None):
    client.post("/app/api/auth/register", json={"name": "U", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        if plan:
            u.subscription_plan = plan
            u.subscription_status = "ACTIVE"
        if code:
            u.referral_code = code
        db.commit()
    finally:
        db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_premium_referrer_gets_unlimited_and_credits_for_premium_invitee():
    ref_phone = "2348230000001"
    cook = _mk(ref_phone, plan="PREMIUM", code="PREMTEST")

    # A referred user who upgraded all the way to Premium (active).
    inv_phone = "2348230000002"
    _mk(inv_phone, plan="PREMIUM")
    db = SessionLocal()
    try:
        db.add(Referral(referral_code="PREMTEST", referrer_phone=ref_phone,
                        referee_phone=inv_phone, referee_name="Invitee"))
        db.commit()
    finally:
        db.close()

    d = client.get("/app/api/referral", cookies=cook).json()
    assert d["invite_limit"] is None            # paid plans invite unlimited
    assert d["active_go"] == 1                   # Premium invitee counts as active
    assert d["credit_this_month"] > 0            # Premium referrer earns credit
    assert d["referrals"][0]["active"] is True


def test_admin_referrals_shows_bonus_for_premium():
    d = client.get("/app/api/admin/referrals",
                   cookies=client.post("/app/api/auth/login",
                                       json={"phone": "2348230000001", "pin": "5678"}).cookies).json()
    row = next(r for r in d["referrers"] if r["referral_code"] == "PREMTEST")
    assert row["referrer_plan"] == "PREMIUM"
    assert row["active_go"] == 1
    assert row["bonus"] > 0


def test_is_paid_plan_helper():
    from plans import is_paid_plan
    assert is_paid_plan("PREMIUM") and is_paid_plan("PRO") and is_paid_plan("GO")
    assert not is_paid_plan("BASIC") and not is_paid_plan(None) and not is_paid_plan("junk")
