"""
Security: a POS sale must not reference another business's customer or branch
(cross-tenant IDOR), and a branch staff's sale is forced into their own branch.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pos-security-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Branch, Transaction

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(name):
    n = next(_seq)
    phone = f"234804444{n:04d}"
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PRO"; u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_cannot_pos_sale_to_another_business_customer():
    a_phone, a = _owner("A")
    b_phone, _b = _owner("B")
    db = SessionLocal()
    b_owner = db.query(User).filter(User.phone == b_phone).first()
    victim = Customer(name="VictimCust", owner_phone=b_phone)
    db.add(victim); db.commit(); victim_id = victim.id; db.close()

    r = client.post("/app/api/pos/save", cookies=a, json={
        "owner_phone": a_phone, "customer_id": victim_id,
        "items": [{"name": "x", "qty": 1, "unit_price": 100}], "payment_amount": 0,
    })
    assert r.status_code != 200          # rejected

    # No transaction was attached to business B's customer
    db = SessionLocal()
    assert db.query(Transaction).filter(Transaction.customer_id == victim_id).count() == 0
    db.close()


def test_owner_supplied_foreign_branch_is_ignored():
    a_phone, a = _owner("A")
    b_phone, _b = _owner("B")
    db = SessionLocal()
    foreign = Branch(owner_phone=b_phone, name="B-Branch", is_default=True)
    db.add(foreign); db.commit(); foreign_id = foreign.id; db.close()

    r = client.post("/app/api/pos/save", cookies=a, json={
        "owner_phone": a_phone, "branch_id": foreign_id,
        "items": [{"name": "x", "qty": 1, "unit_price": 100}], "payment_amount": 100,
    })
    assert r.status_code == 200, r.text
    tx_id = r.json()["receipt_id"]
    db = SessionLocal()
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    assert tx.branch_id != foreign_id     # foreign branch not applied
    db.close()
