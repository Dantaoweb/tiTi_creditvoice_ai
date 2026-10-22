"""
Expiry: each delivery keeps its own date; what's still in the store is the
newest deliveries (oldest sold first). Owners are told what's expired or
expiring soon, the till warns, and expired goods are written off as a loss.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-expiry-000000000000000000")

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import InventoryItem, StockBatch

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348102{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Pharmacy", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        it = InventoryItem(owner_phone=phone, name="paracetamol", unit="pack", quantity=0,
                           selling_price=500, cost_price=300, is_available=True)
        db.add(it); db.commit()
        return phone, cook, it.id
    finally:
        db.close()


def _receive(cook, item_id, qty, expiry=None, batch=None):
    return client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "item_id": item_id, "quantity": qty, "cost_per_unit": 300, "expiry_date": expiry, "batch_no": batch})


def _age(item_id, days):
    """Make the deliveries look older than they are, oldest first."""
    db = SessionLocal()
    try:
        for i, b in enumerate(db.query(StockBatch).filter(StockBatch.item_id == item_id).order_by(StockBatch.id).all()):
            b.received_at = datetime.utcnow() - timedelta(days=days - i)
        db.commit()
    finally:
        db.close()


def _stock(item_id, qty):
    db = SessionLocal(); db.query(InventoryItem).get(item_id).quantity = qty; db.commit(); db.close()


def test_each_delivery_keeps_its_date_oldest_sold_first():
    _p, cook, iid = _shop()
    old = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d")
    soon = (datetime.utcnow() + timedelta(days=12)).strftime("%Y-%m-%d")
    later = (datetime.utcnow() + timedelta(days=400)).strftime("%Y-%m")
    assert _receive(cook, iid, 20, old, "BN-1").status_code == 200
    _receive(cook, iid, 30, soon)
    _receive(cook, iid, 40, later)
    _age(iid, 60)

    exp = client.get("/app/api/inventory/expiry", cookies=cook).json()
    [row] = exp["items"]
    assert exp["warn_days"] == 30 and (row["expired_qty"], row["soon_qty"]) == (20, 30)

    _stock(iid, 60)          # 30 sold — the oldest went first: the expired 20 and 10 of the next
    [row] = client.get("/app/api/inventory/expiry", cookies=cook).json()["items"]
    assert (row["expired_qty"], row["soon_qty"]) == (0, 20)

    inv = client.get("/app/api/inventory", cookies=cook).json()["items"][0]
    assert inv["expiry"]["soon_qty"] == 20 and inv["expiry"]["next_expiry"] == soon


def test_write_off_counts_as_a_loss_and_the_till_warns():
    phone, cook, iid = _shop()
    _receive(cook, iid, 10, (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"))
    _receive(cook, iid, 10)
    _age(iid, 30)
    prods = client.get("/app/api/pos/products", cookies=cook).json()["products"]
    assert prods[0]["expired_qty"] == 10

    assert client.post(f"/app/api/inventory/{iid}/write-off-expired", cookies=cook,
                       json={"quantity": 25}).status_code == 400
    assert client.post(f"/app/api/inventory/{iid}/write-off-expired", cookies=cook,
                       json={"quantity": 10}).status_code == 200
    assert client.get("/app/api/inventory/expiry", cookies=cook).json()["items"] == []
    loss = client.get("/app/api/stock-counts/losses", cookies=cook).json()
    assert loss["lost"] == 3000 and loss["by_reason"] == [{"reason": "Expired", "value": -3000}]


def test_bad_date_is_refused_and_warn_days_setting():
    _p, cook, iid = _shop()
    assert _receive(cook, iid, 5, "soon").status_code == 400
    assert client.put("/app/api/settings/business", cookies=cook,
                      json={"values": {"expiry_warn_days": 7}}).status_code == 200
    _receive(cook, iid, 5, (datetime.utcnow() + timedelta(days=12)).strftime("%Y-%m-%d"))
    assert client.get("/app/api/inventory/expiry", cookies=cook).json()["items"] == []   # 12 days > 7


def test_whatsapp_set_date_still_counts():
    """A product dated the old way (WhatsApp) — its deliveries without their own date use it."""
    _p, cook, iid = _shop()
    _receive(cook, iid, 8)
    db = SessionLocal()
    try:
        db.query(InventoryItem).get(iid).expiry_date = datetime.utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    [row] = client.get("/app/api/inventory/expiry", cookies=cook).json()["items"]
    assert row["expired_qty"] == 8


def test_daily_alert():
    phone, cook, iid = _shop()
    _receive(cook, iid, 6, (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d"))
    from models import AppNotification
    from proactive_scheduler import _check_expiry
    db = SessionLocal()
    try:
        _check_expiry(db); _check_expiry(db)            # once a day only
        notes = db.query(AppNotification).filter(AppNotification.owner_phone == phone,
                                                 AppNotification.event_type == "expiry").all()
        assert len(notes) == 1 and "Paracetamol" in notes[0].body
    finally:
        db.close()


@pytest.mark.parametrize("text", [
    "how do I add expiry date?", "how will I know when goods expire", "what do I do with expired goods?",
    "where do I put the batch number",
])
def test_titi_explains_expiry(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    from models import User
    p = parse_message(text) or {}
    assert (p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "expiry"
    a = build_app_guide_message("expiry", User(phone="1", business_type="pharmacy", business_category="health"))
    assert "Expiry date" in a and "Write off expired" in a and "{record}" not in a


def test_subscription_expiry_is_not_goods_expiry():
    from faq import detect_faq
    assert detect_faq("when does my subscription expire?") != "expiry"
