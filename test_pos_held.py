"""
Held sales at the till (pos_held.py): hold a cart, serve the next customer,
open it again, change it, save it as a sale. Holding moves no stock; saving
removes the held cart. A cashier sees their own; the owner sees everyone's.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pos-held-00000000000000")

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer, HeldSale, InventoryItem, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 9999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    phone = f"234877{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Block Depot", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _staff(owner_phone, name="Sade", see_all=False, branch_id=None):
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    sp = f"234878{next(_seq):06d}"
    db.add(User(phone=sp, name=name, role="delegate", parent_id=owner.id, can_view_all_transactions=see_all,
                branch_id=branch_id, recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE"))
    db.commit(); db.close()
    return client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies


def _cement(owner_phone, qty=50):
    db = SessionLocal()
    try:
        it = InventoryItem(owner_phone=owner_phone, name="cement", unit="bag", selling_price=9000,
                           quantity=qty, is_available=True)
        db.add(it); db.commit()
        return it.id
    finally:
        db.close()


def _stock(item_id):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).filter(InventoryItem.id == item_id).first().quantity
    finally:
        db.close()


def _line(item_id, qty):
    return {"inventory_item_id": item_id, "name": "cement", "qty": qty, "unit": "bag",
            "unit_price": 9000, "base_price": 9000, "priceEdited": False, "junk": {"x": 1}}


def test_hold_open_change_and_save():
    phone, cook = _owner()
    cid = _cement(phone)
    r = client.post("/app/api/pos/held", cookies=cook, json={
        "items": [_line(cid, 10)], "discount": {"input": "1,000", "pct": False},
        "customer_name": "Engr Musa", "customer_phone": "08031112222", "total": 89000})
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["customer"]["name"] == "Engr Musa" and h["total"] == 89000
    assert h["discount"] == {"input": "1000", "pct": False}
    assert "junk" not in h["items"][0]                       # only till fields are kept
    assert _stock(cid) == 50                                  # holding moves no stock

    # A second customer is served while the first is held
    client.post("/app/api/pos/held", cookies=cook, json={"items": [_line(cid, 2)], "total": 18000})
    held = client.get("/app/api/pos/held", cookies=cook).json()["held"]
    assert [x["total"] for x in held] == [89000, 18000]       # oldest first

    # Open the first, change it, hold it again: the same held sale, updated
    r = client.post("/app/api/pos/held", cookies=cook, json={
        "id": h["id"], "items": [_line(cid, 12)], "customer_name": "Engr Musa", "total": 108000})
    assert r.json()["id"] == h["id"] and r.json()["items"][0]["qty"] == 12
    assert len(client.get("/app/api/pos/held", cookies=cook).json()["held"]) == 2

    # Save it: a real sale, stock goes, the held sale is gone
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "items": [_line(cid, 12)], "payment_amount": 108000, "held_id": h["id"]})
    assert r.status_code == 200, r.text
    assert _stock(cid) == 38
    left = client.get("/app/api/pos/held", cookies=cook).json()["held"]
    assert [x["total"] for x in left] == [18000]


def test_delete_and_empty_cart():
    phone, cook = _owner()
    cid = _cement(phone)
    assert client.post("/app/api/pos/held", cookies=cook, json={"items": [], "total": 0}).status_code == 400
    h = client.post("/app/api/pos/held", cookies=cook, json={"items": [_line(cid, 1)], "total": 9000}).json()
    assert client.delete(f"/app/api/pos/held/{h['id']}", cookies=cook).json() == {"ok": True}
    assert client.get("/app/api/pos/held", cookies=cook).json()["held"] == []
    assert client.delete(f"/app/api/pos/held/{h['id']}", cookies=cook).status_code == 404


def test_cashier_sees_own_owner_sees_all():
    phone, owner = _owner()
    cid = _cement(phone)
    shop = client.post("/app/api/branches", cookies=owner, json={"name": "Ikeja yard"}).json()["id"]
    sade = _staff(phone, "Sade", branch_id=shop)
    tunde = _staff(phone, "Tunde", branch_id=shop)
    boss = _staff(phone, "Manager", see_all=True, branch_id=shop)    # branch admin: the whole branch
    client.post("/app/api/pos/held", cookies=sade, json={"items": [_line(cid, 1)], "total": 9000})
    t = client.post("/app/api/pos/held", cookies=tunde, json={"items": [_line(cid, 3)], "total": 27000}).json()

    assert [x["total"] for x in client.get("/app/api/pos/held", cookies=sade).json()["held"]] == [9000]
    assert len(client.get("/app/api/pos/held", cookies=owner).json()["held"]) == 2
    assert len(client.get("/app/api/pos/held", cookies=boss).json()["held"]) == 2
    assert client.get("/app/api/pos/held", cookies=owner).json()["held"][1]["by"] == "Tunde"

    # Sade can't open, change or delete Tunde's held sale
    assert client.delete(f"/app/api/pos/held/{t['id']}", cookies=sade).status_code == 404
    assert client.post("/app/api/pos/held", cookies=sade, json={
        "id": t["id"], "items": [_line(cid, 1)], "total": 9000}).status_code == 400
    # …nor drop it by passing its id when she saves her own sale
    client.post("/app/api/pos/save", cookies=sade, json={
        "owner_phone": phone, "items": [_line(cid, 1)], "payment_amount": 9000, "held_id": t["id"]})
    assert len(client.get("/app/api/pos/held", cookies=owner).json()["held"]) == 1 + 1


def test_other_business_cannot_see_or_use():
    a_phone, a = _owner()
    _b_phone, b = _owner()
    cid = _cement(a_phone)
    h = client.post("/app/api/pos/held", cookies=a, json={"items": [_line(cid, 1)], "total": 9000}).json()
    assert client.get("/app/api/pos/held", cookies=b).json()["held"] == []
    assert client.delete(f"/app/api/pos/held/{h['id']}", cookies=b).status_code == 404
    db = SessionLocal()
    other = Customer(owner_phone=a_phone, name="Ada")
    db.add(other); db.commit(); oid = other.id; db.close()
    assert client.post("/app/api/pos/held", cookies=b, json={
        "items": [{"name": "x", "qty": 1, "unit_price": 5}], "customer_id": oid, "total": 5}).status_code == 400


def test_short_stock_and_stale_flags():
    phone, cook = _owner()
    cid = _cement(phone, qty=5)
    h = client.post("/app/api/pos/held", cookies=cook, json={"items": [_line(cid, 8)], "total": 72000}).json()
    assert h["short"] == [{"name": "cement", "free": 5, "removed": False}]
    assert h["stale"] is False
    db = SessionLocal()
    row = db.query(HeldSale).filter(HeldSale.id == h["id"]).first()
    row.created_at = row.created_at - timedelta(days=8)
    db.query(InventoryItem).filter(InventoryItem.id == cid).first().is_available = False
    db.commit(); db.close()
    again = client.get("/app/api/pos/held", cookies=cook).json()["held"][0]
    assert again["stale"] is True
    assert again["short"] == [{"name": "cement", "free": 0, "removed": True}]


def test_existing_customer_comes_back_fresh():
    phone, cook = _owner()
    cid = _cement(phone)
    db = SessionLocal()
    c = Customer(owner_phone=phone, name="Bello Builders", customer_phone="2348030000000", balance=5000)
    db.add(c); db.commit(); c_id = c.id; db.close()
    client.post("/app/api/pos/held", cookies=cook, json={
        "items": [_line(cid, 1)], "customer_id": c_id, "customer_name": "ignored", "total": 9000})
    db = SessionLocal()
    db.query(Customer).filter(Customer.id == c_id).first().balance = 7000
    db.commit(); db.close()
    cust = client.get("/app/api/pos/held", cookies=cook).json()["held"][0]["customer"]
    assert cust == {"id": c_id, "name": "Bello Builders", "phone": "2348030000000", "balance": 7000}


def test_titi_explains_holding_a_sale():
    from faq import detect_faq, FAQ_ANSWERS
    for q in ["how do i hold a sale", "my customer is not ready?", "can i save as draft at the till?"]:
        assert detect_faq(q) == "hold_sale", q
    assert "*Hold*" in FAQ_ANSWERS["hold_sale"] and "no stock moves" in FAQ_ANSWERS["hold_sale"]
    assert detect_faq("how do i see my customer list?") == "customer_list"
