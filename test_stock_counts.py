"""
Stock count: a staff member counts the shelves without seeing the app's
numbers, the owner approves, and stock changes by each difference — with a
reason, valued at cost, so losses show up.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-stock-counts-0000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, InventoryItem, InventoryMovement, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    n = next(_seq)
    phone, staff_phone = f"2348097{n:06d}", f"2348098{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Stores", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == phone).first()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        db.add(User(phone=staff_phone, name="Sule", role="delegate", parent_id=owner.id,
                    can_view_all_transactions=False, recovery_pin_hash=web_auth._hash_pin("1234"),
                    subscription_status="ACTIVE"))
        items = [
            InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=50, cost_price=60000,
                          selling_price=70000, category="provisions", is_available=True),
            InventoryItem(owner_phone=phone, name="milo", unit="tin", quantity=20, cost_price=3000,
                          selling_price=3500, category="drinks", is_available=True),
            InventoryItem(owner_phone=phone, name="haircut", quantity=None, category="service",
                          selling_price=1000, is_available=True),
        ]
        db.add_all(items); db.commit()
        ids = {i.name: i.id for i in items}
    finally:
        db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    staff = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "1234"}).cookies
    return phone, cook, staff, ids


def _qty(item_id):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).get(item_id).quantity
    finally:
        db.close()


def _line(doc, product):
    return next(l for l in doc["lines"] if l["product"] == product)


def test_staff_counts_blind_owner_approves():
    phone, cook, staff, ids = _shop()
    doc = client.post("/app/api/stock-counts", cookies=staff, json={}).json()
    assert doc["number"] == "SC-0001" and doc["status"] == "counting" and doc["blind"] is True
    assert [l["product"] for l in doc["lines"]] == ["Milo", "Rice"]          # services aren't counted
    assert "expected" not in doc["lines"][0]                                  # blind: no app numbers

    rice, milo = _line(doc, "Rice")["id"], _line(doc, "Milo")["id"]
    client.put(f"/app/api/stock-counts/{doc['id']}/counts", cookies=staff, json={"counts": {str(rice): 47}})
    doc = client.post(f"/app/api/stock-counts/{doc['id']}/submit", cookies=staff,
                      json={"counts": {str(milo): 22}}).json()
    assert doc["status"] == "submitted" and doc["can_approve"] is False
    assert doc["value_lost"] is None                                          # staff don't see cost figures
    assert _qty(ids["rice"]) == 50                                            # nothing changes yet

    db = SessionLocal()
    try:
        note = db.query(AppNotification).filter(AppNotification.owner_phone == phone,
                                                AppNotification.event_type == "stock_count").one()
        assert "SC-0001" in note.title and "to approve" in note.title
    finally:
        db.close()

    # Staff can't approve
    assert client.post(f"/app/api/stock-counts/{doc['id']}/approve", cookies=staff, json={}).status_code == 403

    # A sale while it waits: 2 rice sold → 48 in the app
    db = SessionLocal(); db.query(InventoryItem).get(ids["rice"]).quantity = 48; db.commit(); db.close()

    owner_view = client.get(f"/app/api/stock-counts/{doc['id']}", cookies=cook).json()
    r = _line(owner_view, "Rice")
    assert (r["expected"], r["counted"], r["difference"], r["value"]) == (50, 47, -3, -180000)
    assert _line(owner_view, "Milo")["reason"] == "found"                     # extra: found by default
    assert owner_view["value_lost"] == 180000 and owner_view["value_found"] == 6000

    # A shortage needs a reason
    r = client.post(f"/app/api/stock-counts/{doc['id']}/approve", cookies=cook, json={})
    assert r.status_code == 400 and "Say why Rice" in r.json()["detail"]
    done = client.post(f"/app/api/stock-counts/{doc['id']}/approve", cookies=cook,
                       json={"reasons": {str(rice): "missing"}}).json()
    assert done["status"] == "approved"
    assert _qty(ids["rice"]) == 45          # 48 now − 3 missing: the sale in between is kept
    assert _qty(ids["milo"]) == 22

    db = SessionLocal()
    try:
        mv = db.query(InventoryMovement).filter(InventoryMovement.item_id == ids["rice"],
                                                InventoryMovement.source_type == "STOCK_COUNT").one()
        assert mv.movement_type == "OUT" and mv.quantity == 3 and "Stolen / missing" in mv.note
    finally:
        db.close()

    # Losses, by reason, for the owner only
    loss = client.get("/app/api/stock-counts/losses", cookies=cook).json()
    assert loss["lost"] == 180000 and loss["found"] == 6000
    assert loss["by_reason"][0] == {"reason": "Stolen / missing", "value": -180000}
    assert client.get("/app/api/stock-counts/losses", cookies=staff).status_code == 403

    # Approved once only
    assert client.post(f"/app/api/stock-counts/{doc['id']}/approve", cookies=cook, json={}).status_code == 400


def test_uncounted_products_are_left_alone_and_one_category():
    _phone, cook, _staff, ids = _shop()
    doc = client.post("/app/api/stock-counts", cookies=cook, json={"category": "drinks"}).json()
    assert doc["scope"] == "Drinks" and [l["product"] for l in doc["lines"]] == ["Milo"]
    r = client.post(f"/app/api/stock-counts/{doc['id']}/submit", cookies=cook, json={"counts": {}})
    assert r.status_code == 400 and "Count at least one" in r.json()["detail"]


def test_blind_count_can_be_turned_off_and_cancelled():
    _phone, cook, staff, _ids = _shop()
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"count_blind": False}})
    doc = client.post("/app/api/stock-counts", cookies=staff, json={}).json()
    assert doc["blind"] is False and _line(doc, "Rice")["expected"] == 50
    assert client.post(f"/app/api/stock-counts/{doc['id']}/cancel", cookies=staff).json()["status"] == "cancelled"
    assert [c["status"] for c in client.get("/app/api/stock-counts", cookies=cook).json()["counts"]] == ["cancelled"]


def test_another_business_cannot_see_a_count():
    _p, cook, _s, _i = _shop()
    _p2, cook2, _s2, _i2 = _shop()
    doc = client.post("/app/api/stock-counts", cookies=cook, json={}).json()
    assert client.get(f"/app/api/stock-counts/{doc['id']}", cookies=cook2).status_code == 404


@pytest.mark.parametrize("text", [
    "how do I do stock count?", "what is blind count", "my stock is wrong how do i fix it",
    "how to approve the count",
])
def test_titi_explains_stock_count(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    p = parse_message(text) or {}
    topic = p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)
    assert topic == "stock_count"
    answer = build_app_guide_message("stock_count")
    assert "Count stock" in answer and "blind count" in answer and "Approve" in answer


def test_whatsapp_fix_one_product_phrase_still_works():
    from parser import parse_message
    assert parse_message("set stock rice 50 bags")["type"] == "STOCK_SET"
