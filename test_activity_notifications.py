"""
#11: notes and transaction voids create in-app notifications the owner sees,
whether done by the owner or a staff member.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-activity-notifs-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _pro_owner():
    n = next(_seq)
    phone = f"234800999{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Boss", "phone": phone, "pin": "5678"})
    db = SessionLocal(); u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PRO"; u.subscription_status = "ACTIVE"; db.commit(); db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _events(cook):
    return [n["event_type"] for n in client.get("/app/api/notifications", cookies=cook).json()["notifications"]]


def test_note_creates_notification():
    phone, cook = _pro_owner()
    r = client.post("/app/api/notes", cookies=cook,
                    json={"body": "Bought fuel for generator", "category": "expense",
                          "amount": 5000, "visibility": "owner_only"})
    assert r.status_code == 200, r.text
    assert "note" in _events(cook)


def test_void_creates_notification():
    phone, cook = _pro_owner()
    sale = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "items": [{"name": "x", "qty": 1, "unit_price": 500}], "payment_amount": 500})
    tx_id = sale.json()["receipt_id"]
    v = client.post(f"/app/api/transactions/{tx_id}/void", cookies=cook, json={"reason": "wrong amount"})
    assert v.status_code == 200, v.text
    notifs = client.get("/app/api/notifications", cookies=cook).json()["notifications"]
    assert any(n["event_type"] == "void" and "wrong amount" in n["body"] for n in notifs)


def test_staff_note_is_seen_by_owner():
    owner_phone, ocook = _pro_owner()
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    sp = f"234807999{next(_seq):04d}"
    staff = User(phone=sp, name="Sade", role="delegate", parent_id=owner.id,
                 recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE")
    db.add(staff); db.commit(); db.close()
    scook = client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies

    client.post("/app/api/notes", cookies=scook,
                json={"body": "Restocked shelf", "category": "memo", "visibility": "all"})
    notifs = client.get("/app/api/notifications", cookies=ocook).json()["notifications"]
    assert any(n["event_type"] == "note" and "Sade" in n["body"] for n in notifs)
