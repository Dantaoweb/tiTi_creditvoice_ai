"""
Distributors / van sales (distributors.py): bread goes out with a seller in the
morning, the unsold comes back in the evening — some good, some stale — and the
seller pays for what was sold; the rest is their debt.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-distributors-00000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, InventoryItem, InventoryMovement, Transaction, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _bakery():
    phone = f"2347091{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Mama Tee Bakery", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(phone=phone).one()
        u.business_type = "bakery"; u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
        loaf = InventoryItem(owner_phone=phone, name="bread large loaf", unit="loaf", quantity=500, cost_price=900,
                             selling_price=1500, wholesale_price=1300, is_available=True)
        small = InventoryItem(owner_phone=phone, name="bread small loaf", unit="loaf", quantity=200, cost_price=400,
                              selling_price=700, is_available=True)
        seller = Customer(owner_phone=phone, name="Musa (van 1)", customer_phone="2348031234567", balance=0)
        db.add_all([loaf, small, seller]); db.commit()
        ids = {"loaf": loaf.id, "small": small.id, "seller": seller.id, "uid": u.id}
    finally:
        db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies, ids


def _stock(item_id):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).filter(InventoryItem.id == item_id).first().quantity
    finally:
        db.close()


def _balance(cid):
    db = SessionLocal()
    try:
        return db.query(Customer).filter(Customer.id == cid).first().balance
    finally:
        db.close()


def test_out_in_the_morning_back_and_settled_in_the_evening():
    phone, cook, ids = _bakery()
    r = client.post("/app/api/distributors/send-out", cookies=cook, json={
        "customer_id": ids["seller"], "lines": [{"item_id": ids["loaf"], "qty": 300}]})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "out" and run["lines"][0]["unit_price"] == 1300       # the wholesale price by default
    assert run["out_value"] == 390000 and _stock(ids["loaf"]) == 200
    # More later the same day: added to the same run, at a price set here
    run = client.post("/app/api/distributors/send-out", cookies=cook, json={
        "customer_id": ids["seller"], "lines": [{"item_id": ids["loaf"], "qty": 20},
                                                {"item_id": ids["small"], "qty": 50, "unit_price": 600}]}).json()
    assert len(client.get("/app/api/distributors", cookies=cook).json()["out"]) == 1
    lines = {l["name"]: l for l in run["lines"]}
    assert lines["Bread Large Loaf"]["out"] == 320 and _stock(ids["small"]) == 150

    # Evening: 40 large back good, 8 stale; 10 small back. Paid ₦300,000.
    sold_value = (320 - 48) * 1300 + (50 - 10) * 600          # 353,600 + 24,000 = 377,600
    r = client.post(f"/app/api/distributors/runs/{run['id']}/settle", cookies=cook, json={
        "returns": {str(lines["Bread Large Loaf"]["id"]): {"back": 40, "spoilt": 8},
                    str(lines["Bread Small Loaf"]["id"]): {"back": 10}},
        "paid": 300000, "due_date": "2054-11-06"})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "settled" and done["sold_value"] == sold_value and done["owed_now"] == sold_value - 300000
    assert _stock(ids["loaf"]) == 200 - 20 + 40 and _stock(ids["small"]) == 160      # good ones back; stale removed
    assert _balance(ids["seller"]) == sold_value - 300000                              # the rest is Musa's debt

    db = SessionLocal()
    try:
        tx = db.query(Transaction).filter(Transaction.id == done["receipt_id"]).first()
        assert tx.type == "BUY" and tx.amount == sold_value and "Van sales" in tx.product
        stale = db.query(InventoryMovement).filter(InventoryMovement.item_id == ids["loaf"],
                                                   InventoryMovement.reason == "expired").one()
        assert stale.quantity == 8
        # No sale movement: stock left in the morning, so the sale didn't take it again
        assert db.query(InventoryMovement).filter(InventoryMovement.item_id == ids["loaf"],
                                                  InventoryMovement.source_type.in_(["POS", "SALE"])).count() == 0
    finally:
        db.close()

    ov = client.get("/app/api/distributors", cookies=cook).json()
    assert ov["out"] == [] and len(ov["settled"]) == 1
    s = ov["sellers"][0]
    assert (s["taken"], s["back"], s["spoilt"], s["sold"], s["paid"]) == (370, 50, 8, 312, 300000)
    assert s["seller"]["owes"] == sold_value - 300000

    # Can't settle twice
    assert client.post(f"/app/api/distributors/runs/{run['id']}/settle", cookies=cook,
                       json={"returns": {}, "paid": 0}).status_code == 400


def test_new_seller_by_name_paid_in_full_and_everything_back():
    phone, cook, ids = _bakery()
    run = client.post("/app/api/distributors/send-out", cookies=cook, json={
        "customer_name": "Ada Kiosk", "customer_phone": "08035550000",
        "lines": [{"item_id": ids["small"], "qty": 10}]}).json()
    assert run["seller"]["name"] == "Ada Kiosk" and run["lines"][0]["unit_price"] == 700    # no wholesale: selling price
    line = run["lines"][0]["id"]
    done = client.post(f"/app/api/distributors/runs/{run['id']}/settle", cookies=cook, json={
        "returns": {str(line): {"back": 2}}, "paid": 5600}).json()
    assert done["owed_now"] == 0 and done["receipt_id"]
    # Another seller brings everything back: no sale at all
    run2 = client.post("/app/api/distributors/send-out", cookies=cook, json={
        "customer_name": "Bayo", "lines": [{"item_id": ids["small"], "qty": 5}]}).json()
    done2 = client.post(f"/app/api/distributors/runs/{run2['id']}/settle", cookies=cook, json={
        "returns": {str(run2["lines"][0]["id"]): {"back": 5}}, "paid": 0}).json()
    assert done2["sold_value"] == 0 and done2["receipt_id"] is None and _stock(ids["small"]) == 192


def test_refusals():
    phone, cook, ids = _bakery()
    url = "/app/api/distributors/send-out"
    assert "Only 500" in client.post(url, cookies=cook, json={
        "customer_id": ids["seller"], "lines": [{"item_id": ids["loaf"], "qty": 501}]}).json()["detail"]
    assert client.post(url, cookies=cook, json={"lines": [{"item_id": ids["loaf"], "qty": 1}]}).status_code == 400
    assert client.post(url, cookies=cook, json={"customer_id": ids["seller"], "lines": [
        {"item_id": ids["loaf"], "qty": 1.5}]}).status_code == 400
    run = client.post(url, cookies=cook, json={"customer_id": ids["seller"],
                                               "lines": [{"item_id": ids["loaf"], "qty": 10}]}).json()
    line = str(run["lines"][0]["id"])
    settle = f"/app/api/distributors/runs/{run['id']}/settle"
    assert "More came back" in client.post(settle, cookies=cook, json={
        "returns": {line: {"back": 8, "spoilt": 3}}, "paid": 0}).json()["detail"]
    assert "more than the goods sold" in client.post(settle, cookies=cook, json={
        "returns": {line: {"back": 5}}, "paid": 7000}).json()["detail"]
    # Another business can't touch it
    _p2, other, _i2 = _bakery()
    assert client.post(settle, cookies=other, json={"returns": {}, "paid": 0}).status_code == 400
    assert client.get("/app/api/distributors", cookies=other).json()["out"] == []
    # A cashier can't send goods out
    db = SessionLocal()
    sp = f"2347092{next(_seq):06d}"
    db.add(User(phone=sp, name="Cashier", role="delegate", parent_id=ids["uid"],
                recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE"))
    db.commit(); db.close()
    staff = client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies
    assert client.post(url, cookies=staff, json={"customer_id": ids["seller"],
                                                 "lines": [{"item_id": ids["loaf"], "qty": 1}]}).status_code == 403


def test_production_report_counts_seller_sales_and_whats_out():
    phone, cook, ids = _bakery()
    client.put(f"/app/api/production/recipe/{ids['loaf']}", cookies=cook, json={
        "yield_qty": 100, "lines": [{"item_id": ids["small"], "qty": 1}]})          # any material will do
    client.post("/app/api/production/runs", cookies=cook, json={"product_id": ids["loaf"], "made_qty": 100})
    run = client.post("/app/api/distributors/send-out", cookies=cook, json={
        "customer_id": ids["seller"], "lines": [{"item_id": ids["loaf"], "qty": 60}]}).json()
    rep = client.get("/app/api/production/report", cookies=cook).json()["products"][0]
    assert (rep["sold"], rep["with_sellers"]) == (0, 60)
    client.post(f"/app/api/distributors/runs/{run['id']}/settle", cookies=cook, json={
        "returns": {str(run["lines"][0]["id"]): {"back": 10}}, "paid": 65000})
    rep = client.get("/app/api/production/report", cookies=cook).json()["products"][0]
    assert (rep["sold"], rep["with_sellers"]) == (50, 0)


def test_titi_explains_distributors():
    from faq import FAQ_ANSWERS, detect_faq
    assert detect_faq("how do i record my distributors?") == "distributors"
    assert detect_faq("sales rep brought back unsold bread, what do i do?") == "distributors"
    assert "Settle" in FAQ_ANSWERS["distributors"]
