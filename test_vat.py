"""
VAT: off until the business switches it on, then either added on top of
prices or already inside them — the owner's choice in Settings. "No VAT"
products are left out; invoices keep the VAT they were written with.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-vat-000000000000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, InventoryItem
from vat import compute_vat

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348103{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Stores", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        tv = InventoryItem(owner_phone=phone, name="television", unit="piece", quantity=10,
                           selling_price=100000, is_available=True)
        rice = InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=10,
                             selling_price=50000, is_available=True, vat_exempt=True)
        ade = Customer(owner_phone=phone, name="ade", balance=0)
        db.add_all([tv, rice, ade]); db.commit()
        return phone, cook, tv.id, rice.id, ade.id
    finally:
        db.close()


def _vat(cook, **values):
    return client.put("/app/api/settings/business", cookies=cook, json={"values": values})


def _sell(phone, cook, lines, paid, cust=None, discount=0):
    return client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cust, "payment_amount": paid, "discount": discount,
        "items": lines}).json()


def _tv(tv, qty=1):
    return {"inventory_item_id": tv, "name": "television", "qty": qty, "unit": "piece", "unit_price": 100000}


def test_the_sum():
    assert compute_vat([(100000, False)], 0, None) == (0, 100000, 100000)
    assert compute_vat([(100000, False)], 0, {"rate": 7.5, "mode": "add"}) == (7500, 107500, 100000)
    assert compute_vat([(107500, False)], 0, {"rate": 7.5, "mode": "inclusive"}) == (7500, 107500, 107500)
    # No-VAT lines are left out; a discount shrinks the VAT in proportion
    assert compute_vat([(100000, False), (50000, True)], 15000, {"rate": 7.5, "mode": "add"})[0] == 6750


def test_off_by_default():
    phone, cook, tv, _r, _a = _shop()
    b = client.get("/app/api/settings", cookies=cook).json()["business"]
    assert b["vat_enabled"] is False and b["vat_mode"] == "add" and b["vat_rate"] == 7.5
    r = _sell(phone, cook, [_tv(tv)], 100000)
    assert r["total"] == 100000 and r["vat_amount"] == 0


def test_added_on_top_and_no_vat_products():
    phone, cook, tv, rice, _a = _shop()
    assert _vat(cook, vat_enabled=True, vat_number="TIN 1234-5678").status_code == 200
    r = _sell(phone, cook, [_tv(tv), {"inventory_item_id": rice, "name": "rice", "qty": 1, "unit": "bag",
                                       "unit_price": 50000}], 157500)
    assert (r["total"], r["vat_amount"], r["paid"]) == (157500, 7500, 157500)     # rice: no VAT
    rec = client.get(f"/app/api/pos/receipt/{r['receipt_id']}", cookies=cook).json()
    assert (rec["subtotal"], rec["vat_amount"], rec["vat_mode"], rec["vat_number"]) == (150000, 7500, "add", "TIN 1234-5678")
    from web_pos import format_receipt_text
    text = format_receipt_text(rec)
    assert "Subtotal: N150,000" in text and "VAT 7.5%: N7,500" in text and "VAT no: TIN 1234-5678" in text


def test_prices_already_include_vat():
    phone, cook, tv, _r, _a = _shop()
    _vat(cook, vat_enabled=True, vat_mode="inclusive")
    r = _sell(phone, cook, [_tv(tv)], 100000)
    assert (r["total"], r["vat_amount"]) == (100000, 6977)        # 100,000 × 7.5/107.5
    from web_pos import format_receipt_text
    rec = client.get(f"/app/api/pos/receipt/{r['receipt_id']}", cookies=cook).json()
    assert "(incl. VAT 7.5%: N6,977)" in format_receipt_text(rec)


def test_invoice_keeps_its_vat_and_paying_in_full_leaves_no_debt():
    phone, cook, tv, _r, ade = _shop()
    _vat(cook, vat_enabled=True)
    inv = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": ade, "items": [{"inventory_item_id": tv, "name": "television", "qty": 2, "unit_price": 100000}]}).json()
    doc = client.get(f"/app/api/invoices/doc/{inv['id']}", cookies=cook).json()
    assert (doc["total"], doc["vat_amount"], doc["subtotal"]) == (215000, 15000, 200000)
    from invoices import format_invoice_doc_text
    assert "VAT 7.5%: N15,000" in format_invoice_doc_text(doc)

    _vat(cook, vat_enabled=False)                                     # Settings change later…
    paid = client.post(f"/app/api/invoices/doc/{inv['id']}/pay", cookies=cook, json={"amount": 215000}).json()
    assert paid["status"] == "paid"                                    # …the invoice keeps its VAT
    db = SessionLocal()
    try:
        assert db.query(Customer).get(ade).balance == 0
    finally:
        db.close()


def test_refund_gives_back_the_vat():
    phone, cook, tv, _r, ade = _shop()
    _vat(cook, vat_enabled=True)
    r = _sell(phone, cook, [_tv(tv)], 107500, cust=ade)
    lines = client.get(f"/app/api/sales/{r['receipt_id']}/returnable", cookies=cook).json()["lines"]
    note = client.post(f"/app/api/sales/{r['receipt_id']}/return", cookies=cook, json={
        "lines": [{"line_id": lines[0]["line_id"], "quantity": 1}], "mode": "REFUND",
        "restock": "SELLABLE", "reason": "faulty"}).json()
    assert note["amount"] == 107500


def test_vat_collected_report_and_no_vat_tick():
    phone, cook, tv, _r, _a = _shop()
    _vat(cook, vat_enabled=True)
    _sell(phone, cook, [_tv(tv, 2)], 215000)
    rep = client.get("/app/api/reports/vat", cookies=cook).json()
    assert rep["this_month"] == 15000
    client.put(f"/app/api/inventory/{tv}", cookies=cook, json={"vat_exempt": True})
    assert _sell(phone, cook, [_tv(tv)], 100000)["vat_amount"] == 0


def test_bad_settings_are_refused():
    _p, cook, *_ = _shop()
    assert _vat(cook, vat_mode="sometimes").status_code == 400
    assert _vat(cook, vat_rate=0).status_code == 400


@pytest.mark.parametrize("text", [
    "how do I add VAT to my invoice?", "how to charge vat", "where do I put my TIN?",
    "my prices already include vat, what do I do?",
])
def test_titi_explains_vat(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    from models import User
    p = parse_message(text) or {}
    assert (p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "vat"
    a = build_app_guide_message("vat", User(phone="1", business_type="pharmacy", business_category="health"))
    assert "Add VAT on top" in a and "Already include VAT" in a and "No VAT" in a and "{till}" not in a


def test_vat_filing_service_is_not_the_vat_setting():
    from faq import detect_faq
    assert detect_faq("how much is vat filing?") != "vat"
