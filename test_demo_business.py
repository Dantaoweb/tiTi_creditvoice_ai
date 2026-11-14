"""
Demo business (demo_business.py): an admin or marketer opens a demo business,
shows it as a bakery, a pharmacy…, resets it, and exits back to their own
account. Sample data only; never messaged; left out of admin counts; nobody
else can open one.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-demo-business-0000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from admin import ROLE_APP_ADMIN
from database import SessionLocal
from main import app
from models import AppAdminRole, Customer, InventoryItem, Recipe, Transaction, User
from parser import normalize_phone

_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _phone(prefix="2347111"):
    return f"{prefix}{next(_seq):06d}"


def _account(admin=False):
    """A fresh client (its own cookie jar) logged in as a new user."""
    c = TestClient(app)
    phone = _phone()
    c.post("/app/api/auth/register", json={"name": "Femi Ade", "phone": phone, "pin": "5678"})
    if admin:
        db = SessionLocal()
        db.add(AppAdminRole(phone=normalize_phone(phone), role=ROLE_APP_ADMIN, is_active=True))
        db.commit(); db.close()
    c.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"})
    return c, phone


def _me(c):
    return c.get("/app/api/auth/me").json()


def test_open_switch_reset_and_exit():
    c, phone = _account(admin=True)
    assert _me(c)["can_demo"] is True
    st = c.get("/app/api/demo").json()
    assert st["in_demo"] is False and st["demo"] is None and st["types"][0]["group"] == "Popular"

    r = c.post("/app/api/demo/open", json={"business_type": "bakery"})
    assert r.status_code == 200, r.text
    me = _me(c)
    assert me["is_demo"] is True and me["business_type"] == "bakery" and me["phone"].startswith("999")
    assert me["can_demo"] is False and me["is_app_admin"] is False            # the demo is just a business
    demo_phone = me["phone"]
    db = SessionLocal()
    try:
        assert db.query(InventoryItem).filter(InventoryItem.owner_phone == demo_phone).count() == 8
        custs = db.query(Customer).filter(Customer.owner_phone == demo_phone).all()
        assert len(custs) == 4 and all(cu.customer_phone.startswith("999") for cu in custs)
        assert any((cu.balance or 0) > 0 for cu in custs)                    # a sample debt
        assert db.query(Recipe).filter(Recipe.owner_phone == demo_phone).count() == 1
    finally:
        db.close()
    # Its screens work like any business
    assert c.get("/app/api/production").status_code == 200

    # Show me as a pharmacy: a fresh demo; the bakery one is retired
    r = c.post("/app/api/demo/switch", json={"business_type": "pharmacy"})
    assert r.status_code == 200, r.text
    me = _me(c)
    assert me["business_type"] == "pharmacy" and me["phone"] != demo_phone
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.phone == demo_phone).first().deleted_at is not None
    finally:
        db.close()
    # Reset = the same type, fresh
    before = me["phone"]
    c.post("/app/api/demo/switch", json={})
    assert _me(c)["business_type"] == "pharmacy" and _me(c)["phone"] != before

    # Exit: back to the real account
    r = c.post("/app/api/demo/exit")
    assert r.status_code == 200, r.text
    me = _me(c)
    assert me["phone"] == phone and me["is_demo"] is False
    # Opening again without a type goes back to the same demo
    c.post("/app/api/demo/open", json={})
    assert _me(c)["business_type"] == "pharmacy"


def test_marketers_can_demo_and_others_cant():
    admin, _ap = _account(admin=True)
    mc, mphone = _account()
    assert _me(mc)["can_demo"] is False
    admin.post("/app/api/admin/marketers", json={"name": "Wale", "phone": mphone})
    assert _me(mc)["can_demo"] is True
    assert mc.post("/app/api/demo/open", json={"business_type": "building_materials"}).status_code == 200
    assert _me(mc)["business_type"] == "building_materials"

    plain, _p = _account()
    assert plain.get("/app/api/demo").status_code == 403
    assert plain.post("/app/api/demo/open", json={}).status_code == 403
    assert plain.post("/app/api/demo/switch", json={"business_type": "bakery"}).status_code == 400
    assert plain.post("/app/api/demo/exit").status_code == 401         # nothing to go back to
    bad = admin.post("/app/api/demo/open", json={"business_type": "not_a_type"})
    assert bad.status_code == 400


def test_demos_are_never_messaged_or_counted(monkeypatch):
    import whatsapp_client
    sent = []
    monkeypatch.setattr(whatsapp_client, "WHATSAPP_TOKEN", "x")
    monkeypatch.setattr(whatsapp_client, "PHONE_NUMBER_ID", "y")
    monkeypatch.setattr(whatsapp_client.requests, "post", lambda *a, **k: sent.append(a) or None)
    assert whatsapp_client.send_whatsapp_message("9990000000001", "hi") is None
    assert whatsapp_client.send_whatsapp_template("9990000000001", "reminder") is None
    assert sent == []

    admin, _ap = _account(admin=True)
    before = admin.get("/app/api/admin/stats").json() if admin.get("/app/api/admin/stats").status_code == 200 else None
    demo_c, _ = _account(admin=True)
    demo_c.post("/app/api/demo/open", json={"business_type": "provision_store"})
    users = admin.get("/app/api/admin/users?per_page=200").json()["users"]
    assert not any(u["phone"].startswith("999") for u in users)
    if before is not None:
        after = admin.get("/app/api/admin/stats").json()
        assert after["users"]["total"] == before["users"]["total"] + 1     # the new admin, not the demo
        assert after["transactions"]["total"] == before["transactions"]["total"]
