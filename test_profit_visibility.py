"""
Profit is for the owner and authorised staff, not regular staff.

Regular staff record sales; what the business makes on them — profit,
per-product margins, the value of stock at cost — is shown only to the owner
and staff authorised to see all records (branch admins).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-profit-visibility-00000000")

import uuid

import pytest
from fastapi.testclient import TestClient

import business_facts
import web_auth
from database import SessionLocal
from main import app
from models import Branch, InventoryItem, InventoryMovement, Transaction, TransactionItem, User

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
    owner_phone, staff_phone, admin_phone = f"23480683{n:05d}", f"23480684{n:05d}", f"23480685{n:05d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": owner_phone, "pin": "5678"})
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == owner_phone).first()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        branch = Branch(owner_phone=owner_phone, name="Ikeja", is_default=True)
        db.add(branch); db.commit()
        db.add_all([
            User(phone=staff_phone, name="Sade", role="delegate", parent_id=owner.id, branch_id=branch.id,
                 can_view_all_transactions=False, recovery_pin_hash=web_auth._hash_pin("1234"),
                 subscription_status="ACTIVE"),
            User(phone=admin_phone, name="Bimpe", role="delegate", parent_id=owner.id, branch_id=branch.id,
                 can_view_all_transactions=True, recovery_pin_hash=web_auth._hash_pin("1234"),
                 subscription_status="ACTIVE"),
        ])
        rice = InventoryItem(owner_phone=owner_phone, name="rice", unit="bag", quantity=50,
                             selling_price=1000, branch_id=branch.id)
        db.add(rice); db.flush()
        db.add(InventoryMovement(owner_phone=owner_phone, item_id=rice.id, movement_type="IN",
                                 quantity=50, unit_price=700, source_type="SUPPLIER_PURCHASE"))
        tx = Transaction(type="SALE", amount=10000, recorded_by_id=owner.id, branch_id=branch.id,
                         message_id=f"m-{uuid.uuid4()}")
        db.add(tx); db.flush()
        db.add(TransactionItem(transaction_id=tx.id, product="rice", quantity=10, unit_price=1000, total=10000))
        db.commit()
    finally:
        db.close()
    return owner_phone, staff_phone, admin_phone


def test_owner_and_authorised_staff_see_profit():
    owner_phone, _staff, admin_phone = _business()
    for cookies in (_login(owner_phone, "5678"), _login(admin_phone, "1234")):
        dash = client.get("/app/api/dashboard", cookies=cookies).json()
        assert dash["profit"] is not None and dash["profit_hidden"] is False
        ins = client.get("/app/api/reports/inventory-insights", cookies=cookies).json()
        assert ins["profit"] is not None


def test_regular_staff_see_no_profit_or_margins():
    _owner, staff_phone, _admin = _business()
    cookies = _login(staff_phone, "1234")
    dash = client.get("/app/api/dashboard", cookies=cookies).json()
    assert dash["profit"] is None and dash["margin"] is None and dash["profit_hidden"] is True
    ins = client.get("/app/api/reports/inventory-insights", cookies=cookies).json()
    assert ins["profit"] is None and ins["margin"] == [] and ins["profit_hidden"] is True


def test_titi_wont_tell_regular_staff_the_profit():
    owner_phone, staff_phone, _admin = _business()
    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.phone == staff_phone).first()
        for question in ["what is my profit this month", "what is my margin on rice", "what is my stock worth"]:
            hidden = business_facts.answer(db, owner_phone, question, recorded_by_id=staff.id)
            assert hidden == business_facts.PROFIT_HIDDEN_REPLY, question
        shown = business_facts.answer(db, owner_phone, "what is my profit this month")
        assert shown and shown != business_facts.PROFIT_HIDDEN_REPLY
    finally:
        db.close()


def test_is_rice_profitable_is_hidden_from_regular_staff():
    from analytics_commands import answer_product_profit
    owner_phone, staff_phone, _admin = _business()
    sent = []
    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.phone == staff_phone).first()
        r = answer_product_profit(db, owner_phone, "rice", lambda p, m: sent.append(m), staff_phone,
                                  recorded_by_id=staff.id)
    finally:
        db.close()
    assert r["status"] == "analytics_product_profit_hidden"
    assert sent == [business_facts.PROFIT_HIDDEN_REPLY]
