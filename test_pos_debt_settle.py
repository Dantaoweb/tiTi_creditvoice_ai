"""
POS "Settle previous debt" line: a customer can clear their prior balance in the
same checkout by paying extra. The surplus is recorded as a PAY (never more than
owed), so their balance drops exactly like a manual payment.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pos-debt-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(2000, 2999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234877755{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PRO"; u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _customer(phone, name):
    db = SessionLocal()
    try:
        c = Customer(name=name, owner_phone=phone)
        db.add(c); db.commit()
        return c.id
    finally:
        db.close()


def _balance(cid):
    db = SessionLocal()
    try:
        return db.query(Customer).filter(Customer.id == cid).first().balance or 0
    finally:
        db.close()


def test_pos_settles_prior_debt_at_checkout():
    phone, cook = _owner()
    cid = _customer(phone, "Mr Awe")

    # Credit sale of 1000, nothing paid → owes 1000.
    r1 = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid,
        "items": [{"name": "shoe", "qty": 1, "unit_price": 1000}],
        "payment_amount": 0,
    })
    assert r1.status_code == 200, r1.text
    assert _balance(cid) == 1000

    # Next sale of 500, customer pays 1500: 500 for goods + 1000 clears the debt.
    r2 = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid,
        "items": [{"name": "polish", "qty": 1, "unit_price": 500}],
        "payment_amount": 500, "debt_payment": 1000,
    })
    assert r2.status_code == 200, r2.text
    assert _balance(cid) == 0


def test_pos_debt_payment_never_overpays():
    phone, cook = _owner()
    cid = _customer(phone, "Small Debt")

    # Owes 200.
    client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid,
        "items": [{"name": "x", "qty": 1, "unit_price": 200}], "payment_amount": 0})
    assert _balance(cid) == 200

    # Try to settle 1000 (more than owed) → clamped to 200; balance is 0, not negative.
    client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid,
        "items": [{"name": "y", "qty": 1, "unit_price": 100}],
        "payment_amount": 100, "debt_payment": 1000})
    assert _balance(cid) == 0
