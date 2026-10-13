"""
Part delivery through the web app: the till, the Deliveries page, the
customer page and the Inventory page all tell the same story.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-deliveries-0000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
sent = []


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sent.clear()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda to, m, *a, **k: sent.append((to, m)) or True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348089{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Cement", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        item = InventoryItem(owner_phone=phone, name="cement", unit="bag", quantity=300,
                             selling_price=9000, cost_price=8000, is_available=True)
        cust = Customer(owner_phone=phone, name="ade", customer_phone="2348032222222", balance=0)
        db.add_all([item, cust]); db.commit()
        return phone, cook, item.id, cust.id
    finally:
        db.close()


def _sell(phone, cook, item_id, qty, delivered=None, customer_id=None):
    line = {"inventory_item_id": item_id, "name": "cement", "qty": qty, "unit": "bag", "unit_price": 9000}
    if delivered is not None:
        line["delivered_qty"] = delivered
    return client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": customer_id, "items": [line], "payment_amount": 0,
    })


def test_sell_part_deliver_then_deliver_the_rest():
    phone, cook, item_id, ade = _shop()
    assert _sell(phone, cook, item_id, 100, delivered=60, customer_id=ade).status_code == 200
    assert _sell(phone, cook, item_id, 35, delivered=0, customer_id=ade).status_code == 200

    inv = client.get("/app/api/inventory", cookies=cook).json()["items"][0]
    assert (inv["quantity"], inv["reserved"]) == (240, 75)

    [g] = client.get("/app/api/deliveries", cookies=cook).json()["goods"]
    assert (g["customer"], g["product"], g["remaining"]) == ("Ade", "Cement", 75)
    assert client.get(f"/app/api/customers/{ade}/history", cookies=cook).json()["goods_to_deliver"][0]["remaining"] == 75

    # Selling Ade's bags to someone else is refused, in words
    r = _sell(phone, cook, item_id, 200)
    assert r.status_code == 400 and "165" in r.json()["detail"] and "reserved" in r.json()["detail"]

    r = client.post("/app/api/deliveries/goods", cookies=cook, json={
        "customer_id": ade, "key": g["key"], "quantity": 25, "note": "Truck KJA 123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] and body["remaining"] == 50
    assert sent and sent[-1][0] == "2348032222222" and "Still to deliver: 50 bag" in sent[-1][1]

    r = client.post("/app/api/deliveries/goods", cookies=cook, json={
        "customer_id": ade, "key": g["key"], "quantity": 51})
    assert r.status_code == 400 and "Only 50" in r.json()["detail"]

    inv = client.get("/app/api/inventory", cookies=cook).json()["items"][0]
    assert (inv["quantity"], inv["reserved"]) == (215, 50)


def test_goods_left_behind_need_a_customer():
    phone, cook, item_id, _ade = _shop()
    r = _sell(phone, cook, item_id, 10, delivered=4)
    assert r.status_code == 400 and "Pick the customer" in r.json()["detail"]


def test_another_business_cant_deliver_my_customers_goods():
    phone, cook, item_id, ade = _shop()
    _sell(phone, cook, item_id, 10, delivered=0, customer_id=ade)
    [g] = client.get("/app/api/deliveries", cookies=cook).json()["goods"]
    _p2, cook2, _i2, _c2 = _shop()
    r = client.post("/app/api/deliveries/goods", cookies=cook2, json={
        "customer_id": ade, "key": g["key"], "quantity": 1})
    assert r.status_code == 404
