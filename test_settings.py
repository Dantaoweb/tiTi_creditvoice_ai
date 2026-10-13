"""
Settings people choose: their own display, and (owner / authorised staff) the
business's stock and summary choices. Defaults are how the app always worked.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-settings-000000000000000")

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import web_auth
from app_settings import BUSINESS_DEFAULTS, DISPLAY_DEFAULTS, send_daily_summaries
from database import SessionLocal
from main import app
from models import InventoryItem, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348093{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Mama Joy Stores", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(phone=phone).one()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        rice = InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=5,
                             selling_price=60000, is_available=True)
        coke = InventoryItem(owner_phone=phone, name="coke", unit="bottle", quantity=24,
                             selling_price=300, is_available=True, category="drinks")
        db.add_all([rice, coke]); db.commit()
        return phone, cook, rice.id, coke.id
    finally:
        db.close()


def _staff(owner_phone, authorised):
    phone = f"2348093{next(_seq):06d}"
    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(phone=owner_phone).one()
        db.add(User(phone=phone, name="Sade", role="delegate", parent_id=owner.id,
                    can_view_all_transactions=authorised, subscription_status="ACTIVE",
                    recovery_pin_hash=web_auth._hash_pin("1234")))
        db.commit()
    finally:
        db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "1234"}).cookies


def test_defaults_are_how_the_app_always_worked():
    _p, cook, _r, _c = _shop()
    s = client.get("/app/api/settings", cookies=cook).json()
    assert s["display"] == DISPLAY_DEFAULTS
    assert s["business"] == BUSINESS_DEFAULTS and s["can_edit_business"] is True
    assert s["business"]["allow_negative_stock"] is True and s["business"]["group_by_category"] is False


def test_display_is_each_persons_own():
    phone, cook, _r, _c = _shop()
    staff = _staff(phone, False)
    r = client.put("/app/api/settings/display", cookies=staff, json={"text_size": "xlarge", "theme": "dark"})
    assert r.status_code == 200
    assert client.get("/app/api/settings", cookies=staff).json()["display"]["text_size"] == "xlarge"
    assert client.get("/app/api/settings", cookies=cook).json()["display"]["text_size"] == "normal"
    assert client.put("/app/api/settings/display", cookies=cook, json={"theme": "pink"}).status_code == 400


def test_only_owner_and_authorised_staff_change_business_settings():
    phone, cook, _r, _c = _shop()
    plain = _staff(phone, False)
    assert client.get("/app/api/settings", cookies=plain).json()["can_edit_business"] is False
    r = client.put("/app/api/settings/business", cookies=plain, json={"values": {"group_by_category": True}})
    assert r.status_code == 403
    r = client.put("/app/api/settings/business", cookies=_staff(phone, True),
                   json={"values": {"group_by_category": True, "daily_summary_time": "21:30"}})
    assert r.status_code == 200 and r.json()["business"]["group_by_category"] is True
    assert client.put("/app/api/settings/business", cookies=cook,
                      json={"values": {"daily_summary_time": "25:00"}}).status_code == 400


def test_selling_below_zero_can_be_switched_off():
    phone, cook, rice, _c = _shop()
    sale = {"owner_phone": phone, "items": [{"inventory_item_id": rice, "name": "rice", "qty": 6,
                                              "unit": "bag", "unit_price": 60000}], "payment_amount": 360000}
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"allow_negative_stock": False}})
    r = client.post("/app/api/pos/save", cookies=cook, json=sale)
    assert r.status_code == 400 and "only 5" in r.json()["detail"] and "Settings" in r.json()["detail"]
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"allow_negative_stock": True}})
    assert client.post("/app/api/pos/save", cookies=cook, json=sale).status_code == 200


def test_categories_group_rename_and_assign():
    phone, cook, rice, coke = _shop()
    cats = {c["label"]: c for c in client.get("/app/api/categories", cookies=cook).json()["categories"]}
    assert cats["Drinks"]["count"] == 1 and cats["Uncategorised"]["count"] == 1

    r = client.post("/app/api/categories/assign", cookies=cook, json={"item_ids": [rice], "category": "Provisions"})
    assert r.json()["assigned"] == 1
    page = client.get("/app/api/inventory", cookies=cook, params={"category": "provisions"}).json()
    assert [i["name"] for i in page["items"]] == ["rice"]

    client.post("/app/api/categories/rename", cookies=cook, json={"old": "drinks", "new": "Soft drinks"})
    labels = [c["label"] for c in client.get("/app/api/categories", cookies=cook).json()["categories"]]
    assert "Soft Drinks" in labels and "Drinks" not in labels
    r = client.post("/app/api/categories/rename", cookies=cook, json={"old": "provisions", "new": "service"})
    assert r.status_code == 400                                   # reserved for services


def test_new_products_get_the_default_low_stock_alert():
    phone, cook, _r, _c = _shop()
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"default_low_stock": 5}})
    item = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "Sardine", "unit": "tin", "selling_price": 900, "quantity": 20}).json()
    db = SessionLocal()
    try:
        assert db.query(InventoryItem).filter_by(owner_phone=phone, name="sardine").one().low_stock_alert == 5
    finally:
        db.close()


def test_daily_summary_goes_once_after_the_chosen_time():
    phone, cook, _r, _c = _shop()
    client.put("/app/api/settings/business", cookies=cook,
               json={"values": {"daily_summary": True, "daily_summary_time": "20:00"}})
    got = []
    send = lambda to, text: got.append((to, text))
    db = SessionLocal()
    try:
        early = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)      # 19:00 Lagos
        late = datetime(2026, 10, 13, 19, 30, tzinfo=timezone.utc)      # 20:30 Lagos
        send_daily_summaries(db, send, now=early)
        assert not [g for g in got if g[0] == phone]
        send_daily_summaries(db, send, now=late)
        send_daily_summaries(db, send, now=late)                        # not twice
        mine = [g for g in got if g[0] == phone]
        assert len(mine) == 1 and "daily summary" in mine[0][1]
    finally:
        db.close()


@pytest.mark.parametrize("ask", [
    "how do i make the text bigger?", "how do I turn on dark mode",
    "how can I group my stock by category?", "settings", "how do I get a daily summary?",
])
def test_titi_explains_settings(ask):
    from faq import detect_faq
    from parser import parse_message
    p = parse_message(ask) or {}
    topic = p.get("topic") if p.get("type") == "APP_GUIDE" else detect_faq(ask)
    assert topic == "settings"
