"""
Poultry workflow: daily egg collection adds graded eggs to stock (production IN),
daily feed usage deducts feed (consumption OUT, not a sale), and both roll up
into daily history + the header summary.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-poultry-0000000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, InventoryItem, InventoryMovement

client = TestClient(app)
_seq = iter(range(7100, 7999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _poultry_owner():
    n = next(_seq)
    phone = f"234817{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Farmer", "phone": phone, "pin": "4321"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.business_type = "poultry_farm"
        db.commit()
    finally:
        db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "4321"}).cookies
    return phone, cook


def test_egg_collection_adds_graded_stock_and_summary():
    phone, cook = _poultry_owner()

    cfg = client.get("/app/api/poultry/config", cookies=cook).json()
    assert cfg["is_poultry"] is True
    assert any(g["key"] == "cracked" for g in cfg["grades"])

    r = client.post("/app/api/poultry/egg-collection", cookies=cook, json={
        "rows": [
            {"grade": "sorted", "crates": 12},
            {"grade": "cracked", "crates": 3},
            {"grade": "pullet", "crates": 2},
        ]
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["crates"] == 17
    assert body["summary"]["eggs_collected_today"] == 17
    assert body["summary"]["eggs_in_stock"] == 17

    # Each grade became its own product, sellable per loose egg (retail = 30).
    db = SessionLocal()
    try:
        sorted_item = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone,
            InventoryItem.name == "egg (sorted / big)",
        ).first()
        assert sorted_item is not None
        assert sorted_item.quantity == 12
        assert sorted_item.unit == "crate"
        assert sorted_item.retail_unit == "egg"
        assert sorted_item.retail_per_base == 30
    finally:
        db.close()


def test_feed_usage_deducts_stock_without_a_sale():
    phone, cook = _poultry_owner()

    # Buy feed first (stock IN via supplier purchase).
    client.post("/app/api/inventory/stock-received", cookies=cook,
                json={"product": "layer mash", "quantity": 10, "cost_per_unit": 9000})
    cfg = client.get("/app/api/poultry/config", cookies=cook).json()
    feeds = cfg["feeds"]
    assert len(feeds) == 1 and feeds[0]["name"] == "layer mash"
    feed_id = feeds[0]["id"]

    r = client.post("/app/api/poultry/feed-usage", cookies=cook, json={
        "rows": [{"item_id": feed_id, "quantity": 3}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 3
    assert r.json()["summary"]["feed_used_today"] == 3
    assert r.json()["summary"]["feed_in_stock"] == 7  # 10 bought - 3 used

    # The usage is a CONSUMPTION movement, not a sale (no transaction created).
    db = SessionLocal()
    try:
        mv = db.query(InventoryMovement).filter(
            InventoryMovement.owner_phone == phone,
            InventoryMovement.source_type == "FEED_USE",
        ).one()
        assert mv.movement_type == "OUT"
        assert mv.quantity == 3
    finally:
        db.close()


def test_history_groups_by_day():
    phone, cook = _poultry_owner()
    client.post("/app/api/poultry/egg-collection", cookies=cook,
                json={"rows": [{"grade": "sorted", "crates": 5}]})
    client.post("/app/api/poultry/egg-collection", cookies=cook,
                json={"rows": [{"grade": "small", "crates": 4}]})
    hist = client.get("/app/api/poultry/egg-history", cookies=cook).json()["days"]
    assert len(hist) == 1              # both today → one day row
    assert hist[0]["total"] == 9
