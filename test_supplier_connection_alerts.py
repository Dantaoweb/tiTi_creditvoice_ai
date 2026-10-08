"""
Supplier connection requests: admins see each one, a request the supplier
ignores is chased, and a bad rating is flagged.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-supplier-connections-00000")
ADMIN_PHONE = "2348090055100"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import (
    AppNotification, SupplierContactMessage, SupplierRating, User, VerifiedSupplier,
    VerifiedSupplierProduct, utcnow,
)

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
        for model in (SupplierRating, SupplierContactMessage, VerifiedSupplierProduct,
                      VerifiedSupplier, AppNotification):
            db.query(model).delete()
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


def _supplier():
    phone = f"2348076{next(_seq):06d}"
    cookies = _register(phone, "Dangote Depot")
    db = SessionLocal()
    try:
        vs = VerifiedSupplier(id=str(uuid.uuid4()), owner_phone=phone, supplier_type="wholesaler",
                              verification_status="approved")
        db.add(vs); db.commit()
        return phone, cookies, vs.id
    finally:
        db.close()


def _buyer():
    phone = f"2348075{next(_seq):06d}"
    return phone, _register(phone, "Mama Bola Stores")


def _contact(cookies, sid):
    r = client.post(f"/app/api/verified-suppliers/{sid}/contact", cookies=cookies,
                    json={"product_interest": "Cement", "message": "Need 50 bags"})
    assert r.status_code == 200, r.text


def _notes(phone, event_type):
    db = SessionLocal()
    try:
        return (db.query(AppNotification)
                .filter(AppNotification.owner_phone == phone, AppNotification.event_type == event_type)
                .order_by(AppNotification.id.asc()).all())
    finally:
        db.close()


def _age_requests(days):
    db = SessionLocal()
    try:
        for m in db.query(SupplierContactMessage).all():
            m.created_at = utcnow() - timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _run_check():
    from supplier_alerts import check_unanswered_supplier_requests
    db = SessionLocal()
    try:
        check_unanswered_supplier_requests(db)
    finally:
        db.close()


def test_each_request_alerts_the_admins_and_opens_suppliers(admin):
    _sp, _sc, sid = _supplier()
    _bp, buyer = _buyer()
    _contact(buyer, sid)
    notes = _notes(ADMIN_PHONE, "supplier_enquiry_admin")
    assert len(notes) == 1
    assert notes[0].link == "/admin?tab=Suppliers"
    assert "Mama Bola Stores" in notes[0].body and "Dangote Depot" in notes[0].body


def test_an_unanswered_request_is_chased_once_and_counted(admin):
    supplier_phone, _sc, sid = _supplier()
    _bp, buyer = _buyer()
    _contact(buyer, sid)

    _run_check()                                     # fresh: nothing to chase
    assert _notes(supplier_phone, "supplier_enquiry_reminder") == []
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["suppliers"] == 0

    _age_requests(4)
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["suppliers"] == 1
    _run_check()
    _run_check()                                     # a second cycle must not repeat it
    assert len(_notes(supplier_phone, "supplier_enquiry_reminder")) == 1
    stale = _notes(ADMIN_PHONE, "supplier_enquiry_stale")
    assert len(stale) == 1 and "Dangote Depot" in stale[0].body


def test_answering_clears_the_count(admin):
    _sp, supplier, sid = _supplier()
    _bp, buyer = _buyer()
    _contact(buyer, sid)
    _age_requests(4)
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["suppliers"] == 1

    db = SessionLocal()
    msg_id = db.query(SupplierContactMessage).first().id
    db.close()
    r = client.post(f"/app/api/verified-suppliers/connections/{msg_id}/respond", cookies=supplier,
                    json={"action": "accept"})
    assert r.status_code == 200, r.text
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["suppliers"] == 0


def test_a_bad_rating_is_flagged_once(admin):
    _sp, supplier, sid = _supplier()
    _bp, buyer = _buyer()
    _contact(buyer, sid)
    db = SessionLocal()
    msg_id = db.query(SupplierContactMessage).first().id
    db.close()
    client.post(f"/app/api/verified-suppliers/connections/{msg_id}/respond", cookies=supplier,
                json={"action": "accept"})

    url = f"/app/api/verified-suppliers/{sid}/rate"
    assert client.post(url, cookies=buyer, json={"rating": 5}).status_code == 200
    assert _notes(ADMIN_PHONE, "supplier_low_rating") == []

    client.post(url, cookies=buyer, json={"rating": 1, "review": "Sold me wet cement"})
    flagged = _notes(ADMIN_PHONE, "supplier_low_rating")
    assert len(flagged) == 1
    assert "Sold me wet cement" in flagged[0].body and "1/5" in flagged[0].title

    client.post(url, cookies=buyer, json={"rating": 2})   # still low: no new alert
    assert len(_notes(ADMIN_PHONE, "supplier_low_rating")) == 1
