"""
Consultants have clients, landlords have tenants, transporters have customers.

These businesses share the "fee" menu layout (no stock tabs), but its words —
members, dues, levies — were written for associations. Each now gets its own
wording on the web and in tiTi, while the menu layout stays the same.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-label-groups-00000000000")

from types import SimpleNamespace as N

import pytest
from fastapi.testclient import TestClient

import web_auth
from biz_language import confirm_prefix, get_lang
from business_templates import label_group_for_user, menu_group_for_user
from database import SessionLocal
from main import app
from models import User

client = TestClient(app, raise_server_exceptions=True)


def _user(business_type):
    return N(business_type=business_type, business_category=None, parent_id=None)


@pytest.mark.parametrize("business_type, group, people, confirm", [
    ("consulting",        "professional", "Total clients",   "Confirm:\nBayo fee:"),
    ("law_chamber",       "professional", "Total clients",   "Confirm:\nBayo fee:"),
    ("bookkeeping",       "professional", "Total clients",   "Confirm:\nBayo fee:"),
    ("property_manager",  "tenancy",      "Total tenants",   "Confirm:\nBayo rent:"),
    ("stall_rent",        "tenancy",      "Total tenants",   "Confirm:\nBayo rent:"),
    ("event_rental",      "rental",       "Total clients",   "Confirm:\nBayo hired"),
    ("dispatch_delivery", "transport",    "Total customers", "Confirm:\nBayo delivery:"),
])
def test_each_kind_gets_its_own_words_but_keeps_the_fee_layout(business_type, group, people, confirm):
    u = _user(business_type)
    assert menu_group_for_user(u) == "fee"                 # layout unchanged (no stock tabs)
    assert label_group_for_user(u) == group
    assert get_lang(u)["total_customers"] == people
    assert "member" not in get_lang(u)["total_customers"].lower()
    assert confirm_prefix("Bayo", u) == confirm


def test_everyone_else_is_unchanged():
    for bt in ("supermarket", "barber", "clinic_general"):
        u = _user(bt)
        assert label_group_for_user(u) == menu_group_for_user(u)


def test_the_app_is_told_the_wording_group():
    phone = "2348064000777"
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    client.post("/app/api/auth/register", json={"name": "Bayo Consult", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.business_type = "consulting"
        db.commit()
    finally:
        db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    me = client.get("/app/api/auth/me", cookies=cook).json()
    me = me.get("user", me)
    assert me["menu_group"] == "fee" and me["label_group"] == "professional"
