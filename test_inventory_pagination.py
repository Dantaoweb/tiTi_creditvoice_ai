"""
Inventory list must reach the WHOLE catalogue: the old endpoint returned only
the 200 most-recently-updated items, so item #201 silently hid the oldest one
(looked "deleted", and Quick Record offered to re-create it as new stock).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-inv-paging-000000000000000")

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import InventoryItem, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    phone = f"234845{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _seed(phone, n):
    """n items; item 0 is the OLDEST (least recently updated)."""
    db = SessionLocal()
    now = utcnow()
    for i in range(n):
        db.add(InventoryItem(owner_phone=phone, name=f"product {i:03d}", quantity=10,
                             selling_price=100 + i, is_available=True,
                             updated_at=now - timedelta(minutes=n - i)))
    db.commit(); db.close()


def _get(cook, **params):
    r = client.get("/app/api/inventory", cookies=cook, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_item_reachable_past_200():
    _p, cook = _owner()
    _seed(_p, 230)
    seen, offset = [], 0
    while True:
        d = _get(cook, limit=100, offset=offset)
        assert d["total"] == 230
        seen += [i["name"] for i in d["items"]]
        if not d["has_more"]:
            break
        offset += len(d["items"])
    assert len(seen) == 230 and len(set(seen)) == 230
    assert "product 000" in seen  # the oldest one used to vanish


def test_search_finds_old_item_beyond_first_page():
    _p, cook = _owner()
    _seed(_p, 230)
    d = _get(cook, q="product 000")
    assert [i["name"] for i in d["items"]] == ["product 000"]


def test_search_ranks_exact_match_first():
    phone, cook = _owner()
    db = SessionLocal()
    for name in ["fried rice", "rice bran", "rice"]:
        db.add(InventoryItem(owner_phone=phone, name=name, quantity=1, is_available=True))
    db.commit(); db.close()
    names = [i["name"] for i in _get(cook, q="Rice", limit=2)["items"]]
    assert names == ["rice", "rice bran"]


def test_search_treats_wildcards_literally():
    phone, cook = _owner()
    db = SessionLocal()
    db.add(InventoryItem(owner_phone=phone, name="soap", quantity=1, is_available=True))
    db.commit(); db.close()
    assert _get(cook, q="%")["total"] == 0


def test_low_filter_and_summary():
    phone, cook = _owner()
    db = SessionLocal()
    db.add(InventoryItem(owner_phone=phone, name="low one", quantity=2, low_stock_alert=5,
                         selling_price=100, is_available=True))
    db.add(InventoryItem(owner_phone=phone, name="fine one", quantity=50, low_stock_alert=5,
                         is_available=True))
    db.add(InventoryItem(owner_phone=phone, name="haircut", quantity=None, category="service",
                         low_stock_alert=5, selling_price=500, is_available=True))
    db.commit(); db.close()
    assert [i["name"] for i in _get(cook, low="true")["items"]] == ["low one"]
    s = client.get("/app/api/inventory/summary", cookies=cook).json()
    assert s == {"total": 3, "low_stock": 1, "active": 2}


def test_sort_by_name():
    _p, cook = _owner()
    _seed(_p, 5)
    names = [i["name"] for i in _get(cook, sort="name", dir="asc")["items"]]
    assert names == sorted(names)
