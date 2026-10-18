"""
Contractors quote first, take a deposit before work starts, and the balance on
completion. Every business can put its logo on receipts and invoices.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-quotes-logo-0000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
LOGO = "data:image/png;base64," + "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _business(btype):
    phone = f"2348097{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bayo Builders", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(phone=phone).one()
        u.business_type = btype
        u.business_category = "services_artisans" if btype != "provision_store" else "retail_trading"
        c = Customer(owner_phone=phone, name="Chief Okafor", customer_phone="2348035550000", balance=0)
        db.add(c); db.commit()
        cid = c.id
    finally:
        db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cook, cid


def _quote(cook, cid, deposit=60, quote=True):
    return client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cid, "is_quote": quote, "deposit_percent": deposit,
        "items": [{"name": "Block work", "qty": 1, "unit_price": 700000},
                  {"name": "Labour", "qty": 1, "unit_price": 300000}],
    })


def test_a_contractor_quotes_then_takes_a_deposit_then_the_balance():
    phone, cook, cid = _business("building_contractor")
    assert client.get("/app/api/auth/me", cookies=cook).json()["can_quote"] is True

    r = _quote(cook, cid)
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["is_quote"] and q["status"] == "quote" and q["ref"].startswith("QT-")
    assert q["deposit_amount"] == 600000 and q["balance_on_completion"] == 400000

    # Nothing owed, nothing to pay, until the customer accepts
    r = client.post(f"/app/api/invoices/doc/{q['id']}/pay", cookies=cook, json={"amount": 600000})
    assert r.status_code == 400 and "quotation" in r.json()["detail"]

    inv = client.post(f"/app/api/invoices/doc/{q['id']}/accept", cookies=cook).json()
    assert inv["status"] == "draft" and inv["ref"].startswith("INV-") and inv["quote_ref"] == q["ref"]

    inv = client.post(f"/app/api/invoices/doc/{q['id']}/pay", cookies=cook, json={"amount": 600000}).json()
    assert inv["status"] == "deposit_paid" and inv["deposit_paid"] and inv["moved_to_debt"] == 400000
    db = SessionLocal()
    try:
        assert db.query(Customer).get(cid).balance == 400000        # the balance on completion is owed
    finally:
        db.close()

    listing = client.get("/app/api/invoices", cookies=cook).json()
    assert listing["summary"]["deposit_paid"] == 1


def test_the_whatsapp_text_says_quotation_and_the_deposit():
    from invoices import format_invoice_doc_text
    _phone, cook, cid = _business("welding_fabrication")
    doc = _quote(cook, cid, deposit=50).json()
    text = format_invoice_doc_text(doc)
    assert text.startswith("*QUOTATION*") and "Deposit before work starts (50%): N500,000" in text
    assert "Balance on completion: N500,000" in text


def test_a_shop_cannot_write_quotations_but_its_invoices_work_as_before():
    _phone, cook, cid = _business("provision_store")
    assert client.get("/app/api/auth/me", cookies=cook).json()["can_quote"] is False
    assert _quote(cook, cid).status_code == 403
    r = _quote(cook, cid, deposit=None, quote=False)
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["deposit_amount"] == 0


def test_the_logo_prints_on_receipts_and_invoices():
    phone, cook, cid = _business("building_contractor")
    assert client.post("/app/api/auth/profile/logo", cookies=cook, json={"data_url": "javascript:alert(1)"}).status_code == 400
    r = client.post("/app/api/auth/profile/logo", cookies=cook, json={"data_url": LOGO})
    assert r.status_code == 200 and client.get("/app/api/auth/profile/logo", cookies=cook).json()["logo"] == LOGO

    assert _quote(cook, cid).json()["biz_logo"] == LOGO
    sale = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "items": [{"name": "Repair", "qty": 1, "unit_price": 5000}], "payment_amount": 5000}).json()
    assert client.get(f"/app/api/pos/receipt/{sale['receipt_id']}", cookies=cook).json()["biz_logo"] == LOGO

    client.delete("/app/api/auth/profile/logo", cookies=cook)
    assert client.get("/app/api/auth/profile/logo", cookies=cook).json()["logo"] is None
