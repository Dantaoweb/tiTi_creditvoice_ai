"""
#11: a transaction can be voided from the web and drops out of balances.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-web-void-tests-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Transaction

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner_with_sale(phone, amount=5000):
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == phone).first()
    cust = Customer(name="Ada", owner_phone=phone, balance=0)
    db.add(cust); db.commit()
    tx = Transaction(customer_id=cust.id, type="BUY", amount=amount,
                     message_id=f"buy-{uuid.uuid4()}", recorded_by_id=owner.id)
    db.add(tx); db.commit()
    tx_id, cust_id = tx.id, cust.id
    db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return cookies, tx_id, cust_id


def _balance(cust_id):
    db = SessionLocal()
    c = db.query(Customer).filter(Customer.id == cust_id).first()
    bal = c.balance
    db.close()
    return bal


def test_void_removes_from_balance():
    cookies, tx_id, cust_id = _owner_with_sale("2348077770001", 5000)
    assert _balance(cust_id) == 5000

    r = client.post(f"/app/api/transactions/{tx_id}/void", cookies=cookies,
                    json={"reason": "wrong entry"})
    assert r.status_code == 200, r.text
    assert r.json()["is_voided"] is True

    # Voided sale no longer counts toward the customer's balance
    assert _balance(cust_id) == 0

    # And it's marked voided in the transactions list
    rows = client.get("/app/api/transactions", cookies=cookies).json()["transactions"]
    row = next(x for x in rows if x["id"] == tx_id)
    assert row["is_voided"] is True and row["void_reason"] == "wrong entry"


def test_void_already_voided_is_404():
    cookies, tx_id, _ = _owner_with_sale("2348077770002")
    assert client.post(f"/app/api/transactions/{tx_id}/void", cookies=cookies, json={"reason": "x"}).status_code == 200
    again = client.post(f"/app/api/transactions/{tx_id}/void", cookies=cookies, json={"reason": "y"})
    assert again.status_code == 404
