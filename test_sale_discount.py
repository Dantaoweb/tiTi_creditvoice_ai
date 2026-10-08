"""
A discount off the whole sale, at the web till and on WhatsApp.

The lines keep their own prices; the sale is recorded at lines − discount,
and every receipt prints Subtotal and Discount so the numbers add up.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-sale-discount-00000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, Transaction

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: None)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348073{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cook


def _customer(phone):
    db = SessionLocal()
    try:
        c = Customer(owner_phone=phone, name="Ada", balance=0)
        db.add(c); db.commit()
        return c.id
    finally:
        db.close()


def _sell(phone, cook, discount, paid, customer_id=None, lines=((2, 1500), (1, 2000))):
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": customer_id,
        "items": [{"name": f"item{i}", "qty": q, "unit_price": p} for i, (q, p) in enumerate(lines)],
        "payment_amount": paid, "discount": discount,
    })
    return r


def test_a_cash_sale_with_a_discount_is_recorded_at_the_lower_total():
    phone, cook = _shop()
    r = _sell(phone, cook, discount=500, paid=4500)           # lines 5,000 − 500
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 4500 and r.json()["discount"] == 500

    receipt = client.get(f"/app/api/pos/receipt/{r.json()['receipt_id']}", cookies=cook).json()
    assert receipt["total"] == 4500
    assert receipt["subtotal"] == 5000 and receipt["discount"] == 500


def test_paying_the_discounted_total_leaves_no_debt():
    phone, cook = _shop()
    cid = _customer(phone)
    r = _sell(phone, cook, discount=1000, paid=4000, customer_id=cid)
    assert r.status_code == 200, r.text
    assert r.json()["balance_owed"] == 0
    db = SessionLocal()
    try:
        assert (db.query(Customer).filter(Customer.id == cid).first().balance or 0) == 0
    finally:
        db.close()


def test_part_payment_after_a_discount_owes_only_the_rest():
    phone, cook = _shop()
    cid = _customer(phone)
    r = _sell(phone, cook, discount=1000, paid=1000, customer_id=cid)
    assert r.json()["balance_owed"] == 3000                   # 5,000 − 1,000 discount − 1,000 paid


def test_a_discount_larger_than_the_sale_is_refused():
    phone, cook = _shop()
    assert _sell(phone, cook, discount=6000, paid=0).status_code == 400
    assert _sell(phone, cook, discount=-100, paid=5000).status_code == 400


def test_the_whatsapp_receipt_text_adds_up():
    from web_pos import format_receipt_text
    phone, cook = _shop()
    rid = _sell(phone, cook, discount=500, paid=4500).json()["receipt_id"]
    receipt = client.get(f"/app/api/pos/receipt/{rid}", cookies=cook).json()
    text = format_receipt_text(receipt)
    assert "Subtotal: N5,000" in text and "Discount: -N500" in text and "N4,500" in text


def test_no_discount_lines_when_there_is_no_discount():
    from web_pos import format_receipt_text
    phone, cook = _shop()
    rid = _sell(phone, cook, discount=0, paid=5000).json()["receipt_id"]
    receipt = client.get(f"/app/api/pos/receipt/{rid}", cookies=cook).json()
    assert receipt["discount"] == 0
    assert "Discount" not in format_receipt_text(receipt)
    db = SessionLocal()
    try:
        assert db.query(Transaction).filter(Transaction.id == rid).first().discount_amount is None
    finally:
        db.close()


def test_the_whatsapp_cart_receipt_shows_the_whole_sale_discount():
    from select_product_commands import build_customer_receipt
    cart = [{"product": "rice", "quantity": 2, "unit": "bag", "unit_price": 1500, "total": 3000}]
    text = build_customer_receipt("Ade Stores", "Ada", cart, 2500, 2500, 0, None, 1,
                                  overall_discount=500)
    assert "Subtotal: N3,000" in text and "Discount: -N500" in text
