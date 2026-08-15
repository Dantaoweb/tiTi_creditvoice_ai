"""
Editing a product's selling or cost price is logged as an audit trail
(old -> new, when, who) so price changes can be tracked over time, and the
per-item price-history endpoint surfaces it for the item detail modal.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-price-history-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(7100, 7999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234815{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cook


def _make_item(phone, sell, cost):
    db = SessionLocal()
    try:
        it = InventoryItem(owner_phone=phone, name="rice", unit="bag",
                           quantity=10, selling_price=sell, cost_price=cost)
        db.add(it); db.commit()
        return it.id
    finally:
        db.close()


def test_selling_price_edit_is_logged_and_returned():
    phone, cook = _owner()
    iid = _make_item(phone, 1000, 600)

    r = client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"selling_price": 1200})
    assert r.status_code == 200, r.text

    r = client.get(f"/app/api/inventory/{iid}/price-history", cookies=cook)
    assert r.status_code == 200, r.text
    changes = r.json()["changes"]
    assert len(changes) == 1
    assert changes[0]["field"] == "selling_price"
    assert changes[0]["old_price"] == 1000
    assert changes[0]["new_price"] == 1200
    assert changes[0]["changed_by"] == "Owner"


def test_cost_price_edit_is_logged():
    phone, cook = _owner()
    iid = _make_item(phone, 1000, 600)

    r = client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"cost_price": 750})
    assert r.status_code == 200, r.text

    changes = client.get(f"/app/api/inventory/{iid}/price-history", cookies=cook).json()["changes"]
    assert len(changes) == 1
    assert changes[0]["field"] == "cost_price"
    assert changes[0]["old_price"] == 600
    assert changes[0]["new_price"] == 750


def test_no_log_when_price_unchanged():
    phone, cook = _owner()
    iid = _make_item(phone, 1000, 600)

    # Same price + a name change: nothing to log.
    r = client.put(f"/app/api/inventory/{iid}", cookies=cook,
                   json={"selling_price": 1000, "name": "Rice"})
    assert r.status_code == 200, r.text

    changes = client.get(f"/app/api/inventory/{iid}/price-history", cookies=cook).json()["changes"]
    assert changes == []


def test_changes_are_newest_first():
    phone, cook = _owner()
    iid = _make_item(phone, 1000, 600)

    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"selling_price": 1100})
    client.put(f"/app/api/inventory/{iid}", cookies=cook, json={"selling_price": 1300})

    changes = client.get(f"/app/api/inventory/{iid}/price-history", cookies=cook).json()["changes"]
    assert len(changes) == 2
    # Newest first: 1100 -> 1300 is the latest.
    assert changes[0]["old_price"] == 1100 and changes[0]["new_price"] == 1300
    assert changes[1]["old_price"] == 1000 and changes[1]["new_price"] == 1100
