"""
Whether the business is CAC-registered: a required answer (No is a normal
answer), with the RC number required only if they say yes — and a partner may
insist on registration.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-kyc-registration-0000000")
ADMIN_PHONE = "2348090008000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from conftest import month_slot
from database import SessionLocal
from models import Customer, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 3000))

BASE_KYC = {
    "legal_name": "Adebayo Ogun", "state": "Lagos", "city": "Ikeja",
    "address": "12 Allen Avenue", "id_type": "NIN", "id_number": "12345678901",
}


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


@pytest.fixture
def admin():
    return _register(ADMIN_PHONE, "App Admin")


def _business():
    phone = f"234861{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(3):
            db.add(Transaction(customer_id=cust.id, type="SALE", amount=200_000,
                               recorded_by_id=u.id,
                               created_at=month_slot(m)))
        db.commit()
    finally:
        db.close()
    return phone, cookies


def _partner(admin, name, requires_registered=False):
    body = {"name": name, "asset_types": ["motorcycle"],
            "eligibility": {"requires_registered_business": 1} if requires_registered else {},
            "commission_type": "FLAT_PER_DEAL", "commission_value": 10_000,
            "commission_due_on": "ON_DELIVERY"}
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _apply(cook, pid):
    return client.post(f"/app/api/finance-offers/{pid}/apply", cookies=cook,
                       json={"consent": True, "asset_requested": "motorcycle", "asset_value": 800_000})


def test_the_registration_answer_is_required():
    _phone, cook = _business()
    r = client.post("/app/api/kyc", cookies=cook, json=BASE_KYC)
    assert r.json()["complete"] is False
    assert [m["key"] for m in r.json()["missing"]] == ["is_registered"]


def test_not_registered_is_a_complete_answer():
    _phone, cook = _business()
    r = client.post("/app/api/kyc", cookies=cook, json={**BASE_KYC, "is_registered": False})
    assert r.status_code == 200, r.text
    assert r.json()["complete"] is True and r.json()["kyc"]["is_registered"] is False


def test_saying_registered_requires_the_rc_number():
    _phone, cook = _business()
    r = client.post("/app/api/kyc", cookies=cook, json={**BASE_KYC, "is_registered": True})
    assert r.json()["complete"] is False
    assert "registration_number" in [m["key"] for m in r.json()["missing"]]

    done = client.post("/app/api/kyc", cookies=cook, json={
        "registration_number": "RC1234567", "registered_name": "Ade Rides Ltd"})
    assert done.json()["complete"] is True
    assert done.json()["kyc"]["registration_number"] == "RC1234567"


def test_a_partner_can_require_registration(admin):
    _phone, cook = _business()
    client.post("/app/api/kyc", cookies=cook, json={**BASE_KYC, "is_registered": False})
    open_to_all = _partner(admin, "Open Co")
    registered_only = _partner(admin, "Formal Co", requires_registered=True)

    offers = {o["name"]: o for o in client.get("/app/api/finance-offers", cookies=cook).json()["offers"]}
    assert offers["Open Co"]["eligible"] is True
    assert offers["Formal Co"]["eligible"] is False
    check = next(c for c in offers["Formal Co"]["checks"] if "registered" in c["requirement"])
    assert check["actual"] == "No" and check["passed"] is False

    assert _apply(cook, open_to_all).status_code == 200
    refused = _apply(cook, registered_only)
    assert refused.status_code == 400 and "registered businesses" in refused.json()["detail"]


def test_registering_later_unlocks_that_partner(admin):
    _phone, cook = _business()
    client.post("/app/api/kyc", cookies=cook, json={**BASE_KYC, "is_registered": False})
    pid = _partner(admin, "Formal Only", requires_registered=True)
    assert _apply(cook, pid).status_code == 400

    client.post("/app/api/kyc", cookies=cook,
                json={"is_registered": True, "registration_number": "BN9988776"})
    assert _apply(cook, pid).status_code == 200
