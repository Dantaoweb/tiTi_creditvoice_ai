"""
A receipt must account for debt the customer carried in from earlier sales.
"Balance" used to mean only the unpaid part of THIS sale, so a customer who
owed 5,000 and bought 3,000 more got a receipt reading "Balance: 2,000" while
owing 7,000 — and the WhatsApp copy left out old debt settled at checkout, so
it could show 3,000 when the customer had just handed over 8,000.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-receipt-debt-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer
from web_pos import format_receipt_text

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(business_type=None):
    phone = f"234851{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Shop", "phone": phone, "pin": "5678"})
    if business_type:
        db = SessionLocal()
        from models import User
        u = db.query(User).filter(User.phone == phone).first()
        u.business_type = business_type
        db.commit(); db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _customer(phone, cook, name="Ade"):
    return client.post("/app/api/customers", cookies=cook,
                       json={"owner_phone": phone, "name": name}).json()["id"]


def _sell(phone, cook, cid, amount, paid=0, debt_payment=0):
    body = {"owner_phone": phone, "customer_id": cid,
            "items": [{"name": "goods", "qty": 1, "unit_price": amount}],
            "payment_amount": paid}
    if debt_payment:
        body["debt_payment"] = debt_payment
    r = client.post("/app/api/pos/save", cookies=cook, json=body)
    assert r.status_code == 200, r.text
    return r.json()["receipt_id"]


def _receipt(cook, rid):
    r = client.get(f"/app/api/pos/receipt/{rid}", cookies=cook)
    assert r.status_code == 200, r.text
    return r.json()


def _balance(cid):
    db = SessionLocal()
    try:
        return db.query(Customer).filter(Customer.id == cid).first().balance
    finally:
        db.close()


def test_receipt_shows_previous_balance_and_true_total_owed():
    phone, cook = _owner()
    cid = _customer(phone, cook)
    _sell(phone, cook, cid, 5000)                       # old debt
    rid = _sell(phone, cook, cid, 3000, paid=1000)      # today
    rec = _receipt(cook, rid)

    assert rec["balance_owed"] == 2000          # this sale only
    assert rec["previous_balance"] == 5000
    assert rec["total_owed_now"] == 7000 == _balance(cid)

    text = format_receipt_text(rec)
    assert "Balance this sale: N2,000" in text
    assert "Previous balance: N5,000" in text
    assert "Total owed now: N7,000" in text


def test_whatsapp_receipt_shows_debt_settled_at_checkout():
    phone, cook = _owner()
    cid = _customer(phone, cook, "Bola")
    _sell(phone, cook, cid, 5000)
    rid = _sell(phone, cook, cid, 3000, paid=3000, debt_payment=5000)
    rec = _receipt(cook, rid)

    assert rec["prior_debt_paid"] == 5000
    assert rec["grand_total_collected"] == 8000     # what the customer handed over
    assert rec["total_owed_now"] == 0 == _balance(cid)

    text = format_receipt_text(rec)
    assert "Previous debt settled: N5,000" in text
    assert "Total received: N8,000" in text
    assert "Total owed now: N0" in text


def test_settlement_cannot_exceed_debt_from_before_this_sale():
    phone, cook = _owner()
    cid = _customer(phone, cook, "Chidi")
    _sell(phone, cook, cid, 500)                                  # old debt 500
    rid = _sell(phone, cook, cid, 1000, paid=0, debt_payment=1000)  # asks to settle 1,000
    rec = _receipt(cook, rid)

    assert rec["prior_debt_paid"] == 500        # capped at the real prior debt
    assert rec["previous_balance"] == 500
    assert rec["total_owed_now"] == 1000 == _balance(cid)


def test_no_prior_debt_lines_for_a_clean_customer():
    phone, cook = _owner()
    cid = _customer(phone, cook, "Ngozi")
    rid = _sell(phone, cook, cid, 2000, paid=2000)
    rec = _receipt(cook, rid)
    assert rec["previous_balance"] == 0 and rec["total_owed_now"] == 0
    text = format_receipt_text(rec)
    assert "Previous balance" not in text and "Total owed now" not in text


def test_previous_balance_is_fixed_at_the_time_of_sale():
    """A printed receipt must not change when the customer pays later."""
    phone, cook = _owner()
    cid = _customer(phone, cook, "Emeka")
    _sell(phone, cook, cid, 5000)
    rid = _sell(phone, cook, cid, 3000, paid=1000)
    client.post(f"/app/api/customers/{cid}/pay", cookies=cook, json={"amount": 7000})
    rec = _receipt(cook, rid)
    assert rec["previous_balance"] == 5000 and rec["total_owed_now"] == 7000
    assert _balance(cid) == 0


def test_invoice_text_shows_previous_balance():
    from invoices import format_invoice_text
    phone, cook = _owner()
    cid = _customer(phone, cook, "Tunde")
    _sell(phone, cook, cid, 5000)                      # earlier debt
    rid = _sell(phone, cook, cid, 3000, paid=1000)     # this invoice
    assert client.post(f"/app/api/invoices/{rid}/issue", cookies=cook).status_code == 200
    text = format_invoice_text(_receipt(cook, rid))
    assert "Amount due (this invoice): N2,000" in text
    assert "Previous balance:          N5,000" in text
    assert "Total due now:            N7,000" in text


def test_invoice_text_unchanged_without_previous_balance():
    from invoices import format_invoice_text
    phone, cook = _owner()
    cid = _customer(phone, cook, "Sola")
    rid = _sell(phone, cook, cid, 3000, paid=1000)
    assert client.post(f"/app/api/invoices/{rid}/issue", cookies=cook).status_code == 200
    text = format_invoice_text(_receipt(cook, rid))
    assert "*Amount due: N2,000*" in text
    assert "Previous balance" not in text and "Total due now" not in text


@pytest.mark.parametrize("business_type", ["pharmacy", "clinic", "school", "salon_beauty"])
def test_debt_lines_work_for_every_business_type(business_type):
    phone, cook = _owner(business_type)
    cid = _customer(phone, cook, "Patient A")
    _sell(phone, cook, cid, 4000)
    rid = _sell(phone, cook, cid, 1000, paid=0)
    rec = _receipt(cook, rid)
    assert rec["previous_balance"] == 4000
    assert rec["total_owed_now"] == 5000 == _balance(cid)
    assert "Total owed now: N5,000" in format_receipt_text(rec)
