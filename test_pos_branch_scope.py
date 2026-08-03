"""
POS is branch-gated: the product list shows only the selling branch's stock, and
a sale cannot include an item that belongs to another branch.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pos-branch-0000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, InventoryItem, Branch

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(9000, 9999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _premium_owner():
    n = next(_seq)
    phone = f"234855{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _stock(owner_phone, name, branch_id):
    db = SessionLocal()
    try:
        it = InventoryItem(owner_phone=owner_phone, name=name, selling_price=1000,
                           quantity=10, is_available=True, branch_id=branch_id)
        db.add(it); db.commit(); db.refresh(it)
        return it.id
    finally:
        db.close()


def _two_branches(cook):
    a = client.post("/app/api/branches", cookies=cook, json={"name": "Ikeja"}).json()
    b = client.post("/app/api/branches", cookies=cook, json={"name": "Lekki"}).json()
    return a["id"], b["id"]


def test_products_scoped_to_selected_branch():
    phone, cook = _premium_owner()
    a_id, b_id = _two_branches(cook)
    _stock(phone, "ikeja rice", a_id)
    _stock(phone, "lekki beans", b_id)

    a_products = client.get("/app/api/pos/products", cookies=cook,
                            params={"owner_phone": phone, "branch_id": a_id}).json()["products"]
    names_a = {p["name"] for p in a_products}
    assert "ikeja rice" in names_a and "lekki beans" not in names_a

    b_products = client.get("/app/api/pos/products", cookies=cook,
                            params={"owner_phone": phone, "branch_id": b_id}).json()["products"]
    names_b = {p["name"] for p in b_products}
    assert "lekki beans" in names_b and "ikeja rice" not in names_b


def test_cannot_sell_other_branch_item():
    phone, cook = _premium_owner()
    a_id, b_id = _two_branches(cook)
    lekki_item = _stock(phone, "lekki beans", b_id)
    # Try to sell the Lekki item while selling from Ikeja -> rejected.
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone,
        "branch_id": a_id,
        "items": [{"inventory_item_id": lekki_item, "name": "lekki beans",
                   "qty": 1, "unit_price": 1000}],
        "payment_amount": 1000,
    })
    assert r.status_code == 400
    assert "another branch" in r.json()["detail"].lower()


def test_can_sell_own_branch_item():
    phone, cook = _premium_owner()
    a_id, _b_id = _two_branches(cook)
    ikeja_item = _stock(phone, "ikeja rice", a_id)
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone,
        "branch_id": a_id,
        "items": [{"inventory_item_id": ikeja_item, "name": "ikeja rice",
                   "qty": 1, "unit_price": 1000}],
        "payment_amount": 1000,
    })
    assert r.status_code == 200, r.text


def test_single_location_unaffected():
    # No branches: all stock is sellable (branch filter is a no-op).
    phone, cook = _premium_owner()
    _stock(phone, "plain rice", None)
    products = client.get("/app/api/pos/products", cookies=cook,
                          params={"owner_phone": phone}).json()["products"]
    assert any(p["name"] == "plain rice" for p in products)
    item_id = next(p["id"] for p in products if p["name"] == "plain rice")
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone,
        "items": [{"inventory_item_id": item_id, "name": "plain rice",
                   "qty": 1, "unit_price": 1000}],
        "payment_amount": 1000,
    })
    assert r.status_code == 200, r.text
