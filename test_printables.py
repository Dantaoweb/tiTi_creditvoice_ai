"""
Receipts & printables: business email and bank accounts on the Profile; how
receipts, invoices, quotations and waybills print, chosen in Settings. The
default is the small thermal printer; bank details go on invoices and
quotations, on receipts only when switched on, and never on waybills.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-printables-00000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
sent = []


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sent.clear()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda to, m, *a, **k: sent.append((to, m)) or True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348096{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Cement", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        item = InventoryItem(owner_phone=phone, name="cement", unit="bag", quantity=100,
                             selling_price=9000, cost_price=8000, is_available=True)
        cust = Customer(owner_phone=phone, name="ade", customer_phone="2348034444444", balance=0)
        db.add_all([item, cust]); db.commit()
        return phone, cook, item.id, cust.id
    finally:
        db.close()


ACCT = {"bank": "GTBank", "number": "0123456789", "name": "Bello Cement Ltd"}


def _profile(cook, **kw):
    return client.put("/app/api/auth/profile", cookies=cook, json={"name": "Bello Cement", **kw})


def _sale(phone, cook, item_id, cust):
    return client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cust, "payment_amount": 0,
        "items": [{"inventory_item_id": item_id, "name": "cement", "qty": 2, "unit": "bag",
                   "unit_price": 9000}]}).json()["receipt_id"]


def test_profile_keeps_business_email_and_bank_accounts():
    _phone, cook, *_ = _shop()
    r = _profile(cook, business_email="sales@bello.ng", bank_accounts=[ACCT, {"bank": "", "number": "", "name": ""}])
    assert r.status_code == 200 and r.json()["business_email"] == "sales@bello.ng"
    assert r.json()["bank_accounts"] == [ACCT]                       # blank row dropped
    me = client.get("/app/api/auth/me", cookies=cook).json()
    assert me["business_email"] == "sales@bello.ng" and me["bank_accounts"] == [ACCT]

    assert _profile(cook, business_email="not-an-email").status_code == 400
    assert _profile(cook, bank_accounts=[{"bank": "GTBank", "number": "01234ABC"}]).status_code == 400
    assert _profile(cook, bank_accounts=[ACCT, ACCT, ACCT]).status_code == 400
    # The login email is untouched
    assert client.get("/app/api/auth/me", cookies=cook).json()["email"] is None


def test_defaults_small_thermal_printer_and_todays_layout():
    _phone, cook, *_ = _shop()
    b = client.get("/app/api/settings", cookies=cook).json()["business"]
    assert (b["print_paper"], b["print_logo"], b["print_align"]) == ("80mm", "top", "center")
    assert b["print_bank_invoices"] is True and b["print_bank_receipts"] is False


def test_where_bank_details_print():
    phone, cook, item_id, cust = _shop()
    _profile(cook, business_email="sales@bello.ng", bank_accounts=[ACCT])
    tx = _sale(phone, cook, item_id, cust)

    receipt = client.get(f"/app/api/pos/receipt/{tx}", cookies=cook).json()
    assert receipt["print"]["paper"] == "80mm" and receipt["biz_email"] == "sales@bello.ng"
    assert receipt["bank_accounts"] == []                            # receipts: off by default

    inv = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cust, "items": [{"inventory_item_id": item_id, "name": "cement", "qty": 1, "unit_price": 9000}]})
    assert inv.status_code == 200, inv.text
    doc = client.get(f"/app/api/invoices/doc/{inv.json()['id']}", cookies=cook).json()
    assert doc["bank_accounts"] == [ACCT]                            # invoices: on by default
    from invoices import format_invoice_doc_text
    assert "Pay to: GTBank 0123456789 (Bello Cement Ltd)" in format_invoice_doc_text(doc)

    # Switch receipts on, invoices off
    client.put("/app/api/settings/business", cookies=cook,
               json={"values": {"print_bank_receipts": True, "print_bank_invoices": False}})
    assert client.get(f"/app/api/pos/receipt/{tx}", cookies=cook).json()["bank_accounts"] == [ACCT]
    assert client.get(f"/app/api/invoices/doc/{inv.json()['id']}", cookies=cook).json()["bank_accounts"] == []


def test_waybills_never_carry_bank_details():
    phone, cook, item_id, cust = _shop()
    _profile(cook, bank_accounts=[ACCT])
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"print_bank_receipts": True}})
    client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cust, "payment_amount": 0,
        "items": [{"inventory_item_id": item_id, "name": "cement", "qty": 5, "unit": "bag",
                   "unit_price": 9000, "delivered_qty": 0}]})
    wb = client.post("/app/api/waybills", cookies=cook, json={
        "customer_id": cust, "lines": [{"key": f"i:{item_id}", "quantity": 5}], "notify": False}).json()
    doc = client.get(f"/app/api/waybills/{wb['id']}", cookies=cook).json()
    assert doc["bank_accounts"] == [] and doc["print"]["paper"] == "80mm"


def test_layout_choices_and_own_words():
    phone, cook, item_id, cust = _shop()
    r = client.put("/app/api/settings/business", cookies=cook, json={"values": {
        "print_paper": "a4", "print_logo": "left", "print_align": "left", "print_show_phone": False,
        "receipt_title": "Sales Receipt", "receipt_footer": "No refund after 7 days."}})
    assert r.status_code == 200
    tx = _sale(phone, cook, item_id, cust)
    receipt = client.get(f"/app/api/pos/receipt/{tx}", cookies=cook).json()
    assert receipt["print"] == {"paper": "a4", "logo": "left", "align": "left", "show_phone": False,
                                "show_address": True, "show_email": True}
    assert receipt["config"]["title"] == "Sales Receipt"
    assert receipt["config"]["footer"] == "No refund after 7 days."
    from web_pos import format_receipt_text
    assert "No refund after 7 days." in format_receipt_text(receipt)

    assert client.put("/app/api/settings/business", cookies=cook,
                      json={"values": {"print_paper": "a3"}}).status_code == 400


def test_print_preview_has_the_real_details():
    _phone, cook, *_ = _shop()
    _profile(cook, address="12 Market Rd", bank_accounts=[ACCT])
    p = client.get("/app/api/settings/print-preview", cookies=cook).json()
    assert p["biz_address"] == "12 Market Rd" and p["all_bank_accounts"] == [ACCT]
