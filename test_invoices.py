"""
Stage 1 of formal invoicing (web): per-business sequential invoice numbers.

The number is system-assigned (never typed), gap-free and unique per business,
idempotent per sale, and isolated between businesses.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-invoice-tests-00000000000000")

import uuid
import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer, Transaction, User
from invoices import format_invoice_number

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register_login(phone):
    client.post("/app/api/auth/register", json={"name": "Biz", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    uid = db.query(User).filter(User.phone == phone).first().id
    db.close()
    return cookies, uid


def _credit_sale(owner_phone, recorder_id, amount=5000, name="Ada"):
    """Insert a credit BUY sale for this business; return its tx id."""
    db = SessionLocal()
    c = db.query(Customer).filter(Customer.owner_phone == owner_phone, Customer.name == name).first()
    if not c:
        c = Customer(name=name, owner_phone=owner_phone, balance=0)
        db.add(c); db.commit()
    tx = Transaction(customer_id=c.id, type="BUY", amount=amount,
                     product="Goods", message_id=f"buy-{uuid.uuid4()}", recorded_by_id=recorder_id)
    db.add(tx); db.commit()
    tid = tx.id
    db.close()
    return tid


def test_format_invoice_number():
    assert format_invoice_number(1) == "INV-0001"
    assert format_invoice_number(482) == "INV-0482"
    assert format_invoice_number(None) is None


def test_invoice_numbers_are_sequential_per_business():
    cookies, uid = _register_login("2777000001")
    t1 = _credit_sale("2777000001", uid, name="Ada")
    t2 = _credit_sale("2777000001", uid, name="Bola")

    r1 = client.post(f"/app/api/invoices/{t1}/issue", cookies=cookies)
    r2 = client.post(f"/app/api/invoices/{t2}/issue", cookies=cookies)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["invoice_number"] == 1
    assert r2.json()["invoice_number"] == 2


def test_issue_is_idempotent():
    cookies, uid = _register_login("2777000002")
    t1 = _credit_sale("2777000002", uid)
    first = client.post(f"/app/api/invoices/{t1}/issue", cookies=cookies).json()["invoice_number"]
    second = client.post(f"/app/api/invoices/{t1}/issue", cookies=cookies).json()["invoice_number"]
    assert first == 1 and second == 1        # same number, not re-incremented


def test_numbering_is_isolated_between_businesses():
    a_cookies, a_uid = _register_login("2777000003")
    b_cookies, b_uid = _register_login("2777000004")
    ta = _credit_sale("2777000003", a_uid)
    tb = _credit_sale("2777000004", b_uid)
    # Each business starts its own sequence at 1
    assert client.post(f"/app/api/invoices/{ta}/issue", cookies=a_cookies).json()["invoice_number"] == 1
    assert client.post(f"/app/api/invoices/{tb}/issue", cookies=b_cookies).json()["invoice_number"] == 1


def test_cannot_issue_for_another_business_sale():
    a_cookies, a_uid = _register_login("2777000005")
    b_cookies, b_uid = _register_login("2777000006")
    ta = _credit_sale("2777000005", a_uid)
    # Business B may not invoice business A's sale
    assert client.post(f"/app/api/invoices/{ta}/issue", cookies=b_cookies).status_code == 404
