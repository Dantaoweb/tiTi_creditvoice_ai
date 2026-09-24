"""
Asking to be introduced to a finance partner: explicit consent, a frozen
scorecard snapshot, and a referral code so a closed deal is attributable.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-finance-referrals-000000")
ADMIN_PHONE = "2348090003000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
from database import SessionLocal
from models import Customer, FinanceReferral, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))


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


def _business(months=4, per_month=4, amount=100_000):
    phone = f"234855{next(_seq):06d}"
    cookies = _register(phone, "Ade Stores")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=30 * (months + 2))
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(months):
            for i in range(per_month):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=amount,
                                   recorded_by_id=u.id,
                                   created_at=utcnow() - timedelta(days=30 * m + i * 5 + 1)))
        db.commit()
    finally:
        db.close()
    return phone, cookies


def _partner(admin, **over):
    body = {
        "name": "Gig Wheels", "asset_types": ["motorcycle"],
        "eligibility": {"min_months_recorded": 2},
        "commission_type": "PERCENT_OF_ASSET", "commission_value": 500,
        "commission_due_on": "ON_DELIVERY",
    }
    body.update(over)
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _apply(cook, pid, **over):
    body = {"consent": True, "asset_requested": "motorcycle", "asset_value": 1_200_000,
            "note": "for deliveries"}
    body.update(over)
    return client.post(f"/app/api/finance-offers/{pid}/apply", cookies=cook, json=body)


def test_apply_records_consent_snapshot_and_code(admin):
    _phone, cook = _business()
    pid = _partner(admin)
    card = client.get("/app/api/scorecard", cookies=cook).json()

    r = _apply(cook, pid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["referral_code"].startswith("CV-") and len(body["referral_code"]) == 8
    assert body["status"] == "SUBMITTED"
    assert body["consent_given_at"] is not None
    assert body["asset_value"] == 1_200_000
    # The evidence is frozen as it stood at application time.
    assert body["score"] == int(card["score"])
    assert body["tier"] == card["tier"]
    assert body["config_version"] == card["config_version"]

    db = SessionLocal()
    try:
        stored = json.loads(db.query(FinanceReferral).filter(
            FinanceReferral.id == body["id"]).first().snapshot_json)
        assert stored["metrics"]["avg_monthly_sales"] == card["metrics"]["avg_monthly_sales"]
    finally:
        db.close()


def test_snapshot_does_not_move_when_rules_or_trading_change_later(admin):
    _phone, cook = _business()
    pid = _partner(admin)
    before = _apply(cook, pid).json()

    # Re-tune the rules AND record a burst of new sales.
    db = SessionLocal()
    try:
        cfg = json.loads(json.dumps(bs.DEFAULT_CONFIG))
        cfg["components"]["sales_volume"]["full"] = 50_000_000
        bs.save_config(db, cfg, updated_by="admin", note="tighter")
        u = db.query(User).filter(User.phone == _phone).first()
        for i in range(30):
            db.add(Transaction(type="SALE", amount=900_000, recorded_by_id=u.id,
                               created_at=utcnow() - timedelta(hours=i)))
        db.commit()
    finally:
        db.close()

    after = client.get("/app/api/my-referrals", cookies=cook).json()["referrals"][0]
    assert after["score"] == before["score"]
    assert after["config_version"] == before["config_version"]
    # …while a fresh scorecard has moved.
    assert client.get("/app/api/scorecard", cookies=cook).json()["score"] != before["score"]


def test_consent_is_required(admin):
    _phone, cook = _business()
    pid = _partner(admin)
    r = _apply(cook, pid, consent=False)
    assert r.status_code == 400 and "consent" in r.json()["detail"].lower()
    assert client.get("/app/api/my-referrals", cookies=cook).json()["referrals"] == []


def test_one_open_request_per_partner_and_reapply_after_withdrawing(admin):
    _phone, cook = _business()
    pid = _partner(admin)
    first = _apply(cook, pid).json()
    again = _apply(cook, pid)
    assert again.status_code == 400 and first["referral_code"] in again.json()["detail"]

    w = client.post(f"/app/api/my-referrals/{first['id']}/withdraw", cookies=cook)
    assert w.status_code == 200, w.text
    assert w.json()["status"] == "WITHDRAWN"
    assert w.json()["consent_revoked_at"] is not None

    assert _apply(cook, pid).status_code == 200      # free to try again
    assert len(client.get("/app/api/my-referrals", cookies=cook).json()["referrals"]) == 2


def test_cannot_withdraw_once_approved_or_delivered(admin):
    _phone, cook = _business()
    pid = _partner(admin)
    rid = _apply(cook, pid).json()["id"]
    db = SessionLocal()
    try:
        db.query(FinanceReferral).filter(FinanceReferral.id == rid).first().status = "APPROVED"
        db.commit()
    finally:
        db.close()
    r = client.post(f"/app/api/my-referrals/{rid}/withdraw", cookies=cook)
    assert r.status_code == 400 and "approved" in r.json()["detail"].lower()


def test_inactive_partner_cannot_be_applied_to_and_offers_show_applied_status(admin):
    _phone, cook = _business()
    pid = _partner(admin)
    paused = _partner(admin, name="Paused Co", is_active=False)
    assert _apply(cook, paused).status_code == 404

    _apply(cook, pid)
    offers = {o["name"]: o for o in client.get("/app/api/finance-offers", cookies=cook).json()["offers"]}
    assert offers["Gig Wheels"]["applied_status"] == "SUBMITTED"


def test_another_business_cannot_withdraw_someone_elses_request(admin):
    _phone, cook = _business()
    pid = _partner(admin)
    rid = _apply(cook, pid).json()["id"]
    _other, other_cook = _business()
    r = client.post(f"/app/api/my-referrals/{rid}/withdraw", cookies=other_cook)
    assert r.status_code == 404
