"""
Waybills through the web app, and who may do what: any staff who records
sales makes and prints waybills; cancelling one and keeping goods aside is
for the owner and authorised staff.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-waybills-api-000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, InventoryItem, User

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


def _shop(stock=40):
    n = next(_seq)
    phone, staff_phone = f"2348091{n:06d}", f"2348092{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Cement", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == phone).first()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        db.add(User(phone=staff_phone, name="Loader", role="delegate", parent_id=owner.id,
                    can_view_all_transactions=False, recovery_pin_hash=web_auth._hash_pin("1234"),
                    subscription_status="ACTIVE"))
        item = InventoryItem(owner_phone=phone, name="cement", unit="bag", quantity=stock,
                             selling_price=9000, cost_price=8000, is_available=True)
        cust = Customer(owner_phone=phone, name="ade", customer_phone="2348033333333", balance=0)
        db.add_all([item, cust]); db.commit()
        ids = item.id, cust.id
    finally:
        db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    staff = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "1234"}).cookies
    return phone, cook, staff, *ids


def _stock(item_id):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).get(item_id).quantity
    finally:
        db.close()


def test_short_sale_then_waybills_from_the_deliveries_page():
    phone, cook, staff, item_id, ade = _shop()
    # Staff with no branch see only their own sales, so the loader sells too
    r = client.post("/app/api/pos/save", cookies=staff, json={
        "owner_phone": phone, "customer_id": ade, "payment_amount": 0,
        "items": [{"inventory_item_id": item_id, "name": "cement", "qty": 100, "unit": "bag",
                   "unit_price": 9000, "delivered_qty": 40}]})
    assert r.status_code == 200 and _stock(item_id) == 0

    inv = client.get("/app/api/inventory", cookies=cook).json()["items"][0]
    assert (inv["waiting"], inv["reserved"]) == (60, 0)
    assert inv["waiting_customers"] == [{"name": "Ade", "quantity": 60}]

    # New stock: Ade is waiting; the owner keeps 60 aside for him
    db = SessionLocal(); db.query(InventoryItem).get(item_id).quantity = 100; db.commit(); db.close()
    w = client.get(f"/app/api/inventory/{item_id}/waiting", cookies=cook).json()
    assert w["waiting"][0]["remaining"] == 60 and w["item"]["free"] == 100
    key = w["waiting"][0]["key"]
    assert client.post("/app/api/deliveries/goods/keep", cookies=staff,
                       json={"customer_id": ade, "key": key, "kept": 60}).status_code == 403
    assert client.post("/app/api/deliveries/goods/keep", cookies=cook,
                       json={"customer_id": ade, "key": key, "kept": 60}).status_code == 200

    # A loader (ordinary staff) makes the waybill from the form
    form = client.get(f"/app/api/waybills/new?customer_id={ade}", cookies=staff).json()
    assert form["lines"][0]["max"] == 60
    r = client.post("/app/api/waybills", cookies=staff, json={
        "customer_id": ade, "lines": [{"key": key, "quantity": 30}],
        "driver_name": "Musa", "driver_phone": "08030000000", "vehicle": "KJA 123 XY",
        "loaders": "Sule, Tunde", "address": "12 Market Rd, Ibadan"})
    assert r.status_code == 200, r.text
    wb = r.json()
    assert wb["number"] == "WB-0001" and wb["sent"] and _stock(item_id) == 70
    assert sent and "KJA 123 XY" in sent[-1][1] and "30 bag Cement" in sent[-1][1]

    # Next waybill remembers the driver and the address
    form = client.get(f"/app/api/waybills/new?customer_id={ade}", cookies=cook).json()
    assert form["details"]["vehicle"] == "KJA 123 XY" and form["details"]["address"] == "12 Market Rd, Ibadan"

    # Only the owner / authorised staff cancel
    assert client.post(f"/app/api/waybills/{wb['id']}/cancel", cookies=staff,
                       json={"reason": "x"}).status_code == 403
    doc = client.get(f"/app/api/waybills/{wb['id']}", cookies=staff).json()
    assert doc["can_cancel"] is False and "unit_price" not in str(doc["lines"])
    r = client.post(f"/app/api/waybills/{wb['id']}/cancel", cookies=cook, json={"reason": "Truck broke down"})
    assert r.status_code == 200 and r.json()["cancelled_at"] and _stock(item_id) == 100

    rows = client.get("/app/api/waybills", cookies=cook).json()["waybills"]
    assert [w["number"] for w in rows] == ["WB-0001"] and rows[0]["cancelled"]


def test_receipt_waybill_and_receipt_lists_it():
    phone, cook, _staff, item_id, ade = _shop(stock=300)
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": ade, "payment_amount": 0,
        "items": [{"inventory_item_id": item_id, "name": "cement", "qty": 50, "unit": "bag", "unit_price": 9000}]})
    tx_id = r.json()["receipt_id"]
    sent.clear()                                             # the receipt itself
    form = client.get(f"/app/api/waybills/new?tx_id={tx_id}", cookies=cook).json()
    [line] = form["lines"]
    assert line["handed_over"] and form["title"].startswith("Receipt #")
    r = client.post("/app/api/waybills", cookies=cook, json={
        "tx_id": tx_id, "lines": [{"line_id": line["line_id"], "quantity": 50}], "notify": False})
    assert r.status_code == 200 and not sent and _stock(item_id) == 250
    assert [w["number"] for w in client.get(f"/app/api/waybills?tx_id={tx_id}", cookies=cook).json()["waybills"]] \
        == ["WB-0001"]


def test_another_business_cannot_see_a_waybill():
    phone, cook, _s, item_id, ade = _shop()
    _p2, cook2, _s2, _i2, _a2 = _shop()
    db = SessionLocal(); db.query(InventoryItem).get(item_id).quantity = 40; db.commit(); db.close()
    client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": ade, "payment_amount": 0,
        "items": [{"inventory_item_id": item_id, "name": "cement", "qty": 10, "unit": "bag",
                   "unit_price": 9000, "delivered_qty": 0}]})
    key = f"i:{item_id}"
    wb = client.post("/app/api/waybills", cookies=cook, json={
        "customer_id": ade, "lines": [{"key": key, "quantity": 10}]}).json()
    assert client.get(f"/app/api/waybills/{wb['id']}", cookies=cook2).status_code == 404
    assert client.post(f"/app/api/waybills/{wb['id']}/cancel", cookies=cook2,
                       json={"reason": "x"}).status_code == 404
    assert client.post("/app/api/waybills", cookies=cook2, json={
        "customer_id": ade, "lines": [{"key": key, "quantity": 1}]}).status_code == 404
