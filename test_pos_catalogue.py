"""
POS catalogue: loaded once for on-phone search, flagged `truncated` when the
business has more priced products than the preload, with a server `q` search
fallback so products past the preload stay sellable.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pos-catalogue-00000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import InventoryItem

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
    phone = f"234848{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _seed(phone, names):
    db = SessionLocal()
    for n in names:
        db.add(InventoryItem(owner_phone=phone, name=n, quantity=5, selling_price=100, is_available=True))
    db.commit(); db.close()


def _get(cook, **params):
    r = client.get("/app/api/pos/products", cookies=cook, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_small_catalogue_not_truncated():
    phone, cook = _owner()
    _seed(phone, ["garri", "rice", "zobo"])
    d = _get(cook)
    assert d["total"] == 3 and d["truncated"] is False and len(d["products"]) == 3


def test_truncated_flag_and_server_search_reaches_past_preload():
    phone, cook = _owner()
    _seed(phone, [f"item {i:02d}" for i in range(10)] + ["zobo drink"])
    d = _get(cook, limit=5)   # simulate a catalogue bigger than the preload
    assert d["total"] == 11 and d["truncated"] is True and len(d["products"]) == 5
    assert "zobo drink" not in [p["name"] for p in d["products"]]
    found = _get(cook, q="ZOBO", limit=50)["products"]
    assert [p["name"] for p in found] == ["zobo drink"]


def test_search_treats_wildcards_literally():
    phone, cook = _owner()
    _seed(phone, ["rice"])
    assert _get(cook, q="%")["products"] == []


def test_limit_capped_at_preload_max():
    _p, cook = _owner()
    r = client.get("/app/api/pos/products", cookies=cook, params={"limit": 100000})
    assert r.status_code == 422
