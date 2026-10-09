"""
A supplier on Add stock and Edit stock, like Adjust stock.

Opening stock with a supplier is a delivery: it's recorded against the
supplier, and anything not paid is owed to them. A product also remembers who
usually supplies it, which pre-fills receiving stock and reporting a fake.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-stock-supplier-00000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import InventoryItem, InventoryMovement, Supplier, SupplierPurchase

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348070{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cook


def _add(phone, cook, **extra):
    body = {"owner_phone": phone, "name": "Peak Milk", "unit": "tin", "quantity": 10,
            "cost_price": 800, "selling_price": 1000, **extra}
    r = client.post("/app/api/inventory", cookies=cook, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(item_id):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    finally:
        db.close()


def _purchases(phone):
    db = SessionLocal()
    try:
        return [(p.total, p.paid_amount, db.query(Supplier).get(p.supplier_id).name)
                for p in db.query(SupplierPurchase).filter(SupplierPurchase.owner_phone == phone).all()]
    finally:
        db.close()


def test_opening_stock_from_a_supplier_is_a_delivery_with_debt():
    phone, cook = _shop()
    iid = _add(phone, cook, supplier="Mama Joy Wholesale", paid_now=5000)
    assert _item(iid).quantity == 10
    assert _item(iid).usual_supplier == "Mama Joy Wholesale"
    total, paid, name = _purchases(phone)[0]
    assert (total, paid) == (8000, 5000) and name.lower() == "mama joy wholesale"

    db = SessionLocal()
    try:
        mv = db.query(InventoryMovement).filter(InventoryMovement.item_id == iid).one()
        assert mv.source_type == "SUPPLIER_PURCHASE" and mv.quantity == 10   # counted once
    finally:
        db.close()


def test_paid_now_left_blank_means_paid_in_full():
    phone, cook = _shop()
    _add(phone, cook, supplier="Mama Joy Wholesale")
    total, paid, _name = _purchases(phone)[0]
    assert total == paid == 8000


def test_no_supplier_works_as_before():
    phone, cook = _shop()
    iid = _add(phone, cook)
    assert _purchases(phone) == []
    assert _item(iid).usual_supplier is None
    db = SessionLocal()
    try:
        assert db.query(InventoryMovement).filter(InventoryMovement.item_id == iid).one().source_type == "WEB_ADD"
    finally:
        db.close()


def test_edit_sets_and_clears_the_usual_supplier():
    phone, cook = _shop()
    iid = _add(phone, cook)
    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"usual_supplier": "Dangote Depot"})
    assert _item(iid).usual_supplier == "Dangote Depot"
    listed = client.get("/app/api/inventory", cookies=cook).json()
    rows = listed.get("items") or listed.get("inventory") or []
    assert any(r.get("usual_supplier") == "Dangote Depot" for r in rows)
    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"usual_supplier": ""})
    assert _item(iid).usual_supplier is None


def test_receiving_stock_learns_the_usual_supplier_once():
    phone, cook = _shop()
    iid = _add(phone, cook)
    client.post("/app/api/inventory/stock-received", cookies=cook,
                json={"item_id": iid, "quantity": 5, "cost_per_unit": 800, "supplier": "Others"})
    assert _item(iid).usual_supplier is None                   # "Others" isn't a supplier
    client.post("/app/api/inventory/stock-received", cookies=cook,
                json={"item_id": iid, "quantity": 5, "cost_per_unit": 800, "supplier": "Bola Distributors"})
    assert (_item(iid).usual_supplier or "").lower() == "bola distributors"
    client.post("/app/api/inventory/stock-received", cookies=cook,
                json={"item_id": iid, "quantity": 5, "cost_per_unit": 800, "supplier": "Someone Else"})
    assert (_item(iid).usual_supplier or "").lower() == "bola distributors"   # not overwritten
