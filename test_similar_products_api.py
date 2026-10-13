"""
The web app and WhatsApp stop a product being added twice by accident.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-similar-products-00000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from faq import detect_faq
from main import app
from models import InventoryItem
from parser import parse_message

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348091{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Mama Joy Pharmacy", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        owner = db.query(__import__("models").User).filter_by(phone=phone).one()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        db.add_all([
            InventoryItem(owner_phone=phone, name="paracetamol 500mg", unit="pack", quantity=40,
                          selling_price=500, is_available=True),
            InventoryItem(owner_phone=phone, name="groundnut oil", unit="bottle", quantity=9,
                          selling_price=2500, is_available=True),
            InventoryItem(owner_phone=phone, name="peak milk (tin)", unit="tin", quantity=30,
                          selling_price=600, is_available=True),
            InventoryItem(owner_phone=phone, name="peak milk tin", unit="tin", quantity=6,
                          selling_price=600, is_available=True),
        ])
        db.commit()
    finally:
        db.close()
    return phone, cook


def test_add_product_warns_and_refuses_a_twin():
    phone, cook = _shop()
    r = client.get("/app/api/inventory/similar", cookies=cook, params={"name": "paracetemol 500mg"}).json()
    assert r["exact"] == [] and r["similar"][0]["name"] == "Paracetamol 500Mg"

    r = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "Paracetamol 500 MG", "unit": "pack", "selling_price": 500})
    assert r.status_code == 409 and "already have this product" in r.json()["detail"]

    r = client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "Sardine", "unit": "tin", "selling_price": 900})
    assert r.status_code == 200, r.text


def test_search_offers_close_matches():
    _phone, cook = _shop()
    d = client.get("/app/api/inventory", cookies=cook, params={"q": "g/nut oil"}).json()
    assert d["total"] == 0 and d["close_matches"][0]["name"] == "Groundnut Oil"


def test_duplicates_listed():
    _phone, cook = _shop()
    pairs = client.get("/app/api/inventory/duplicates", cookies=cook).json()["pairs"]
    assert any({p["a"]["name"], p["b"]["name"]} == {"Peak Milk (Tin)", "Peak Milk Tin"} for p in pairs)


def test_quick_add_skips_a_name_already_there_in_another_spelling():
    phone, cook = _shop()
    r = client.post("/app/api/inventory/bulk", cookies=cook, json={
        "owner_phone": phone, "names": ["Groundnut-Oil", "Ground nut oil", "Bournvita"]}).json()
    assert r["saved"] == 1 and r["already_existed"] == 2


@pytest.mark.parametrize("ask", [
    "how can I know if a product is already in my stock?",
    "i can't find a product, how do I know if I added it before?",
])
def test_titi_explains_how_to_check(ask):
    p = parse_message(ask) or {}
    topic = p.get("topic") if p.get("type") == "APP_GUIDE" else detect_faq(ask)
    assert topic == "already_in_stock"
