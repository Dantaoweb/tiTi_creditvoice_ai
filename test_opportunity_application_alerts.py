"""
Opportunity applications reach the admins, and a decision reaches the applicant.

An application nobody is told about waits until someone happens to open the
tab; a decision the applicant isn't told about only exists if they go looking.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-opportunity-alerts-00000000")
ADMIN_PHONE = "2348090077000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, Opportunity, OpportunityApplication

client = TestClient(app, raise_server_exceptions=True)

_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: None)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    db = SessionLocal()
    try:
        db.query(OpportunityApplication).delete()
        db.query(Opportunity).delete()
        db.query(AppNotification).delete()
        db.commit()
    finally:
        db.close()
    yield


def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


@pytest.fixture
def admin():
    return _register(ADMIN_PHONE, "App Admin")


def _opportunity(admin):
    r = client.post("/app/api/admin/opportunities", cookies=admin, json={
        "title": "Women in Trade Grant", "description": "A grant", "category": "grant",
        "partner_name": "Bank of Industry",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _applicant():
    phone = f"2348078{next(_seq):06d}"
    return phone, _register(phone, "Mama Bola Stores")


def _notes(phone, event_type):
    db = SessionLocal()
    try:
        return (db.query(AppNotification)
                .filter(AppNotification.owner_phone == phone, AppNotification.event_type == event_type)
                .order_by(AppNotification.id.asc()).all())
    finally:
        db.close()


def _apply(opp_id, cookies):
    r = client.post(f"/app/api/opportunities/{opp_id}/apply", cookies=cookies,
                    json={"answers": {"Years in business": "3"}})
    assert r.status_code == 200, r.text


def _application_id(phone):
    db = SessionLocal()
    try:
        return db.query(OpportunityApplication).filter(
            OpportunityApplication.applicant_phone == phone).first().id
    finally:
        db.close()


def test_admins_are_told_and_the_alert_opens_the_opportunities_tab(admin):
    opp_id = _opportunity(admin)
    _phone, cookies = _applicant()
    _apply(opp_id, cookies)

    notes = _notes(ADMIN_PHONE, "opportunity_application")
    assert len(notes) == 1
    assert notes[0].link == "/admin?tab=Opportunities"
    assert "Mama Bola Stores" in notes[0].body
    assert "Women in Trade Grant" in notes[0].body and "Bank of Industry" in notes[0].body


def test_new_applications_are_counted_until_someone_moves_them(admin):
    opp_id = _opportunity(admin)
    phone, cookies = _applicant()
    _apply(opp_id, cookies)

    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["opportunities"] == 1
    listed = client.get("/app/api/admin/opportunities", cookies=admin).json()["opportunities"][0]
    assert listed["application_count"] == 1 and listed["new_count"] == 1

    client.patch(f"/app/api/admin/opportunity-applications/{_application_id(phone)}/status",
                 cookies=admin, json={"status": "reviewing"})
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["opportunities"] == 0
    listed = client.get("/app/api/admin/opportunities", cookies=admin).json()["opportunities"][0]
    assert listed["application_count"] == 1 and listed["new_count"] == 0


def test_the_applicant_hears_each_decision_with_the_note(admin):
    opp_id = _opportunity(admin)
    phone, cookies = _applicant()
    _apply(opp_id, cookies)
    url = f"/app/api/admin/opportunity-applications/{_application_id(phone)}/status"

    client.patch(url, cookies=admin, json={"status": "approved", "admin_notes": "Bring your CAC"})
    notes = _notes(phone, "opportunity_status")
    assert len(notes) == 1
    assert "approved" in notes[0].title.lower()
    assert "Women in Trade Grant" in notes[0].body and "Bring your CAC" in notes[0].body
    assert notes[0].link == "/opportunities"

    # Only editing the note, not moving it, tells them nothing new.
    client.patch(url, cookies=admin, json={"status": "approved", "admin_notes": "Typo fixed"})
    assert len(_notes(phone, "opportunity_status")) == 1


def test_a_failed_alert_does_not_lose_the_application(admin, monkeypatch):
    opp_id = _opportunity(admin)

    def boom(*a, **k):
        raise RuntimeError("bell is broken")
    monkeypatch.setattr("web_common._add_notification", boom)
    phone, cookies = _applicant()
    _apply(opp_id, cookies)
    assert _application_id(phone)
