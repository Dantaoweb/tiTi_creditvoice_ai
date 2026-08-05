"""
Referrals must count PREMIUM the same as GO/PRO. Regression: after Premium was
added (and existing Pro users grandfathered to Premium), the referral logic
hard-coded ["GO","PRO"], so Premium referrers/invitees stopped counting — active
referrals and bonuses collapsed to zero in both the user and admin views.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-referral-prem-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from admin import ROLE_APP_ADMIN
from database import SessionLocal
from models import User, Referral, AppAdminRole
from parser import normalize_phone

client = TestClient(app, raise_server_exceptions=True)

REF_PHONE = "2348230000001"
INV_PHONE = "2348230000002"


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


@pytest.fixture(scope="module", autouse=True)
def _seed():
    """Referrer (Premium, admin via DB role) with one active-Premium invitee.

    Admin is granted through app_admin_roles rather than the process-global
    APP_ADMIN_PHONES env, so this stays correct when the whole suite runs in one
    process (CI) and another module has set that env to a different phone."""
    for ph in (REF_PHONE, INV_PHONE):
        client.post("/app/api/auth/register", json={"name": "U", "phone": ph, "pin": "5678"})
    db = SessionLocal()
    try:
        ref = db.query(User).filter(User.phone == REF_PHONE).first()
        ref.subscription_plan = "PREMIUM"; ref.subscription_status = "ACTIVE"
        ref.referral_code = "PREMTEST"
        inv = db.query(User).filter(User.phone == INV_PHONE).first()
        inv.subscription_plan = "PREMIUM"; inv.subscription_status = "ACTIVE"
        db.add(AppAdminRole(phone=normalize_phone(REF_PHONE), role=ROLE_APP_ADMIN, is_active=True))
        db.add(Referral(referral_code="PREMTEST", referrer_phone=REF_PHONE,
                        referee_phone=INV_PHONE, referee_name="Invitee"))
        db.commit()
    finally:
        db.close()


def _login(phone):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_premium_referrer_gets_unlimited_and_credits_for_premium_invitee():
    d = client.get("/app/api/referral", cookies=_login(REF_PHONE)).json()
    assert d["invite_limit"] is None            # paid plans invite unlimited
    assert d["active_go"] == 1                   # Premium invitee counts as active
    assert d["credit_this_month"] > 0            # Premium referrer earns credit
    assert d["referrals"][0]["active"] is True


def test_admin_referrals_shows_bonus_for_premium():
    d = client.get("/app/api/admin/referrals", cookies=_login(REF_PHONE)).json()
    row = next(r for r in d["referrers"] if r["referral_code"] == "PREMTEST")
    assert row["referrer_plan"] == "PREMIUM"
    assert row["active_go"] == 1
    assert row["bonus"] > 0


def test_is_paid_plan_helper():
    from plans import is_paid_plan
    assert is_paid_plan("PREMIUM") and is_paid_plan("PRO") and is_paid_plan("GO")
    assert not is_paid_plan("BASIC") and not is_paid_plan(None) and not is_paid_plan("junk")
