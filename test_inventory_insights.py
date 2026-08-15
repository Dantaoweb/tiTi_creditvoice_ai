"""
The Inventory Insights report rolls up, over a period: (A) a margin snapshot
(current cost vs selling price), (B) the price-change log, and (C) stock
received with cost trend + total spend.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-insights-00000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(6100, 6999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234816{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cook


def _item_id(phone, name):
    db = SessionLocal()
    try:
        it = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone, InventoryItem.name == name.lower()
        ).first()
        return it.id if it else None
    finally:
        db.close()


def test_insights_rolls_up_margin_price_changes_and_stock():
    phone, cook = _owner()

    # Two stock-ins at rising cost.
    client.post("/app/api/inventory/stock-received", cookies=cook,
                json={"product": "Rice", "quantity": 50, "cost_per_unit": 800})
    client.post("/app/api/inventory/stock-received", cookies=cook,
                json={"product": "Rice", "quantity": 30, "cost_per_unit": 900})
    iid = _item_id(phone, "rice")

    # Set then raise the selling price (two logged changes).
    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"selling_price": 1000})
    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"selling_price": 1100})

    r = client.get("/app/api/reports/inventory-insights", cookies=cook)
    assert r.status_code == 200, r.text
    d = r.json()

    # C. Stock received: 80 units, spend 50*800 + 30*900 = 67,000, cost trend up.
    assert d["purchasing_spend"] == 67000
    assert len(d["stock_received"]) == 1
    sr = d["stock_received"][0]
    assert sr["qty"] == 80
    assert sr["spent"] == 67000
    assert sr["trend"] == "up"

    # B. Price changes: two selling-price edits, latest is an increase.
    assert d["price_edits"] == 2
    assert d["price_up"] == 1  # 1000 -> 1100 counts; None -> 1000 does not
    assert d["price_changes"][0]["new_price"] == 1100

    # A. Margin snapshot: cost 900 (latest IN), selling 1100 -> margin 200 (18%).
    assert len(d["margin"]) == 1
    m = d["margin"][0]
    assert m["cost_price"] == 900
    assert m["selling_price"] == 1100
    assert m["margin"] == 200
    assert m["margin_pct"] == 18
    assert m["flag"] is None


def test_margin_flags_loss_and_no_cost():
    phone, cook = _owner()
    db = SessionLocal()
    try:
        db.add(InventoryItem(owner_phone=phone, name="sugar", quantity=5,
                             cost_price=500, selling_price=480))   # loss
        db.add(InventoryItem(owner_phone=phone, name="salt", quantity=5,
                             cost_price=None, selling_price=200))  # no cost
        db.commit()
    finally:
        db.close()

    d = client.get("/app/api/reports/inventory-insights", cookies=cook).json()
    flags = {m["name"]: m["flag"] for m in d["margin"]}
    assert flags["sugar"] == "loss"
    assert flags["salt"] == "no_cost"
    # Worst-first ordering: the loss surfaces before the no-cost row.
    names = [m["name"] for m in d["margin"]]
    assert names.index("sugar") < names.index("salt")
