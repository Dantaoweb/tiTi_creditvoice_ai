"""
Basic plan enforcement in the web app:
  - 100 transactions/month cap blocks new POS sales (debt payments exempt);
  - 5 active products cap applies to bulk add (extras saved as drafts);
  - paid plans are unlimited.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-basic-limits-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Transaction, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(5000, 6000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(plan=None):
    n = next(_seq)
    phone = f"234827{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Biz", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        if plan:
            u.subscription_plan = plan
            u.subscription_status = "ACTIVE"
        db.commit()
        uid = u.id
    finally:
        db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, uid, cookies


def _seed_month_sales(owner_phone, owner_id, n):
    db = SessionLocal()
    try:
        db.add_all([
            Transaction(type="SALE", amount=100, recorded_by_id=owner_id,
                        message_id=f"s-{uuid.uuid4()}")
            for _ in range(n)
        ])
        db.commit()
    finally:
        db.close()


def _pos_payload(phone):
    return {"owner_phone": phone, "items": [{"name": "widget", "qty": 1, "unit_price": 100}],
            "payment_amount": 100}


def test_basic_blocks_pos_after_100_this_month():
    phone, uid, cook = _owner()  # Basic
    _seed_month_sales(phone, uid, 100)
    r = client.post("/app/api/pos/save", cookies=cook, json=_pos_payload(phone))
    assert r.status_code == 403
    assert "100 transactions" in r.json()["detail"]


def test_paid_plan_not_blocked():
    phone, uid, cook = _owner("GO")
    _seed_month_sales(phone, uid, 120)
    r = client.post("/app/api/pos/save", cookies=cook, json=_pos_payload(phone))
    assert r.status_code == 200, r.text


def test_debt_payment_exempt_from_cap():
    phone, uid, cook = _owner()  # Basic
    # A customer who owes money.
    db = SessionLocal()
    try:
        c = Customer(owner_phone=phone, name="ada", balance=5000)
        db.add(c); db.commit()
        db.add(Transaction(customer_id=c.id, type="BUY", amount=5000, recorded_by_id=uid,
                           message_id=f"b-{uuid.uuid4()}"))
        db.commit()
        cid = c.id
    finally:
        db.close()
    _seed_month_sales(phone, uid, 100)  # at the cap
    r = client.post(f"/app/api/customers/{cid}/pay", cookies=cook, json={"amount": 1000})
    assert r.status_code == 200, r.text  # collecting a debt is never blocked


def test_pos_products_reports_usage():
    phone, uid, cook = _owner()
    _seed_month_sales(phone, uid, 95)
    d = client.get("/app/api/pos/products", cookies=cook).json()
    assert d["monthly_transactions"]["limit"] == 100
    assert d["monthly_transactions"]["count"] == 95
    assert d["monthly_transactions"]["remaining"] == 5


def test_bulk_add_caps_active_products():
    phone, uid, cook = _owner()  # Basic, 5 active max
    items = [{"name": f"prod{i}", "selling_price": 500} for i in range(7)]
    r = client.post("/app/api/inventory/bulk", cookies=cook,
                    json={"owner_phone": phone, "names": [], "items": items})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["priced_blocked"] == 2  # only 5 got a price
    db = SessionLocal()
    try:
        active = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone, InventoryItem.selling_price != None).count()
        assert active == 5
    finally:
        db.close()
