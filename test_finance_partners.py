"""
Admin-editable finance partners + scorecard rules, and what a business sees:
its own scorecard and the offers it qualifies for.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-finance-partners-0000000")
ADMIN_PHONE = "2348090002000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import AuditLog, Customer, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))

def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


@pytest.fixture
def admin():
    return _register(ADMIN_PHONE, "App Admin")


def _business(months=4, per_month=4, amount=100_000):
    phone = f"234854{next(_seq):06d}"
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


def _partner_body(**over):
    body = {
        "name": "Gig Wheels", "contact_name": "Ops", "contact_phone": "2348000000000",
        "asset_types": ["motorcycle"], "asset_value_min": 500_000, "asset_value_max": 2_000_000,
        "eligibility": {"min_months_recorded": 3, "min_avg_monthly_sales": 200_000},
        "commission_type": "PERCENT_OF_ASSET", "commission_value": 500,
        "commission_due_on": "ON_DELIVERY", "notes": "pilot",
    }
    body.update(over)
    return body


# ── Admin: partners ──────────────────────────────────────────────────────────

def test_admin_can_create_edit_and_deactivate_a_partner(admin):
    created = client.post("/app/api/admin/finance-partners", cookies=admin, json=_partner_body())
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    assert created.json()["eligibility"]["min_months_recorded"] == 3

    edited = client.put(f"/app/api/admin/finance-partners/{pid}", cookies=admin,
                        json=_partner_body(commission_type="FLAT_PER_DEAL", commission_value=25_000,
                                           eligibility={"min_months_recorded": 6}))
    assert edited.status_code == 200, edited.text
    assert edited.json()["commission_type"] == "FLAT_PER_DEAL"
    assert edited.json()["commission_value"] == 25_000
    assert edited.json()["eligibility"] == {"min_months_recorded": 6}

    listed = client.get("/app/api/admin/finance-partners", cookies=admin).json()["partners"]
    assert any(p["id"] == pid for p in listed)

    # Every change is auditable.
    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter(
            AuditLog.action == "ADMIN_SETTINGS_CHANGE",
            AuditLog.resource.like(f"finance_partner:%{pid}"),
        ).count() >= 2
    finally:
        db.close()

    assert client.delete(f"/app/api/admin/finance-partners/{pid}", cookies=admin).status_code == 200


def test_bad_commission_terms_are_rejected(admin):
    r = client.post("/app/api/admin/finance-partners", cookies=admin,
                    json=_partner_body(commission_type="WHATEVER"))
    assert r.status_code == 400
    r = client.post("/app/api/admin/finance-partners", cookies=admin,
                    json=_partner_body(commission_value=-5))
    assert r.status_code == 400


def test_only_admins_can_manage_partners():
    _phone, cook = _business()
    assert client.get("/app/api/admin/finance-partners", cookies=cook).status_code == 403
    assert client.post("/app/api/admin/finance-partners", cookies=cook,
                       json=_partner_body()).status_code == 403
    assert client.post("/app/api/admin/scorecard-config", cookies=cook,
                       json={"config": {}}).status_code == 403


# ── Admin: scorecard rules ───────────────────────────────────────────────────

def test_admin_edits_scorecard_rules_and_sees_the_effect_before_saving(admin):
    _business(months=4, per_month=4, amount=100_000)

    live = client.get("/app/api/admin/scorecard-config", cookies=admin).json()
    assert live["config"]["components"]["sales_volume"]["weight"] == 20
    assert live["defaults"]["window_months"] == 6

    tighter = live["config"]
    tighter["components"]["sales_volume"]["full"] = 20_000_000
    preview = client.post("/app/api/admin/scorecard-preview", cookies=admin,
                          json={"config": tighter}).json()
    assert preview["live"]["businesses"] >= 1
    assert preview["proposed"]["avg_score"] <= preview["live"]["avg_score"]

    saved = client.post("/app/api/admin/scorecard-config", cookies=admin,
                        json={"config": tighter, "note": "tighter sales band"})
    assert saved.status_code == 200, saved.text
    after = client.get("/app/api/admin/scorecard-config", cookies=admin).json()
    assert after["version"] == saved.json()["version"]
    assert after["history"][0]["note"] == "tighter sales band"


def test_config_with_no_weights_is_refused(admin):
    r = client.post("/app/api/admin/scorecard-config", cookies=admin,
                    json={"config": {"components": {}}})
    assert r.status_code == 400
    r = client.post("/app/api/admin/scorecard-config", cookies=admin, json={"config": {
        "components": {"x": {"metric": "avg_monthly_sales", "weight": 0}}}})
    assert r.status_code == 400


# ── Business owner ───────────────────────────────────────────────────────────

def test_business_sees_its_own_scorecard():
    _phone, cook = _business()
    card = client.get("/app/api/scorecard", cookies=cook)
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["scored"] is True
    assert 0 <= body["score"] <= 100
    assert body["metrics"]["avg_monthly_sales"] == 400_000
    assert body["components"] and body["tier"]


def test_offers_show_each_partner_requirement_without_leaking_commission(admin):
    _phone, cook = _business(months=4, per_month=4, amount=100_000)   # 400k/month
    client.post("/app/api/admin/finance-partners", cookies=admin, json=_partner_body(
        name="Reachable", eligibility={"min_months_recorded": 2, "min_avg_monthly_sales": 100_000}))
    client.post("/app/api/admin/finance-partners", cookies=admin, json=_partner_body(
        name="Out of reach", eligibility={"min_avg_monthly_sales": 50_000_000}))
    client.post("/app/api/admin/finance-partners", cookies=admin, json=_partner_body(
        name="Paused", is_active=False))

    body = client.get("/app/api/finance-offers", cookies=cook).json()
    by_name = {o["name"]: o for o in body["offers"]}
    assert "Paused" not in by_name                     # inactive partners are hidden
    assert by_name["Reachable"]["eligible"] is True
    assert by_name["Out of reach"]["eligible"] is False
    failed = [c for c in by_name["Out of reach"]["checks"] if not c["passed"]]
    assert failed and failed[0]["requirement"] == "average monthly sales"

    # What CreditVoice earns, and the partner's contacts, stay internal.
    for offer in body["offers"]:
        assert "commission_type" not in offer and "commission_value" not in offer
        assert "contact_phone" not in offer
