"""
Web admin approval of bank-transfer subscription payments: list pending, approve
(activates the plan), reject (marks rejected). Admin is granted via a DB role so
the whole suite can share one process on CI.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pay-approval-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from admin import ROLE_APP_ADMIN
from database import SessionLocal
from models import User, SubscriptionPayment, AppAdminRole
from parser import normalize_phone
from subscriptions import create_subscription_payment_request

client = TestClient(app, raise_server_exceptions=True)

ADMIN = "2348260000001"
BIZ = "2348260000002"
BIZ2 = "2348260000003"


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


@pytest.fixture(scope="module", autouse=True)
def _seed():
    for ph in (ADMIN, BIZ, BIZ2):
        client.post("/app/api/auth/register", json={"name": "U", "phone": ph, "pin": "5678"})
    db = SessionLocal()
    try:
        db.add(AppAdminRole(phone=normalize_phone(ADMIN), role=ROLE_APP_ADMIN, is_active=True))
        db.commit()
    finally:
        db.close()


def _login(phone):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _pending_payment(biz_phone, plan="PREMIUM", period="MONTHLY"):
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == biz_phone).first()
        p = create_subscription_payment_request(db, owner, plan, period)
        p.payment_method = "BANK_TRANSFER"
        db.commit()
        return p.id
    finally:
        db.close()


def test_list_approve_and_reject():
    admin = _login(ADMIN)
    pid = _pending_payment(BIZ, "PREMIUM", "YEARLY")

    # Non-admin cannot see the list.
    assert client.get("/app/api/admin/subscription-payments", cookies=_login(BIZ)).status_code == 403

    # Admin sees the pending payment.
    d = client.get("/app/api/admin/subscription-payments", cookies=admin).json()
    row = next(r for r in d["payments"] if r["id"] == pid)
    assert row["plan"] == "PREMIUM" and row["period"] == "YEARLY" and row["amount"] == 100000

    # Approve → the business is now on the plan.
    r = client.post(f"/app/api/admin/subscription-payments/{pid}/approve", cookies=admin)
    assert r.status_code == 200 and r.json()["plan"] == "PREMIUM", r.text
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == BIZ).first()
        assert owner.subscription_plan == "PREMIUM" and owner.subscription_status == "ACTIVE"
        assert owner.subscription_expires_at is not None
    finally:
        db.close()

    # Approving again is a no-op conflict (already approved).
    assert client.post(f"/app/api/admin/subscription-payments/{pid}/approve", cookies=admin).status_code == 409

    # Reject a different pending payment.
    pid2 = _pending_payment(BIZ2, "GO", "MONTHLY")
    assert client.post(f"/app/api/admin/subscription-payments/{pid2}/reject", cookies=admin).status_code == 200
    db = SessionLocal()
    try:
        p2 = db.query(SubscriptionPayment).filter(SubscriptionPayment.id == pid2).first()
        assert p2.status == "REJECTED"
        # Rejection must not activate the plan.
        owner2 = db.query(User).filter(User.phone == BIZ2).first()
        assert owner2.subscription_plan in (None, "BASIC")
    finally:
        db.close()
