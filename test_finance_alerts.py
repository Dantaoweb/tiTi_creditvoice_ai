"""
Who hears what as a finance application moves.

A request waits at SUBMITTED until an admin shares it, so the admins must be
told it arrived. The business must hear each stage (with the reason when
declined). The financier's portal has no bell, so they are reached on
WhatsApp and email when a request is shared with them, a repayment needs
confirming, or a shared request is withdrawn.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-finance-alerts-000000000")
ADMIN_PHONE = "2348090088000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import web_auth
from conftest import month_slot
from database import SessionLocal
from main import app
from models import AppNotification, Customer, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(3000, 5000))

KYC = {"legal_name": "Ade Owner", "state": "Lagos", "city": "Ikeja",
       "address": "12 Allen Avenue", "id_type": "NIN", "id_number": "22233344455",
       "is_registered": False}


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Everything sent to a financier, by channel."""
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    box = {"whatsapp": [], "email": []}
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda phone, msg: box["whatsapp"].append((phone, msg)))
    monkeypatch.setattr("email_service.send_email",
                        lambda to, subject, html, text="": box["email"].append((to, subject, text)) or True)
    monkeypatch.setattr("feature_flags.whatsapp_live", lambda db=None: True)
    db = SessionLocal()
    try:
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
    phone = f"234866{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(3):
            for i in range(4):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=150_000,
                                   recorded_by_id=u.id, created_at=month_slot(m, i, 5, 4)))
        db.commit()
    finally:
        db.close()
    client.post("/app/api/kyc", cookies=cookies, json=KYC)
    return phone, cookies


def _financier(admin):
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json={
        "name": "Gig Wheels", "asset_types": ["motorcycle"], "eligibility": {},
        "commission_type": "PERCENT_OF_ASSET", "commission_value": 500,
        "commission_due_on": "ON_DELIVERY"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    staff_phone = f"234867{next(_seq):06d}"
    created = client.post("/app/api/admin/financier-users", cookies=admin, json={
        "finance_partner_id": pid, "name": "Ops Person", "phone": staff_phone,
        "email": "ops@gigwheels.test"})
    assert created.status_code == 200, created.text
    accepted = client.post("/app/api/financier/accept-invite",
                           json={"code": created.json()["invite_code"], "pin": "4321"})
    return pid, staff_phone, accepted.cookies


def _apply(cook, pid):
    r = client.post(f"/app/api/finance-offers/{pid}/apply", cookies=cook, json={
        "consent": True, "asset_requested": "motorcycle", "asset_value": 1_000_000})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _move(admin, aid, **body):
    r = client.patch(f"/app/api/admin/finance-applications/{aid}", cookies=admin, json=body)
    assert r.status_code == 200, r.text


def _notes(phone, event_type):
    db = SessionLocal()
    try:
        return (db.query(AppNotification)
                .filter(AppNotification.owner_phone == phone, AppNotification.event_type == event_type)
                .order_by(AppNotification.id.asc()).all())
    finally:
        db.close()


def test_admins_hear_of_a_new_request_and_it_counts_until_shared(admin):
    pid, _staff, _fc = _financier(admin)
    _phone, cook = _business()
    aid = _apply(cook, pid)

    notes = _notes(ADMIN_PHONE, "finance_application")
    assert len(notes) == 1
    assert notes[0].link == "/admin?tab=Finance"
    assert "Ade Rides" in notes[0].body and "Gig Wheels" in notes[0].body
    assert "motorcycle" in notes[0].body and "N1,000,000" in notes[0].body

    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["finance"] == 1
    _move(admin, aid, status="SHARED")
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["finance"] == 0


def test_sharing_tells_the_business_and_the_financier(admin, outbox):
    pid, staff_phone, _fc = _financier(admin)
    phone, cook = _business()
    aid = _apply(cook, pid)
    _move(admin, aid, status="SHARED")

    told = _notes(phone, "finance_status")
    assert len(told) == 1 and "Gig Wheels" in told[0].body and told[0].link == "/scorecard"

    assert any(p == staff_phone and "New finance request" in m for p, m in outbox["whatsapp"])
    assert any(to == "ops@gigwheels.test" and "New finance request" in subj for to, subj, _ in outbox["email"])


def test_a_financier_decision_reaches_the_business_and_the_admins(admin):
    pid, _staff, fin_cookies = _financier(admin)
    phone, cook = _business()
    aid = _apply(cook, pid)
    _move(admin, aid, status="SHARED")

    r = client.patch(f"/app/api/financier/applications/{aid}", cookies=fin_cookies,
                     json={"status": "DECLINED", "decline_reason": "Income too irregular"})
    assert r.status_code == 200, r.text

    told = _notes(phone, "finance_status")[-1]
    assert "could not approve" in told.body and "Income too irregular" in told.body
    admin_note = _notes(ADMIN_PHONE, "finance_financier_update")[-1]
    assert "Gig Wheels" in admin_note.body and "Income too irregular" in admin_note.body


def test_a_claimed_repayment_waits_for_confirmation(admin, outbox):
    pid, staff_phone, _fc = _financier(admin)
    _phone, cook = _business()
    aid = _apply(cook, pid)
    for stage in ("SHARED", "APPROVED", "DELIVERED"):
        _move(admin, aid, status=stage)
    r = client.post(f"/app/api/admin/finance-applications/{aid}/schedule", cookies=admin,
                    json={"installments": 4, "amount_each": 100_000, "every": "WEEKLY"})
    assert r.status_code == 200, r.text

    r = client.post(f"/app/api/my-applications/{aid}/repayments", cookies=cook,
                    json={"installment_no": 1, "amount": 100_000})
    assert r.status_code == 200, r.text

    note = _notes(ADMIN_PHONE, "finance_repayment")[-1]
    assert "N100,000" in note.body and "installment 1" in note.body
    assert any(p == staff_phone and "Repayment to confirm" in m for p, m in outbox["whatsapp"])
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["finance"] == 1

    client.post(f"/app/api/admin/finance-applications/{aid}/repayments/confirm", cookies=admin,
                json={"installment_no": 1})
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["finance"] == 0


def test_withdrawal_tells_the_admins_and_a_financier_who_has_it(admin, outbox):
    pid, staff_phone, _fc = _financier(admin)
    _phone, cook = _business()

    unshared = _apply(cook, pid)
    client.post(f"/app/api/my-applications/{unshared}/withdraw", cookies=cook)
    assert len(_notes(ADMIN_PHONE, "finance_withdrawn")) == 1
    assert not any("withdrawn" in m.lower() for _p, m in outbox["whatsapp"])   # they never saw it

    shared = _apply(cook, pid)
    _move(admin, shared, status="SHARED")
    client.post(f"/app/api/my-applications/{shared}/withdraw", cookies=cook)
    assert len(_notes(ADMIN_PHONE, "finance_withdrawn")) == 2
    assert any(p == staff_phone and "withdrawn" in m.lower() for p, m in outbox["whatsapp"])


def test_a_failed_alert_does_not_lose_the_request(admin, monkeypatch):
    pid, _staff, _fc = _financier(admin)

    def boom(*a, **k):
        raise RuntimeError("bell is broken")
    monkeypatch.setattr("web_common._add_notification", boom)
    _phone, cook = _business()
    assert _apply(cook, pid)
