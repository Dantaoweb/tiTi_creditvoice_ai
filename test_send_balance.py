"""
Sending one customer their balance — the answer to "how much do I owe?".
Before this, the only way was to draft reminders for EVERY debtor and find
that customer in the list.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-send-balance-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    phone = f"234852{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _customer(phone, cook, name="Ade", cust_phone="2348031234567"):
    cid = client.post("/app/api/customers", cookies=cook,
                      json={"owner_phone": phone, "name": name, "phone": cust_phone}).json()["id"]
    return cid


def _sell(phone, cook, cid, amount, paid=0):
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid,
        "items": [{"name": "rice", "qty": 1, "unit_price": amount}], "payment_amount": paid})
    assert r.status_code == 200, r.text


def _message(cook, cid):
    r = client.get(f"/app/api/customers/{cid}/balance-message", cookies=cook)
    assert r.status_code == 200, r.text
    return r.json()


def test_balance_message_states_the_amount_and_recent_items():
    phone, cook = _owner()
    cid = _customer(phone, cook)
    _sell(phone, cook, cid, 5000)
    _sell(phone, cook, cid, 3000, paid=1000)
    d = _message(cook, cid)

    assert d["balance"] == 7000
    msg = d["message"]
    assert "N7,000" in msg
    assert "Ade Stores" in msg          # business name
    assert "Owing since" in msg
    assert "Recent activity:" in msg
    assert "paid N1,000" in msg         # the payment shows as a payment line
    assert d["self_send_url"].startswith("https://wa.me/2348031234567?text=")


def test_message_for_a_settled_customer_and_one_in_credit():
    phone, cook = _owner()
    cid = _customer(phone, cook, "Ngozi")
    _sell(phone, cook, cid, 2000, paid=2000)
    assert "fully settled" in _message(cook, cid)["message"]

    client.post(f"/app/api/customers/{cid}/pay", cookies=cook, json={"amount": 500})
    d = _message(cook, cid)
    assert d["balance"] == -500 and "credit with us" in d["message"]


def test_send_reports_delivery_honestly_and_offers_the_self_send_link():
    phone, cook = _owner()
    cid = _customer(phone, cook, "Bola")
    _sell(phone, cook, cid, 4000)
    r = client.post(f"/app/api/customers/{cid}/send-balance", cookies=cook,
                    json={"message": "You owe N4,000"})
    assert r.status_code == 200, r.text
    body = r.json()
    # No WhatsApp credentials in tests → not delivered, and the owner gets a link.
    assert body["delivered"] is False
    assert body["self_send_url"].startswith("https://wa.me/")
    assert "You%20owe" in body["self_send_url"]


def test_customer_without_phone_cannot_be_sent_to():
    phone, cook = _owner()
    db = SessionLocal()
    c = Customer(owner_phone=phone, name="No Phone", balance=1000)
    db.add(c); db.commit(); cid = c.id; db.close()
    d = _message(cook, cid)
    assert d["customer_phone"] is None and d["self_send_url"] is None
    r = client.post(f"/app/api/customers/{cid}/send-balance", cookies=cook, json={"message": "hi"})
    assert r.status_code == 400 and "No phone" in r.json()["detail"]


def test_another_business_cannot_read_or_send_a_customers_balance():
    phone, cook = _owner()
    cid = _customer(phone, cook, "Private")
    _sell(phone, cook, cid, 9000)
    _other_phone, other = _owner()
    assert client.get(f"/app/api/customers/{cid}/balance-message", cookies=other).status_code == 404
    assert client.post(f"/app/api/customers/{cid}/send-balance", cookies=other,
                       json={"message": "x"}).status_code == 404
