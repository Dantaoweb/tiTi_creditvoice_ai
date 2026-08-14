"""
Wholesale (quantity-break) pricing: an item can carry an optional wholesale_price
+ wholesale_min_qty on the base unit. Purely additive — items without them behave
exactly as before. (The retail-vs-wholesale price selection at the till is
front-end logic; here we verify the fields save, return, and clear.)
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-wholesale-00000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(8000, 8999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234855522{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_wholesale_fields_saved_and_returned():
    phone, cook = _owner()
    r = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "coke", "unit": "bottle", "quantity": 100,
        "selling_price": 200, "wholesale_price": 180, "wholesale_min_qty": 12})
    assert r.status_code == 200, r.text
    iid = r.json()["id"]

    items = client.get("/app/api/inventory", params={"owner_phone": phone}, cookies=cook).json()["items"]
    it = next(x for x in items if x["id"] == iid)
    assert it["wholesale_price"] == 180 and it["wholesale_min_qty"] == 12

    prods = client.get("/app/api/pos/products", cookies=cook).json()["products"]
    p = next(x for x in prods if x["id"] == iid)
    assert p["wholesale_price"] == 180 and p["wholesale_min_qty"] == 12


def test_wholesale_optional_and_clearable():
    phone, cook = _owner()
    # No wholesale → nulls, behaves as before.
    iid = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "fanta", "unit": "bottle", "quantity": 50,
        "selling_price": 200}).json()["id"]
    items = client.get("/app/api/inventory", params={"owner_phone": phone}, cookies=cook).json()["items"]
    it = next(x for x in items if x["id"] == iid)
    assert it["wholesale_price"] is None and it["wholesale_min_qty"] is None

    # Add then clear (0 → None) via edit.
    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"wholesale_price": 180, "wholesale_min_qty": 12})
    db = SessionLocal()
    try:
        item = db.query(InventoryItem).filter(InventoryItem.id == iid).first()
        assert item.wholesale_price == 180 and item.wholesale_min_qty == 12
    finally:
        db.close()

    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"wholesale_price": 0, "wholesale_min_qty": 0})
    db = SessionLocal()
    try:
        item = db.query(InventoryItem).filter(InventoryItem.id == iid).first()
        assert item.wholesale_price is None and item.wholesale_min_qty is None
    finally:
        db.close()
