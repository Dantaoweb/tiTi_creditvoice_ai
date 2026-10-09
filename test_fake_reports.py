"""
Shops warning each other about suspected fakes.

A report reaches the admins; nothing reaches other shops until an admin
confirms it. Confirming warns every other shop stocking the barcode or buying
from the same supplier (by phone), flags the barcode at the till, and tells
the reporter. The reporter's identity is never sent to other shops.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-fake-reports-0000000000")
ADMIN_PHONE = "2348090044100"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, FakeReport, InventoryItem, Supplier

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
CODE = "6151100099995"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: None)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    db = SessionLocal()
    try:
        db.query(FakeReport).delete()
        db.query(AppNotification).delete()
        db.query(InventoryItem).filter(InventoryItem.barcode == CODE).delete()
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


def _shop(name="Ade Stores"):
    phone = f"2348071{next(_seq):06d}"
    return phone, _register(phone, name)


def _item(phone, code=CODE, name="peak milk 400g"):
    db = SessionLocal()
    try:
        it = InventoryItem(owner_phone=phone, name=name, quantity=10, selling_price=900, barcode=code)
        db.add(it); db.commit()
        return it.id
    finally:
        db.close()


def _supplier(phone, supplier_phone="08031112222", name="Mama Joy Wholesale"):
    db = SessionLocal()
    try:
        s = Supplier(owner_phone=phone, name=name, phone=supplier_phone)
        db.add(s); db.commit()
        return s.id
    finally:
        db.close()


def _notes(phone, event_type):
    db = SessionLocal()
    try:
        return (db.query(AppNotification)
                .filter(AppNotification.owner_phone == phone, AppNotification.event_type == event_type)
                .order_by(AppNotification.id.asc()).all())
    finally:
        db.close()


def _report(cook, item_id, **extra):
    r = client.post("/app/api/fake-reports", cookies=cook, json={
        "item_id": item_id, "product_name": "peak milk 400g",
        "reason": "Label spelt 'Paek', seal broken", **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_a_report_alerts_the_admins_and_counts(admin):
    phone, cook = _shop()
    _report(cook, _item(phone))
    notes = _notes(ADMIN_PHONE, "fake_report")
    assert len(notes) == 1 and notes[0].link == "/admin?tab=Fakes"
    assert "Ade Stores" in notes[0].body and CODE in notes[0].body and "Paek" in notes[0].body
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["fakes"] == 1


def test_nothing_reaches_other_shops_before_an_admin_confirms(admin):
    reporter, cook = _shop()
    other, _c = _shop("Bola Mart")
    _item(other)
    _report(cook, _item(reporter))
    assert _notes(other, "fake_warning") == []


def test_confirming_warns_shops_by_barcode_and_by_supplier(admin):
    reporter, cook = _shop()
    sup = _supplier(reporter)
    same_barcode, _c1 = _shop("Bola Mart")
    _item(same_barcode)
    same_supplier, _c2 = _shop("Chika Store")
    _supplier(same_supplier, supplier_phone="2348031112222")    # same phone, other format
    unrelated, _c3 = _shop("Dayo Shop")
    _item(unrelated, code="6151100011112", name="milo")

    rid = _report(cook, _item(reporter), supplier_id=sup)
    listed = client.get("/app/api/admin/fake-reports", cookies=admin).json()["reports"][0]
    assert listed["would_warn"] == 2

    r = client.patch(f"/app/api/admin/fake-reports/{rid}", cookies=admin,
                     json={"status": "CONFIRMED", "admin_note": "Look for 'Paek' on the label"})
    assert r.status_code == 200, r.text
    assert r.json()["shops_warned"] == 2

    for warned in (same_barcode, same_supplier):
        note = _notes(warned, "fake_warning")
        assert len(note) == 1 and "Paek" in note[0].body
        assert "Ade Stores" not in note[0].body                 # reporter stays anonymous
    assert _notes(unrelated, "fake_warning") == []
    assert len(_notes(reporter, "fake_report_outcome")) == 1
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["fakes"] == 0


def test_a_confirmed_barcode_is_flagged_at_the_till(admin):
    reporter, cook = _shop()
    rid = _report(cook, _item(reporter))
    client.patch(f"/app/api/admin/fake-reports/{rid}", cookies=admin, json={"status": "CONFIRMED"})

    _other, other_cook = _shop("Bola Mart")
    got = client.get("/app/api/barcodes/insight", params={"code": CODE}, cookies=other_cook).json()
    assert any(w["kind"] == "reported" for w in got["warnings"])


def test_dismissing_tells_the_reporter_and_warns_nobody(admin):
    reporter, cook = _shop()
    other, _c = _shop("Bola Mart")
    _item(other)
    rid = _report(cook, _item(reporter))
    client.patch(f"/app/api/admin/fake-reports/{rid}", cookies=admin,
                 json={"status": "DISMISSED", "admin_note": "That's the new packaging design"})
    assert _notes(other, "fake_warning") == []
    outcome = _notes(reporter, "fake_report_outcome")
    assert len(outcome) == 1 and "new packaging design" in outcome[0].body
    got = client.get("/app/api/barcodes/insight", params={"code": CODE}, cookies=cook).json()
    assert not any(w["kind"] == "reported" for w in got["warnings"])


def test_a_report_is_decided_once(admin):
    reporter, cook = _shop()
    rid = _report(cook, _item(reporter))
    client.patch(f"/app/api/admin/fake-reports/{rid}", cookies=admin, json={"status": "DISMISSED"})
    r = client.patch(f"/app/api/admin/fake-reports/{rid}", cookies=admin, json={"status": "CONFIRMED"})
    assert r.status_code == 409


def test_only_admins_review_and_shops_only_report_their_own_items(admin):
    reporter, cook = _shop()
    rid = _report(cook, _item(reporter))
    assert client.get("/app/api/admin/fake-reports", cookies=cook).status_code == 403
    assert client.patch(f"/app/api/admin/fake-reports/{rid}", cookies=cook,
                        json={"status": "CONFIRMED"}).status_code == 403
    other, other_cook = _shop("Bola Mart")
    r = client.post("/app/api/fake-reports", cookies=other_cook, json={
        "item_id": _item(reporter, code="6151100022223"), "product_name": "x", "reason": "y"})
    assert r.status_code == 404


def test_a_reason_is_required():
    phone, cook = _shop()
    r = client.post("/app/api/fake-reports", cookies=cook,
                    json={"item_id": _item(phone), "product_name": "peak", "reason": "  "})
    assert r.status_code == 400
