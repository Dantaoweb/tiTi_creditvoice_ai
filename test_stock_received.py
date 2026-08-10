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


def test_credit_purchase_then_pay_supplier_clears_balance():
    phone, cook = _owner()
    # Receive on credit: total 100000, paid 40000 → owe 60000.
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Cement", "quantity": 100, "cost_per_unit": 1000,
        "paid_now": 40000, "supplier": "BUA",
    })
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        sup_id = db.query(Supplier).filter(
            Supplier.owner_phone == phone, Supplier.name == "bua"
        ).first().id
    finally:
        db.close()

    # Detail shows the debt.
    d = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()
    assert d["total_bought"] == 100000 and d["total_paid"] == 40000 and d["balance"] == 60000
    assert len(d["purchases"]) == 1

    # Pay the rest.
    pr = client.post(f"/app/api/suppliers/{sup_id}/pay", cookies=cook, json={"amount": 60000})
    assert pr.status_code == 200 and pr.json()["balance"] == 0, pr.text

    d2 = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()
    assert d2["balance"] == 0 and len(d2["payments"]) == 1


def test_pay_rejects_other_owners_supplier():
    _p, cook = _owner()
    # A supplier that belongs to a different owner.
    _p2, cook2 = _owner()
    client.post("/app/api/inventory/stock-received", cookies=cook2, json={
        "product": "Sand", "quantity": 5, "supplier": "Foreign",
    })
    db = SessionLocal()
    try:
        foreign_id = db.query(Supplier).filter(Supplier.name == "foreign").first().id
    finally:
        db.close()
    r = client.post(f"/app/api/suppliers/{foreign_id}/pay", cookies=cook, json={"amount": 1000})
    assert r.status_code == 404
