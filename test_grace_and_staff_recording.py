"""
Subscription grace period (3 days past expiry the paid plan still works) and the
Basic-plan rule that staff cannot record sales (owner-only), which kicks in when
a paid plan lapses.
"""
import os
import uuid
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-grace-staff-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Transaction
from subscriptions import (
    _utcnow, get_business_subscription, app_user_effective_plan,
    staff_recording_allowed, SUBSCRIPTION_GRACE_DAYS,
)

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(6000, 7000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(plan="PREMIUM", expires_in_days=30):
    n = next(_seq)
    phone = f"234812{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.subscription_plan = plan
        u.subscription_status = "ACTIVE"
        u.subscription_expires_at = _utcnow() + timedelta(days=expires_in_days)
        db.commit()
        uid = u.id
    finally:
        db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, uid, cookies


def _add_staff(owner_phone, owner_id):
    n = next(_seq)
    sphone = f"234813{n:06d}"
    db = SessionLocal()
    try:
        db.add(User(phone=sphone, name="Staff", role="delegate", parent_id=owner_id,
                    recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE"))
        db.commit()
    finally:
        db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": sphone, "pin": "1234"}).cookies
    return sphone, cookies


# ── Grace period ──────────────────────────────────────────────────────────────

def test_paid_plan_survives_within_grace_then_drops():
    phone, uid, _ = _owner(plan="PREMIUM", expires_in_days=30)
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.id == uid).first()

        # 1 day past expiry → still within grace → plan stays PREMIUM.
        owner.subscription_expires_at = _utcnow() - timedelta(days=1)
        db.commit()
        sub = get_business_subscription(db, owner)
        assert sub["plan"] == "PREMIUM" and sub["status"] == "GRACE"
        assert app_user_effective_plan(owner) == "PREMIUM"

        # Past the grace window → drops to Basic.
        owner.subscription_expires_at = _utcnow() - timedelta(days=SUBSCRIPTION_GRACE_DAYS + 1)
        db.commit()
        sub = get_business_subscription(db, owner)
        assert sub["plan"] == "BASIC" and sub["status"] == "EXPIRED"
    finally:
        db.close()


# ── Staff recording allowed only on paid plans ────────────────────────────────

def test_staff_recording_allowed_helper():
    phone, uid, _ = _owner(plan="PREMIUM")
    sphone, _sc = _add_staff(phone, uid)
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.id == uid).first()
        staff = db.query(User).filter(User.phone == sphone).first()
        assert staff_recording_allowed(db, owner) is True          # owner always
        assert staff_recording_allowed(db, staff) is True          # staff on Premium
        owner.subscription_plan = "BASIC"; db.commit()
        assert staff_recording_allowed(db, staff) is False         # staff on Basic
        assert staff_recording_allowed(db, owner) is True          # owner still can
    finally:
        db.close()


def _seed_debtor(owner_phone):
    db = SessionLocal()
    try:
        c = Customer(owner_phone=owner_phone, name=f"deb-{uuid.uuid4().hex[:6]}")
        db.add(c); db.commit(); db.refresh(c)
        db.add(Transaction(customer_id=c.id, type="BUY", amount=5000,
                           message_id=f"m-{uuid.uuid4()}"))
        db.commit()
        return c.id
    finally:
        db.close()


def test_staff_blocked_from_recording_payment_on_basic():
    phone, uid, owner_ck = _owner(plan="PREMIUM")
    sphone, staff_ck = _add_staff(phone, uid)
    cid = _seed_debtor(phone)

    # On Premium the staff can record a payment.
    r = client.post(f"/app/api/customers/{cid}/pay", cookies=staff_ck, json={"amount": 1000})
    assert r.status_code == 200, r.text

    # Drop the business to Basic → staff is now blocked.
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == uid).update({"subscription_plan": "BASIC"})
        db.commit()
    finally:
        db.close()

    r = client.post(f"/app/api/customers/{cid}/pay", cookies=staff_ck, json={"amount": 1000})
    assert r.status_code == 403
    assert "Basic" in r.json()["detail"] or "Pro" in r.json()["detail"]

    # The owner can still record on Basic.
    r = client.post(f"/app/api/customers/{cid}/pay", cookies=owner_ck, json={"amount": 500})
    assert r.status_code == 200, r.text
