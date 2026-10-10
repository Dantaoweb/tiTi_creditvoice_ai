"""
Money owed shows until it is paid.

Buying on credit records what the business owes the supplier; paying the
supplier settles the oldest purchases first, so each purchase shows what is
still owed and drops to nothing once paid. The Dashboard shows the total owed
to suppliers to the owner and authorised staff.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-owed-until-paid-0000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348066{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _receive(cook, product, qty, cost, paid_now, supplier="Mama Joy"):
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": product, "quantity": qty, "cost_per_unit": cost,
        "supplier": supplier, "paid_now": paid_now})
    assert r.status_code == 200, r.text


def _suppliers(cook):
    return client.get("/app/api/suppliers", cookies=cook).json()


def test_nothing_paid_means_it_is_all_owed():
    _p, cook = _shop()
    _receive(cook, "rice", 10, 800, paid_now=0)                 # what the forms send for an empty box
    data = _suppliers(cook)
    assert data["suppliers"][0]["balance"] == 8000
    assert data["recent_purchases"][0]["remaining"] == 8000
    assert client.get("/app/api/dashboard", cookies=cook).json()["suppliers_owed"] == 8000


def test_paying_the_supplier_clears_the_oldest_purchase_first():
    _p, cook = _shop()
    _receive(cook, "rice", 10, 800, paid_now=0)                 # owes 8,000 (older)
    _receive(cook, "beans", 5, 1000, paid_now=2000)             # owes 3,000 (newer)
    sid = _suppliers(cook)["suppliers"][0]["id"]
    r = client.post(f"/app/api/suppliers/{sid}/pay", cookies=cook, json={"amount": 8000})
    assert r.status_code == 200, r.text

    rows = {p["product"]: p["remaining"] for p in _suppliers(cook)["recent_purchases"]}
    assert rows["rice"] == 0 and rows["beans"] == 3000
    assert client.get("/app/api/dashboard", cookies=cook).json()["suppliers_owed"] == 3000

    client.post(f"/app/api/suppliers/{sid}/pay", cookies=cook, json={"amount": 3000})
    assert all(p["remaining"] == 0 for p in _suppliers(cook)["recent_purchases"])
    assert client.get("/app/api/dashboard", cookies=cook).json()["suppliers_owed"] == 0


def test_add_stock_with_a_supplier_and_nothing_paid_is_owed():
    phone, cook = _shop()
    r = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "garri", "unit": "bag", "quantity": 4, "cost_price": 2500,
        "selling_price": 3000, "supplier": "Bola Farms", "paid_now": 0})
    assert r.status_code == 200, r.text
    assert _suppliers(cook)["suppliers"][0]["balance"] == 10000


def test_regular_staff_dont_see_what_is_owed_to_suppliers():
    owner_phone, owner = _shop()
    staff_phone = f"2348065{next(_seq):06d}"
    db = SessionLocal()
    try:
        o = db.query(User).filter(User.phone == owner_phone).first()
        o.subscription_plan = "PRO"; o.subscription_status = "ACTIVE"
        db.add(User(phone=staff_phone, name="Sade", role="delegate", parent_id=o.id,
                    can_view_all_transactions=False, recovery_pin_hash=web_auth._hash_pin("1234"),
                    subscription_status="ACTIVE"))
        db.commit()
    finally:
        db.close()
    _receive(owner, "rice", 10, 800, paid_now=0)
    staff = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "1234"}).cookies
    assert client.get("/app/api/dashboard", cookies=staff).json()["suppliers_owed"] is None


def test_purchase_remaining_helper():
    from types import SimpleNamespace as N
    from datetime import datetime
    from web_supplier_routes import purchase_remaining
    buys = [N(id=1, total=5000, paid_amount=0, created_at=datetime(2026, 1, 1)),
            N(id=2, total=4000, paid_amount=1000, created_at=datetime(2026, 2, 1))]
    pays = [N(amount=6000)]
    assert purchase_remaining(buys, pays) == {1: 0, 2: 2000}
