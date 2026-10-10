"""
Expenses, and net profit.

Running costs are recorded directly, or shared by staff as an expense Note
that waits for the boss to approve. Only approved expenses count, and they
come off gross profit to give net profit. Expenses are for the owner and
authorised staff, like profit.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-expenses-000000000000000")

import uuid

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, InventoryItem, InventoryMovement, Transaction, TransactionItem, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _login(phone, pin):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def _business():
    n = next(_seq)
    owner_phone, staff_phone = f"23480673{n:05d}", f"23480674{n:05d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": owner_phone, "pin": "5678"})
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == owner_phone).first()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        db.add(User(phone=staff_phone, name="Sade", role="delegate", parent_id=owner.id,
                    can_view_all_transactions=False, recovery_pin_hash=web_auth._hash_pin("1234"),
                    subscription_status="ACTIVE"))
        # A month's sales: 10 bags of rice bought at 700, sold at 1000 → 3,000 gross profit.
        rice = InventoryItem(owner_phone=owner_phone, name="rice", unit="bag", quantity=50, selling_price=1000)
        db.add(rice); db.flush()
        db.add(InventoryMovement(owner_phone=owner_phone, item_id=rice.id, movement_type="IN",
                                 quantity=50, unit_price=700, source_type="SUPPLIER_PURCHASE"))
        tx = Transaction(type="SALE", amount=10000, recorded_by_id=owner.id, message_id=f"m-{uuid.uuid4()}")
        db.add(tx); db.flush()
        db.add(TransactionItem(transaction_id=tx.id, product="rice", quantity=10, unit_price=1000, total=10000))
        db.commit()
    finally:
        db.close()
    return owner_phone, _login(owner_phone, "5678"), staff_phone, _login(staff_phone, "1234")


def _expenses(cookies, **params):
    r = client.get("/app/api/expenses", params=params, cookies=cookies)
    assert r.status_code == 200, r.text
    return r.json()


def test_recorded_expenses_give_net_profit():
    _o, owner, _s, _sc = _business()
    assert client.post("/app/api/expenses", cookies=owner,
                       json={"amount": 1200, "category": "rent", "note": "October"}).status_code == 200
    client.post("/app/api/expenses", cookies=owner, json={"amount": 300, "category": "transport"})

    data = _expenses(owner)
    assert data["total"] == 1500
    assert data["by_category"][0] == {"category": "rent", "label": "Rent", "amount": 1200}

    profit = client.get("/app/api/dashboard", cookies=owner).json()["profit"]
    assert profit["gross_profit"] == 3000 and profit["expenses"] == 1500 and profit["net_profit"] == 1500


def test_an_expense_belongs_to_the_day_it_was_spent():
    _o, owner, _s, _sc = _business()
    client.post("/app/api/expenses", cookies=owner,
                json={"amount": 5000, "category": "rent", "spent_on": "2020-01-15"})
    assert _expenses(owner, period="MONTH")["total"] == 0          # not this month
    assert _expenses(owner)["total"] == 5000                       # all time


def test_edit_and_delete():
    _o, owner, _s, _sc = _business()
    client.post("/app/api/expenses", cookies=owner, json={"amount": 1000, "category": "repairs"})
    eid = _expenses(owner)["expenses"][0]["id"]
    client.put(f"/app/api/expenses/{eid}", cookies=owner, json={"amount": 1500, "category": "repairs"})
    assert _expenses(owner)["total"] == 1500
    client.delete(f"/app/api/expenses/{eid}", cookies=owner)
    assert _expenses(owner)["total"] == 0


def test_bad_input_is_refused():
    _o, owner, _s, _sc = _business()
    assert client.post("/app/api/expenses", cookies=owner, json={"amount": 0, "category": "rent"}).status_code == 422
    assert client.post("/app/api/expenses", cookies=owner, json={"amount": 100, "category": "stock"}).status_code == 400


def test_staff_share_an_expense_note_and_the_boss_approves_it():
    owner_phone, owner, staff_phone, staff = _business()
    r = client.post("/app/api/notes", cookies=staff, json={
        "body": "Paid okada to deliver to Mama Joy", "category": "expense", "amount": 800, "visibility": "all"})
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        alert = (db.query(AppNotification)
                 .filter(AppNotification.owner_phone == owner_phone, AppNotification.event_type == "expense_note")
                 .first())
        assert alert and alert.link == "/expenses" and "N800" in alert.body
    finally:
        db.close()

    data = _expenses(owner)
    assert data["total"] == 0                                      # not counted until approved
    assert len(data["to_review"]) == 1 and data["to_review"][0]["shared_by"] == "Sade"
    assert client.get("/app/api/dashboard", cookies=owner).json()["profit"]["expenses_to_review"] == 1

    note_id = data["to_review"][0]["note_id"]
    assert client.post(f"/app/api/expenses/from-note/{note_id}", cookies=owner,
                       json={"category": "transport"}).status_code == 200
    data = _expenses(owner)
    assert data["total"] == 800 and data["to_review"] == []
    assert data["expenses"][0]["from_note"] is True
    # Decided once.
    assert client.post(f"/app/api/expenses/from-note/{note_id}", cookies=owner,
                       json={"category": "transport"}).status_code == 409

    db = SessionLocal()
    try:
        told = db.query(AppNotification).filter(AppNotification.owner_phone == staff_phone,
                                                AppNotification.event_type == "expense_review").first()
        assert told and "approved" in told.body
    finally:
        db.close()
    notes = client.get("/app/api/notes", cookies=owner).json()["notes"]
    assert notes[0]["expense_status"] == "APPROVED"


def test_dismissing_a_note_keeps_it_out():
    _o, owner, _sp, staff = _business()
    client.post("/app/api/notes", cookies=staff, json={
        "body": "Bought 5 bags of rice for the shop", "category": "expense", "amount": 3500, "visibility": "all"})
    note_id = _expenses(owner)["to_review"][0]["note_id"]
    client.post(f"/app/api/expenses/notes/{note_id}/dismiss", cookies=owner)
    data = _expenses(owner)
    assert data["total"] == 0 and data["to_review"] == []


def test_deleting_an_approved_expense_puts_the_note_back_to_review():
    _o, owner, _sp, staff = _business()
    client.post("/app/api/notes", cookies=staff, json={
        "body": "Diesel for generator", "category": "expense", "amount": 2000, "visibility": "all"})
    note_id = _expenses(owner)["to_review"][0]["note_id"]
    client.post(f"/app/api/expenses/from-note/{note_id}", cookies=owner, json={"category": "fuel"})
    eid = _expenses(owner)["expenses"][0]["id"]
    client.delete(f"/app/api/expenses/{eid}", cookies=owner)
    assert len(_expenses(owner)["to_review"]) == 1


def test_regular_staff_cannot_see_or_record_expenses():
    _o, _owner, _sp, staff = _business()
    assert client.get("/app/api/expenses", cookies=staff).status_code == 403
    assert client.post("/app/api/expenses", cookies=staff,
                       json={"amount": 100, "category": "rent"}).status_code == 403


def test_titi_gives_net_profit():
    from business_facts import _fact_profit

    class Ask:
        period = None
    owner_phone, owner, _s, _sc = _business()
    client.post("/app/api/expenses", cookies=owner, json={"amount": 1000, "category": "rent"})
    db = SessionLocal()
    try:
        text = _fact_profit(db, owner_phone, Ask())
    finally:
        db.close()
    assert "net profit" in text.lower() and ("2,000" in text)
