"""
Plan payments: admins hear when a business says it paid, and only those count.

A payment request exists the moment the bank details are shown, so "pending"
alone mixes people who paid with people who only looked. What an admin must
check is a payment the business says it made.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-payment-alerts-0000000000")
ADMIN_PHONE = "2348090099000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppAdminRole, AppNotification, SubscriptionPayment, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    box = []
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda p, m: box.append((p, m)))
    db = SessionLocal()
    try:
        db.query(SubscriptionPayment).delete()
        db.query(AppNotification).delete()
        db.commit()
    finally:
        db.close()
    yield box


def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


@pytest.fixture
def admin():
    return _register(ADMIN_PHONE, "App Admin")


def _business():
    phone = f"2348079{next(_seq):06d}"
    return phone, _register(phone, "Ade Stores")


def _notes(phone, event_type):
    db = SessionLocal()
    try:
        return (db.query(AppNotification)
                .filter(AppNotification.owner_phone == phone, AppNotification.event_type == event_type)
                .order_by(AppNotification.id.asc()).all())
    finally:
        db.close()


def _pending(admin):
    return client.get("/app/api/admin/pending-counts", cookies=admin).json()["payments"]


def test_looking_at_bank_details_is_not_a_payment(admin):
    _phone, cook = _business()
    client.post("/app/api/subscription/request", json={"plan": "GO"}, cookies=cook)

    assert _notes(ADMIN_PHONE, "payment_reported") == []
    assert _pending(admin) == 0
    row = client.get("/app/api/admin/subscription-payments", cookies=admin).json()["payments"][0]
    assert row["paid_reported_at"] is None


def test_saying_paid_alerts_every_admin_and_counts(admin):
    # An admin granted from the app is told too, not just the env list.
    db = SessionLocal()
    try:
        db.add(AppAdminRole(phone="2348090099111", role="APP_ADMIN", is_active=True))
        db.commit()
    finally:
        db.close()
    _register("2348090099111", "Second Admin")

    _phone, cook = _business()
    client.post("/app/api/subscription/request", json={"plan": "GO"}, cookies=cook)
    assert client.post("/app/api/subscription/confirm-payment", json={"plan": "GO"}, cookies=cook).status_code == 200

    for who in (ADMIN_PHONE, "2348090099111"):
        notes = _notes(who, "payment_reported")
        assert len(notes) == 1, who
        assert notes[0].link == "/admin?tab=Payments"
        assert "Ade Stores" in notes[0].body and "GO" in notes[0].body
    assert _pending(admin) == 1
    row = client.get("/app/api/admin/subscription-payments", cookies=admin).json()["payments"][0]
    assert row["paid_reported_at"]


def test_reject_with_a_reason_tells_the_business(admin, sent):
    phone, cook = _business()
    client.post("/app/api/subscription/request", json={"plan": "GO"}, cookies=cook)
    client.post("/app/api/subscription/confirm-payment", json={"plan": "GO"}, cookies=cook)
    pid = client.get("/app/api/admin/subscription-payments", cookies=admin).json()["payments"][0]["id"]

    r = client.post(f"/app/api/admin/subscription-payments/{pid}/reject", cookies=admin,
                    json={"reason": "No transfer of N5,000 received"})
    assert r.status_code == 200, r.text
    told = [n for n in _notes(phone, "upgrade") if n.title == "Payment not confirmed"]
    assert told and "No transfer of N5,000 received" in told[0].body
    assert any(p == phone and "No transfer of N5,000 received" in m for p, m in sent)
    assert _pending(admin) == 0


def test_reject_without_a_body_still_works(admin):
    phone, cook = _business()
    client.post("/app/api/subscription/request", json={"plan": "GO"}, cookies=cook)
    client.post("/app/api/subscription/confirm-payment", json={"plan": "GO"}, cookies=cook)
    pid = client.get("/app/api/admin/subscription-payments", cookies=admin).json()["payments"][0]["id"]
    assert client.post(f"/app/api/admin/subscription-payments/{pid}/reject", cookies=admin).status_code == 200
    told = [n for n in _notes(phone, "upgrade") if n.title == "Payment not confirmed"]
    assert told and "clearer receipt" in told[0].body


def test_a_card_payment_tells_the_admins_it_came_in(admin):
    from web_subscription_routes import _tell_admins_card_paid
    phone, _cook = _business()
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == phone).first()
        payment = SubscriptionPayment(user_id=owner.id, phone=phone, plan="PRO", amount=15000,
                                      billing_period="MONTHLY", payment_method="MONNIFY",
                                      status="APPROVED")
        db.add(payment); db.commit()
        _tell_admins_card_paid(db, payment, owner)
    finally:
        db.close()
    notes = _notes(ADMIN_PHONE, "payment_card")
    assert len(notes) == 1 and "N15,000" in notes[0].body and "already active" in notes[0].body
