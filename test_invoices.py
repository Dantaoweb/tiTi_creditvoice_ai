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


# ── Stage 2: list + derived status ───────────────────────────────────────────

def _pay(owner_phone, name, amount):
    db = SessionLocal()
    c = db.query(Customer).filter(Customer.owner_phone == owner_phone, Customer.name == name).first()
    db.add(Transaction(customer_id=c.id, type="PAY", amount=amount,
                       message_id=f"pay-{uuid.uuid4()}"))
    db.commit(); db.close()


def _set_due(tx_id, days_from_now):
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    tx.due_date = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days_from_now)
    db.commit(); db.close()


def test_list_open_and_paid_status():
    cookies, uid = _register_login("2777000007")
    t1 = _credit_sale("2777000007", uid, amount=5000, name="Ada")
    client.post(f"/app/api/invoices/{t1}/issue", cookies=cookies)

    data = client.get("/app/api/invoices", cookies=cookies).json()
    assert data["summary"]["open"] == 1
    row = data["invoices"][0]
    assert row["status"] == "open" and row["outstanding"] == 5000

    _pay("2777000007", "Ada", 5000)              # fully paid
    data = client.get("/app/api/invoices", cookies=cookies).json()
    row = data["invoices"][0]
    assert row["status"] == "paid" and row["outstanding"] == 0


def test_overdue_when_past_due_and_unpaid():
    cookies, uid = _register_login("2777000008")
    t1 = _credit_sale("2777000008", uid, amount=3000, name="Bola")
    _set_due(t1, -2)                              # due date 2 days ago
    client.post(f"/app/api/invoices/{t1}/issue", cookies=cookies)
    data = client.get("/app/api/invoices?status=overdue", cookies=cookies).json()
    assert len(data["invoices"]) == 1
    assert data["invoices"][0]["status"] == "overdue"


def _set_phone(owner_phone, name, phone):
    db = SessionLocal()
    c = db.query(Customer).filter(Customer.owner_phone == owner_phone, Customer.name == name).first()
    c.customer_phone = phone
    db.commit(); db.close()


def test_send_invoice_records_sent(monkeypatch):
    # The WhatsApp send is stubbed; we assert the invoice is stamped as sent
    # and the formatted text is a proper invoice.
    sent_box = {}
    import whatsapp_client
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message",
                        lambda phone, msg: sent_box.update(phone=phone, msg=msg))

    cookies, uid = _register_login("2777000010")
    t1 = _credit_sale("2777000010", uid, amount=5000, name="Ada")
    _set_phone("2777000010", "Ada", "2348123456789")

    r = client.post(f"/app/api/invoices/{t1}/send", cookies=cookies)
    assert r.status_code == 200, r.text
    assert r.json()["sent_at"]
    assert sent_box.get("phone") == "2348123456789"
    assert "INVOICE" in sent_box.get("msg", "") and "Amount due" in sent_box.get("msg", "")

    # The list now shows it as sent
    rows = {x["id"]: x for x in client.get("/app/api/invoices", cookies=cookies).json()["invoices"]}
    assert rows[t1]["sent_at"]


def test_send_invoice_without_phone_is_rejected():
    cookies, uid = _register_login("2777000011")
    t1 = _credit_sale("2777000011", uid, amount=5000, name="Dele")   # no phone set
    r = client.post(f"/app/api/invoices/{t1}/send", cookies=cookies)
    assert r.status_code == 400
    assert "phone" in r.json()["detail"].lower()


def test_fifo_allocation_across_two_invoices():
    # Two invoices for one customer; a partial payment clears the older one first.
    cookies, uid = _register_login("2777000009")
    t1 = _credit_sale("2777000009", uid, amount=4000, name="Chika")   # older
    t2 = _credit_sale("2777000009", uid, amount=6000, name="Chika")   # newer
    client.post(f"/app/api/invoices/{t1}/issue", cookies=cookies)
    client.post(f"/app/api/invoices/{t2}/issue", cookies=cookies)
    _pay("2777000009", "Chika", 4000)            # exactly clears the first

    rows = {r["id"]: r for r in client.get("/app/api/invoices", cookies=cookies).json()["invoices"]}
    assert rows[t1]["status"] == "paid" and rows[t1]["outstanding"] == 0
    assert rows[t2]["status"] == "open" and rows[t2]["outstanding"] == 6000
