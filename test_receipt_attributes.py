"""
Custom stock fields (car dealer: chassis/engine/colour) are snapshotted onto the
sale line and appear, labelled, on the web receipt.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-receipt-attrs-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _dealer(phone):
    client.post("/app/api/auth/register", json={"name": "Cars", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.business_type = "car_dealer"
    db.commit(); db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_car_attributes_on_receipt():
    phone = "2348200000010"
    cook = _dealer(phone)

    add = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone,
        "name": "toyota corolla",
        "selling_price": 4500000,
        "quantity": 1,
        "attributes": {
            "maker": "Toyota", "model": "Corolla", "year": "2015",
            "color": "Black", "chassis_no": "CHS-ABC-123", "engine_no": "ENG-999",
        },
    })
    assert add.status_code == 200, add.text
    item_id = add.json()["id"]

    sale = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone,
        "items": [{"inventory_item_id": item_id, "name": "toyota corolla",
                   "qty": 1, "unit_price": 4500000}],
        "payment_amount": 4500000,
    })
    assert sale.status_code == 200, sale.text
    rid = sale.json()["receipt_id"]

    receipt = client.get(f"/app/api/pos/receipt/{rid}", cookies=cook).json()
    attrs = receipt["items"][0]["attributes"]
    kv = {a["label"]: a["value"] for a in attrs}
    assert kv.get("Chassis number") == "CHS-ABC-123"
    assert kv.get("Engine number") == "ENG-999"
    assert kv.get("Colour") == "Black"
    assert kv.get("Maker / Make") == "Toyota"
    # Ordered per template: maker first, chassis before engine.
    labels = [a["label"] for a in attrs]
    assert labels.index("Maker / Make") < labels.index("Chassis number") < labels.index("Engine number")


def test_non_dealer_receipt_has_no_attributes():
    phone = "2348200000020"
    client.post("/app/api/auth/register", json={"name": "Shop", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    add = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "rice", "selling_price": 5000, "quantity": 10,
    })
    item_id = add.json()["id"]
    sale = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone,
        "items": [{"inventory_item_id": item_id, "name": "rice", "qty": 1, "unit_price": 5000}],
        "payment_amount": 5000,
    })
    rid = sale.json()["receipt_id"]
    receipt = client.get(f"/app/api/pos/receipt/{rid}", cookies=cook).json()
    assert receipt["items"][0]["attributes"] == []
