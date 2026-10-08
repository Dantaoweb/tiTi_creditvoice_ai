"""
Supplier directory applications reach the admins, and the decision reaches the
applicant.

An applicant is told "Admin will review within 48 hours", so an application no
admin is told about breaks that promise. Every admin is alerted — including one
granted from the app, and one whose account stores the phone in local format —
and the alert opens the Suppliers tab. A re-application shows what was wrong
the first time.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-supplier-alerts-0000000000")
ADMIN_PHONE = "2348090066000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppAdminRole, AppNotification, User, VerifiedSupplier, VerifiedSupplierProduct

client = TestClient(app, raise_server_exceptions=True)

_seq = iter(range(100, 999))

APPLICATION = {
    "supplier_type": "wholesaler",
    "bio": "Rice and beans in bulk",
    "states_covered": ["Lagos"],
    "products": [{"product_name": "Rice", "category": "Grains"}],
}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: None)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    db = SessionLocal()
    try:
        db.query(VerifiedSupplierProduct).delete()
        db.query(VerifiedSupplier).delete()
        db.query(AppNotification).delete()
        db.commit()
    finally:
        db.close()
    yield


def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _pro_business():
    phone = f"2348077{next(_seq):06d}"
    cookies = _register(phone, "Ade Wholesale")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.subscription_plan = "PRO"
        u.subscription_status = "ACTIVE"
        db.commit()
    finally:
        db.close()
    return phone, cookies


def _notes(phone, event_type):
    db = SessionLocal()
    try:
        return (db.query(AppNotification)
                .filter(AppNotification.owner_phone == phone, AppNotification.event_type == event_type)
                .order_by(AppNotification.id.asc()).all())
    finally:
        db.close()


def _apply(cookies):
    r = client.post("/app/api/verified-suppliers/apply", cookies=cookies, json=APPLICATION)
    assert r.status_code == 200, r.text


def _supplier_id(phone):
    db = SessionLocal()
    try:
        return db.query(VerifiedSupplier).filter(VerifiedSupplier.owner_phone == phone).first().id
    finally:
        db.close()


def test_every_admin_is_told_and_the_alert_opens_the_suppliers_tab():
    admin = _register(ADMIN_PHONE, "App Admin")
    # An admin granted from the app, whose account uses the local 0… format.
    db = SessionLocal()
    try:
        db.add(AppAdminRole(phone="2348090066111", role="APP_ADMIN", is_active=True))
        db.commit()
    finally:
        db.close()
    _register("08090066111", "Second Admin")

    phone, cookies = _pro_business()
    _apply(cookies)

    first = _notes(ADMIN_PHONE, "supplier_application")
    assert len(first) == 1
    assert first[0].link == "/admin?tab=Suppliers"
    assert "Ade Wholesale" in first[0].body and "Wholesaler" in first[0].body
    second = _notes("08090066111", "supplier_application")
    assert len(second) == 1                         # reached under the phone they log in with

    counts = client.get("/app/api/admin/pending-counts", cookies=admin).json()
    assert counts["suppliers"] == 1 and counts["total"] >= 1


def test_a_denied_admin_is_not_told():
    _register(ADMIN_PHONE, "App Admin")
    db = SessionLocal()
    try:
        db.add(AppAdminRole(phone=ADMIN_PHONE, role="APP_ADMIN", is_active=False))
        db.commit()
    finally:
        db.close()
    try:
        _phone, cookies = _pro_business()
        _apply(cookies)
        assert _notes(ADMIN_PHONE, "supplier_application") == []
    finally:
        db = SessionLocal()
        db.query(AppAdminRole).filter(AppAdminRole.phone == ADMIN_PHONE).delete()
        db.commit(); db.close()


def test_the_applicant_hears_the_decision():
    admin = _register(ADMIN_PHONE, "App Admin")
    phone, cookies = _pro_business()
    _apply(cookies)
    sid = _supplier_id(phone)

    client.post(f"/app/api/admin/supplier-applications/{sid}/reject", cookies=admin,
                json={"reason": "Add your CAC number"})
    rejected = _notes(phone, "supplier_rejected")
    assert len(rejected) == 1
    assert "Add your CAC number" in rejected[0].body and rejected[0].link == "/suppliers"
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["suppliers"] == 0

    _apply(cookies)
    client.post(f"/app/api/admin/supplier-applications/{sid}/approve", cookies=admin)
    assert len(_notes(phone, "supplier_approved")) == 1


def test_a_reapplication_shows_what_was_wrong_before():
    admin = _register(ADMIN_PHONE, "App Admin")
    phone, cookies = _pro_business()
    _apply(cookies)
    sid = _supplier_id(phone)
    client.post(f"/app/api/admin/supplier-applications/{sid}/reject", cookies=admin,
                json={"reason": "Add your CAC number"})

    _apply(cookies)
    alerts = _notes(ADMIN_PHONE, "supplier_application")
    assert alerts[-1].title.endswith("re-applied") or "re-applied" in alerts[-1].title.lower()

    row = client.get("/app/api/admin/supplier-applications?status=pending", cookies=admin).json()["applications"][0]
    assert row["reapplied_at"]
    assert row["previous_rejection_reason"] == "Add your CAC number"


def test_a_failed_alert_does_not_lose_the_application(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bell is broken")
    monkeypatch.setattr("web_common._add_notification", boom)
    phone, cookies = _pro_business()
    _apply(cookies)
    db = SessionLocal()
    try:
        assert db.query(VerifiedSupplier).filter(VerifiedSupplier.owner_phone == phone).count() == 1
    finally:
        db.close()
