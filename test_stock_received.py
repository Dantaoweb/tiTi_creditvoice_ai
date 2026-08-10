"""
Stock Received (Quick Form) records BOTH a physical stock increase AND a
SupplierPurchase against a supplier (defaulting to "Others"), for new and
existing products.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-stock-received-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, InventoryItem, Supplier, SupplierPurchase

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(9000, 9999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234814{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _item_qty(phone, name):
    db = SessionLocal()
    try:
        it = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone, InventoryItem.name == name.lower()
        ).first()
        return it.quantity if it else None
    finally:
        db.close()


def _supplier_and_purchases(phone, supplier_name):
    db = SessionLocal()
    try:
        sup = db.query(Supplier).filter(
            Supplier.owner_phone == phone, Supplier.name == supplier_name.lower()
        ).first()
        if not sup:
            return None, 0
        n = db.query(SupplierPurchase).filter(SupplierPurchase.supplier_id == sup.id).count()
        return sup, n
    finally:
        db.close()


def test_stock_received_new_product_creates_item_supplier_and_purchase():
    phone, cook = _owner()
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Cocoa", "quantity": 50, "cost_per_unit": 1000, "supplier": "Dangote",
    })
    assert r.status_code == 200, r.text
    assert r.json()["new_quantity"] == 50
    assert _item_qty(phone, "cocoa") == 50
    sup, n = _supplier_and_purchases(phone, "dangote")
    assert sup is not None and n == 1


def test_stock_received_existing_product_adds_quantity():
    phone, cook = _owner()
    # Create an existing priced product with opening stock 10.
    client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "Rice", "quantity": 10, "selling_price": 5000,
    })
    db = SessionLocal()
    try:
        item_id = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone, InventoryItem.name == "rice"
        ).first().id
    finally:
        db.close()

    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "item_id": item_id, "quantity": 15, "cost_per_unit": 4000, "supplier": "Ayo",
    })
    assert r.status_code == 200, r.text
    assert _item_qty(phone, "rice") == 25  # 10 + 15
    sup, n = _supplier_and_purchases(phone, "ayo")
    assert sup is not None and n == 1


def test_stock_received_defaults_supplier_to_others():
    phone, cook = _owner()
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Beans", "quantity": 20,
    })
    assert r.status_code == 200, r.text
    assert r.json()["supplier"] == "Others"
    assert _item_qty(phone, "beans") == 20
    sup, n = _supplier_and_purchases(phone, "others")
    assert sup is not None and n == 1


def test_stock_received_rejects_zero_quantity():
    _p, cook = _owner()
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Milk", "quantity": 0,
    })
    assert r.status_code == 400
