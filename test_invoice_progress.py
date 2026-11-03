"""
Quotation → Accepted (invoice) → Paid (receipt) → Delivered → Completed.
Completed = paid in full (at once, or the rest later from Debts) AND the goods
delivered, or nothing to deliver. The invoice list has a Completed tab.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-invoice-progress-0000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, InventoryItem, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _business():
    phone = f"2348096{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bayo Builders", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(phone=phone).one()
        u.business_type = "building_contractor"; u.business_category = "services_artisans"
        c = Customer(owner_phone=phone, name="Chief Okafor", customer_phone="2348035550000", balance=0)
        cem = InventoryItem(owner_phone=phone, name="cement", unit="bag", selling_price=10000,
                            quantity=100, is_available=True)
        db.add_all([c, cem]); db.commit()
        cid, item = c.id, cem.id
    finally:
        db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return cook, cid, item


def _steps(doc):
    return {s["key"]: s for s in doc["steps"]}


def _stage_of(cook, inv_id):
    return next(r for r in client.get("/app/api/invoices", cookies=cook).json()["invoices"]
                if r.get("kind") == "invoice" and r["id"] == inv_id)["stage"]


def test_quote_to_completed_with_goods_and_balance_paid_later():
    cook, cid, cem = _business()
    q = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cid, "is_quote": True,
        "items": [{"inventory_item_id": cem, "name": "cement", "qty": 10, "unit": "bag", "unit_price": 10000}],
    }).json()
    assert q["stage"] == "quote"
    assert [s["key"] for s in q["steps"]] == ["quote", "invoice", "paid", "delivered", "completed"]
    assert _steps(q)["quote"]["done"] and not _steps(q)["invoice"]["done"]

    inv = client.post(f"/app/api/invoices/doc/{q['id']}/accept", cookies=cook).json()
    st = _steps(inv)
    assert inv["stage"] == "invoice" and st["invoice"]["done"] and st["invoice"]["ref"].startswith("INV-")
    assert st["invoice"]["label"] == "Accepted" and st["quote"]["ref"] == q["ref"]

    # Part paid: the rest is the customer's debt
    inv = client.post(f"/app/api/invoices/doc/{q['id']}/pay", cookies=cook, json={"amount": 60000}).json()
    st = _steps(inv)
    assert inv["stage"] == "part_paid" and st["paid"]["partial"] and st["paid"]["label"] == "Part paid"
    assert st["paid"]["ref"].startswith("Receipt #") and st["paid"]["receipt_id"] == inv["transaction_id"]
    assert _stage_of(cook, q["id"]) == "part_paid"

    # The balance comes in later, from Debts: paid in full, but not delivered yet
    assert client.post(f"/app/api/customers/{cid}/pay", cookies=cook, json={"amount": 40000}).status_code == 200
    inv = client.get(f"/app/api/invoices/doc/{q['id']}", cookies=cook).json()
    assert inv["status"] == "part_paid"            # what was paid at the time stays as it was
    assert inv["stage"] == "paid" and _steps(inv)["paid"]["done"] and not _steps(inv)["completed"]["done"]
    summary = client.get("/app/api/invoices", cookies=cook).json()["summary"]
    assert summary["paid"] == 1 and summary["part_paid"] == 0

    # Delivered: Completed
    inv = client.post(f"/app/api/invoices/doc/{q['id']}/deliver", cookies=cook).json()
    assert inv["stage"] == "completed" and all(s["done"] for s in inv["steps"])
    lst = client.get("/app/api/invoices", cookies=cook, params={"status": "completed"}).json()
    assert [r["id"] for r in lst["invoices"]] == [q["id"]] and lst["summary"]["completed"] == 1
    assert client.get("/app/api/invoices", cookies=cook, params={"status": "paid"}).json()["invoices"] == []


def test_paid_in_full_service_job_is_completed_at_once():
    cook, cid, _cem = _business()
    inv = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cid, "items": [{"name": "Labour", "qty": 1, "unit_price": 300000}]}).json()
    assert [s["key"] for s in inv["steps"]] == ["invoice", "paid", "completed"]   # nothing to deliver
    assert _steps(inv)["invoice"]["label"] == "Invoice"
    inv = client.post(f"/app/api/invoices/doc/{inv['id']}/pay", cookies=cook, json={"amount": 300000}).json()
    assert inv["status"] == "paid" and inv["stage"] == "completed"
    assert _steps(inv)["completed"]["date"] == inv["paid_at"]


def test_delivered_but_unpaid_is_not_completed_and_cancelled_has_no_steps():
    cook, cid, cem = _business()
    inv = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cid,
        "items": [{"inventory_item_id": cem, "name": "cement", "qty": 2, "unit": "bag", "unit_price": 10000}],
    }).json()
    inv = client.post(f"/app/api/invoices/doc/{inv['id']}/deliver", cookies=cook).json()
    assert inv["stage"] == "invoice" and _steps(inv)["delivered"]["done"] and not _steps(inv)["paid"]["done"]

    other = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cid, "items": [{"name": "Labour", "qty": 1, "unit_price": 5000}]}).json()
    gone = client.post(f"/app/api/invoices/doc/{other['id']}/cancel", cookies=cook).json()
    assert gone["stage"] == "cancelled" and gone["steps"] == []


def test_titi_explains_progress():
    from faq import FAQ_ANSWERS, detect_faq
    assert detect_faq("what does completed mean on my invoice?") == "invoices"
    assert "Completed" in FAQ_ANSWERS["invoices"] and "Quotation → Accepted" in FAQ_ANSWERS["quotation"]
