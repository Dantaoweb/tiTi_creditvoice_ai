"""
Yearly billing: yearly price = 10x monthly (2 months free), yearly activation
runs 365 days, and the web request/status carry the period.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-yearly-sub-0000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(4000, 5000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234811{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def test_yearly_pricing_values():
    from messages import get_plan_price
    assert get_plan_price("GO", "YEARLY") == 30000
    assert get_plan_price("PRO", "YEARLY") == 70000
    assert get_plan_price("PREMIUM", "YEARLY") == 100000


def test_web_request_yearly_amount_and_period():
    _p, cook = _owner()
    r = client.post("/app/api/subscription/request", cookies=cook,
                    json={"plan": "PRO", "period": "YEARLY"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 70000
    assert body["period"] == "YEARLY"


def test_web_request_defaults_to_monthly():
    _p, cook = _owner()
    r = client.post("/app/api/subscription/request", cookies=cook, json={"plan": "PRO"})
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 7000
    assert r.json()["period"] == "MONTHLY"


def test_status_returns_yearly_prices():
    _p, cook = _owner()
    d = client.get("/app/api/subscription/status", cookies=cook).json()
    assert d["prices_yearly"]["PRO"] == 70000
    assert d["prices"]["PRO"] == 7000


def test_yearly_activation_is_365_days():
    from subscriptions import create_subscription_payment_request, approve_subscription_payment
    phone, _cook = _owner()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        payment = create_subscription_payment_request(db, user, "PREMIUM", "YEARLY")
        assert payment.billing_period == "YEARLY"
        assert payment.amount == 100000
        db.commit()
        owner = approve_subscription_payment(db, payment, admin_user=user)
        db.commit()
        from subscriptions import _utcnow
        days = (owner.subscription_expires_at - _utcnow()).days
        assert 360 <= days <= 366, days
        assert owner.subscription_plan == "PREMIUM"
    finally:
        db.close()


def test_monthly_activation_is_30_days():
    from subscriptions import create_subscription_payment_request, approve_subscription_payment, _utcnow
    phone, _cook = _owner()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        payment = create_subscription_payment_request(db, user, "GO", "MONTHLY")
        db.commit()
        owner = approve_subscription_payment(db, payment, admin_user=user)
        db.commit()
        days = (owner.subscription_expires_at - _utcnow()).days
        assert 28 <= days <= 31, days
    finally:
        db.close()
