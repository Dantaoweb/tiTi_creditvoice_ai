"""
Verified-supplier application is a Pro-and-above feature. Regression: the gate
hard-coded ("PRO", "ENTERPRISE"), so PREMIUM owners (the tier Pro users were
grandfathered into) were wrongly told to upgrade to PRO and could not apply.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-supplier-apply-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(6000, 7000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(plan):
    n = next(_seq)
    phone = f"234829{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Sup", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.subscription_plan = plan
        u.subscription_status = "ACTIVE"
        db.commit()
    finally:
        db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


_APPLY = {"supplier_type": "wholesaler", "products": [{"product_name": "rice"}]}


def test_premium_can_apply():
    cook = _owner("PREMIUM")
    r = client.post("/app/api/verified-suppliers/apply", cookies=cook, json=_APPLY)
    assert r.status_code == 200, r.text


def test_pro_can_apply():
    cook = _owner("PRO")
    r = client.post("/app/api/verified-suppliers/apply", cookies=cook, json=_APPLY)
    assert r.status_code == 200, r.text


def test_basic_is_blocked_with_upgrade_message():
    cook = _owner("BASIC")
    r = client.post("/app/api/verified-suppliers/apply", cookies=cook, json=_APPLY)
    assert r.status_code == 403
    assert "Pro" in r.json()["detail"]
