"""
Identity details are asked when applying for financing — never at sign-up — and
a partner is only offered where it actually operates.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-kyc-coverage-00000000000")
ADMIN_PHONE = "2348090007000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
from database import SessionLocal
from models import BusinessKyc, Customer, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 3000))

FULL_KYC = {
    "legal_name": "Adebayo Ogun", "state": "Lagos", "city": "Ikeja",
    "address": "12 Allen Avenue", "id_type": "NIN", "id_number": "12345678901",
    "is_registered": False,
}


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    db = SessionLocal()
    try:
        bs.save_config(db, bs.DEFAULT_CONFIG, updated_by="test", note="baseline")
    finally:
        db.close()
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
    phone = f"234860{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(3):
            for i in range(4):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=100_000,
                                   recorded_by_id=u.id,
                                   created_at=utcnow() - timedelta(days=30 * m + i * 5 + 1)))
        db.commit()
    finally:
        db.close()
    return phone, cookies


def _partner(admin, name="Wheels", nationwide=True, states=None):
    body = {"name": name, "asset_types": ["motorcycle"], "eligibility": {},
            "nationwide": nationwide, "states_covered": states or [],
            "commission_type": "FLAT_PER_DEAL", "commission_value": 10_000,
            "commission_due_on": "ON_DELIVERY"}
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _apply(cook, pid):
    return client.post(f"/app/api/finance-offers/{pid}/apply", cookies=cook,
                       json={"consent": True, "asset_requested": "motorcycle",
                             "asset_value": 900_000})


# ── Nothing is asked at sign-up ──────────────────────────────────────────────

def test_signup_asks_nothing_and_the_gaps_are_named_when_applying(admin):
    _phone, cook = _business()
    mine = client.get("/app/api/kyc", cookies=cook).json()
    assert mine["complete"] is False and mine["kyc"] is None
    assert {m["key"] for m in mine["missing"]} == {
        "legal_name", "state", "city", "address", "id_type", "id_number", "is_registered"}

    pid = _partner(admin)["id"]
    blocked = _apply(cook, pid)
    assert blocked.status_code == 400
    detail = blocked.json()["detail"]
    assert "before applying" in detail["message"]
    assert {m["key"] for m in detail["kyc_required"]} == {
        "legal_name", "state", "city", "address", "id_type", "id_number", "is_registered"}

    # The offers list says the same thing, so the page can send them to the form.
    offers = client.get("/app/api/finance-offers", cookies=cook).json()
    assert offers["kyc_complete"] is False and len(offers["kyc_missing"]) == 7


def test_completing_the_details_unlocks_applying(admin):
    _phone, cook = _business()
    pid = _partner(admin)["id"]
    saved = client.post("/app/api/kyc", cookies=cook, json=FULL_KYC)
    assert saved.status_code == 200, saved.text
    assert saved.json()["complete"] is True and saved.json()["missing"] == []
    assert saved.json()["kyc"]["state"] == "Lagos"

    applied = _apply(cook, pid)
    assert applied.status_code == 200, applied.text

    # The details are frozen onto the application for the partner to verify.
    detail = client.get(f"/app/api/admin/finance-applications/{applied.json()['id']}",
                        cookies=admin).json()
    assert detail["kyc"]["legal_name"] == "Adebayo Ogun"
    assert detail["kyc"]["id_number"] == "12345678901"


def test_partial_details_still_block_and_say_what_is_left(admin):
    _phone, cook = _business()
    pid = _partner(admin)["id"]
    client.post("/app/api/kyc", cookies=cook, json={"legal_name": "Ade", "state": "Oyo"})
    blocked = _apply(cook, pid)
    assert blocked.status_code == 400
    assert {m["key"] for m in blocked.json()["detail"]["kyc_required"]} == {
        "city", "address", "id_type", "id_number", "is_registered"}


def test_bad_state_and_bad_id_type_are_refused(admin):
    _phone, cook = _business()
    bad_state = client.post("/app/api/kyc", cookies=cook, json={**FULL_KYC, "state": "Lagoss"})
    assert bad_state.status_code == 400 and "not a Nigerian state" in bad_state.json()["detail"]
    bad_id = client.post("/app/api/kyc", cookies=cook, json={**FULL_KYC, "id_type": "BVN"})
    assert bad_id.status_code == 400 and "ID type" in bad_id.json()["detail"]


def test_state_is_stored_in_its_proper_casing(admin):
    _phone, cook = _business()
    r = client.post("/app/api/kyc", cookies=cook, json={**FULL_KYC, "state": "  lagos "})
    assert r.json()["kyc"]["state"] == "Lagos"


# ── Coverage ─────────────────────────────────────────────────────────────────

def test_a_partner_outside_the_business_state_cannot_be_applied_to(admin):
    _phone, cook = _business()
    client.post("/app/api/kyc", cookies=cook, json=FULL_KYC)      # Lagos
    local = _partner(admin, "Lagos Only", nationwide=False, states=["Lagos", "Ogun"])
    far = _partner(admin, "North Only", nationwide=False, states=["Kano"])
    everywhere = _partner(admin, "All Nigeria", nationwide=True)

    offers = {o["name"]: o for o in client.get("/app/api/finance-offers", cookies=cook).json()["offers"]}
    assert offers["Lagos Only"]["covered"] is True
    assert offers["Lagos Only"]["coverage"] == "Lagos, Ogun"
    assert offers["North Only"]["covered"] is False
    assert offers["All Nigeria"]["covered"] is True and offers["All Nigeria"]["coverage"] == "Nationwide"

    assert _apply(cook, local["id"]).status_code == 200
    refused = _apply(cook, far["id"])
    assert refused.status_code == 400
    assert "does not operate in Lagos" in refused.json()["detail"]
    assert "Kano" in refused.json()["detail"]


def test_coverage_states_are_validated_on_the_partner(admin):
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json={
        "name": "Typo Co", "nationwide": False, "states_covered": ["Lagoss"],
        "commission_type": "FLAT_PER_DEAL", "commission_value": 1, "commission_due_on": "ON_DELIVERY"})
    assert r.status_code == 400 and "not a Nigerian state" in r.json()["detail"]

    ok = _partner(admin, "Cased Co", nationwide=False, states=["  oyo ", "LAGOS"])
    assert ok["states_covered"] == ["Oyo", "Lagos"]      # stored properly cased


def test_a_partner_with_no_states_recorded_is_not_hidden(admin):
    _phone, cook = _business()
    client.post("/app/api/kyc", cookies=cook, json=FULL_KYC)
    _partner(admin, "Unset Co", nationwide=False, states=[])
    offers = {o["name"]: o for o in client.get("/app/api/finance-offers", cookies=cook).json()["offers"]}
    assert offers["Unset Co"]["covered"] is True


# ── Privacy ──────────────────────────────────────────────────────────────────

def test_the_id_number_is_masked_outside_the_owner_and_admin(admin):
    from business_kyc import get_kyc, kyc_dict
    _phone, cook = _business()
    client.post("/app/api/kyc", cookies=cook, json=FULL_KYC)
    db = SessionLocal()
    try:
        masked = kyc_dict(get_kyc(db, _phone))     # default: not the owner's own view
        assert masked["id_number"] == "•••••••8901"
    finally:
        db.close()
    # The owner sees their own in full.
    assert client.get("/app/api/kyc", cookies=cook).json()["kyc"]["id_number"] == "12345678901"


def test_another_business_cannot_read_your_details(admin):
    _phone, cook = _business()
    client.post("/app/api/kyc", cookies=cook, json=FULL_KYC)
    _other, other_cook = _business()
    other = client.get("/app/api/kyc", cookies=other_cook).json()
    assert other["kyc"] is None            # their own record, not this one's

    db = SessionLocal()
    try:
        assert db.query(BusinessKyc).filter(BusinessKyc.owner_phone == _phone).count() == 1
    finally:
        db.close()
