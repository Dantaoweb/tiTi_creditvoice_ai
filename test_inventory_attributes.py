"""
Per-business custom stock fields (e.g. car dealers: maker/model/year/colour/
chassis/engine) stored on InventoryItem.attributes_json.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-inv-attrs-00000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(8000, 9000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(business_type=None):
    n = next(_seq)
    phone = f"234844{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    if business_type:
        db = SessionLocal()
        u = db.query(User).filter(User.phone == phone).first()
        u.business_type = business_type
        db.commit(); db.close()
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def test_car_dealer_fields_listed():
    _p, cook = _owner("car_dealer")
    d = client.get("/app/api/inventory/fields", cookies=cook).json()
    keys = [f["key"] for f in d["fields"]]
    assert keys == ["maker", "model", "year", "color", "chassis_no", "engine_no"]


def test_non_dealer_has_no_fields():
    _p, cook = _owner()  # generic business
    d = client.get("/app/api/inventory/fields", cookies=cook).json()
    assert d["fields"] == []


def test_add_stock_with_attributes_roundtrips():
    phone, cook = _owner("car_dealer")
    r = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone,
        "name": "Toyota Camry",
        "selling_price": 8500000,
        "quantity": 1,
        "attributes": {
            "maker": "Toyota", "model": "Camry", "year": "2015",
            "color": "Black", "chassis_no": "JT123456", "engine_no": "2AR-FE-9988",
            "junk": "should be dropped",
        },
    })
    assert r.status_code == 200, r.text
    items = client.get("/app/api/inventory", cookies=cook,
                       params={"owner_phone": phone}).json()["items"]
    car = next(i for i in items if i["name"] == "toyota camry")
    a = car["attributes"]
    assert a["maker"] == "Toyota" and a["model"] == "Camry" and a["year"] == "2015"
    assert a["chassis_no"] == "JT123456" and a["engine_no"] == "2AR-FE-9988"
    assert "junk" not in a  # unknown keys stripped


def test_non_dealer_attributes_are_stripped():
    phone, cook = _owner()  # no fields defined
    r = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "rice", "selling_price": 5000,
        "attributes": {"maker": "nope"},
    })
    assert r.status_code == 200, r.text
    items = client.get("/app/api/inventory", cookies=cook,
                       params={"owner_phone": phone}).json()["items"]
    item = next(i for i in items if i["name"] == "rice")
    assert item["attributes"] == {}


def test_edit_updates_attributes():
    phone, cook = _owner("car_dealer")
    add = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "Honda Accord", "selling_price": 6000000,
        "attributes": {"maker": "Honda", "year": "2012"},
    }).json()
    r = client.put(f"/app/api/inventory/{add['id']}", cookies=cook, json={
        "attributes": {"maker": "Honda", "model": "Accord", "year": "2013", "color": "Silver"},
    })
    assert r.status_code == 200, r.text
    items = client.get("/app/api/inventory", cookies=cook,
                       params={"owner_phone": phone}).json()["items"]
    car = next(i for i in items if i["name"] == "honda accord")
    assert car["attributes"]["model"] == "Accord" and car["attributes"]["year"] == "2013"
    assert car["attributes"]["color"] == "Silver"
