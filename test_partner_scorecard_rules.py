"""
Each financier scores by its own rules. A motorcycle financier may care about
daily takings and repayment; an equipment financier about margin and suppliers.
Partner overrides layer over the global rules; a partner that sets none scores
applicants exactly the standard way.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-partner-rules-00000000000")
ADMIN_PHONE = "2348090006000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
from database import SessionLocal
from models import Customer, Supplier, SupplierPurchase, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 3000))


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


def _business(with_suppliers=False):
    phone = f"234859{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(4):
            for i in range(6):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=100_000,
                                   recorded_by_id=u.id,
                                   created_at=utcnow() - timedelta(days=30 * m + i * 4 + 1)))
        if with_suppliers:
            sup = Supplier(name="Depot", owner_phone=phone)
            db.add(sup); db.flush()
            db.add(SupplierPurchase(supplier_id=sup.id, owner_phone=phone, product="parts",
                                    total=100_000, paid_amount=40_000))   # poor payer
        db.commit()
    finally:
        db.close()
    return phone, cookies


def _partner(admin, name, overrides=None, eligibility=None):
    body = {
        "name": name, "asset_types": ["motorcycle"],
        "eligibility": eligibility or {},
        "scorecard_overrides": overrides or {},
        "commission_type": "FLAT_PER_DEAL", "commission_value": 10_000,
        "commission_due_on": "ON_DELIVERY",
    }
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _offers(cook):
    r = client.get("/app/api/finance-offers", cookies=cook)
    assert r.status_code == 200, r.text
    return {o["name"]: o for o in r.json()["offers"]}


def test_partner_without_overrides_scores_the_standard_way(admin):
    _phone, cook = _business()
    _partner(admin, "Standard Co")
    card = client.get("/app/api/scorecard", cookies=cook).json()
    offer = _offers(cook)["Standard Co"]
    assert offer["partner_rules"] is False
    assert offer["score"] == card["score"]


def test_two_partners_can_score_the_same_business_differently(admin):
    _phone, cook = _business(with_suppliers=True)
    # One cares only about takings and consistency…
    _partner(admin, "Takings First", overrides={"components": {
        "sales_volume": {"weight": 60},
        "consistency": {"weight": 40},
        "margin": {"enabled": False},
        "supplier_discipline": {"enabled": False},
        "repeat_customers": {"enabled": False},
        "collections": {"enabled": False},
        "sales_floor": {"enabled": False},
        "tenure": {"enabled": False},
    }})
    # …the other leans hard on paying suppliers, which this business does badly.
    _partner(admin, "Suppliers First", overrides={"components": {
        "supplier_discipline": {"weight": 80},
        "sales_volume": {"weight": 20},
        "margin": {"enabled": False},
        "repeat_customers": {"enabled": False},
        "collections": {"enabled": False},
        "sales_floor": {"enabled": False},
        "tenure": {"enabled": False},
        "consistency": {"enabled": False},
    }})

    offers = _offers(cook)
    assert offers["Takings First"]["partner_rules"] is True
    assert offers["Suppliers First"]["partner_rules"] is True
    assert offers["Takings First"]["score"] > offers["Suppliers First"]["score"]


def test_a_partner_can_set_its_own_tiers_and_minimum_history(admin):
    _phone, cook = _business()
    _partner(admin, "Own Tiers", overrides={
        "min_months_recorded": 24,          # demands two years
        "tiers": [{"name": "Watchlist", "min_score": 0}, {"name": "Preferred", "min_score": 99}],
    })
    offer = _offers(cook)["Own Tiers"]
    assert offer["score"] is None           # not enough history for THIS partner
    assert offer["tier"] == "Unrated"

    # The business is still scored normally elsewhere.
    assert client.get("/app/api/scorecard", cookies=cook).json()["scored"] is True


def test_eligibility_is_judged_against_the_partners_own_score(admin):
    _phone, cook = _business(with_suppliers=True)
    strict = {"components": {
        "supplier_discipline": {"weight": 100},
        "sales_volume": {"enabled": False}, "sales_floor": {"enabled": False},
        "consistency": {"enabled": False}, "tenure": {"enabled": False},
        "margin": {"enabled": False}, "repeat_customers": {"enabled": False},
        "collections": {"enabled": False},
    }}
    _partner(admin, "Strict Co", overrides=strict, eligibility={"min_score": 60})
    offer = _offers(cook)["Strict Co"]
    # Supplier payment is 40% → scores 0 on that band → fails their minimum.
    assert offer["score"] < 60 and offer["eligible"] is False
    failed = [c for c in offer["checks"] if not c["passed"]]
    assert failed and failed[0]["requirement"] == "scorecard score"


def test_the_application_snapshot_is_the_partners_view(admin):
    _phone, cook = _business(with_suppliers=True)
    partner = _partner(admin, "Snapshot Co", overrides={"components": {
        "supplier_discipline": {"weight": 100},
        "sales_volume": {"enabled": False}, "sales_floor": {"enabled": False},
        "consistency": {"enabled": False}, "tenure": {"enabled": False},
        "margin": {"enabled": False}, "repeat_customers": {"enabled": False},
        "collections": {"enabled": False},
    }})
    standard = client.get("/app/api/scorecard", cookies=cook).json()
    applied = client.post(f"/app/api/finance-offers/{partner['id']}/apply", cookies=cook,
                          json={"consent": True, "asset_requested": "motorcycle"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["score"] != int(standard["score"])

    detail = client.get(f"/app/api/admin/finance-applications/{applied.json()['id']}",
                        cookies=admin).json()
    assert detail["snapshot"]["partner_rules"] is True
    assert detail["snapshot"]["partner_name"] == "Snapshot Co"
    # Only the component this partner cares about was counted.
    assert [c["key"] for c in detail["snapshot"]["components"]] == ["supplier_discipline"]


def test_overrides_round_trip_and_can_be_cleared(admin):
    created = _partner(admin, "Editable", overrides={"components": {"margin": {"weight": 50}}})
    assert created["scorecard_overrides"]["components"]["margin"]["weight"] == 50

    cleared = client.put(f"/app/api/admin/finance-partners/{created['id']}", cookies=admin, json={
        "name": "Editable", "asset_types": ["motorcycle"], "eligibility": {},
        "scorecard_overrides": {}, "commission_type": "FLAT_PER_DEAL",
        "commission_value": 10_000, "commission_due_on": "ON_DELIVERY"})
    assert cleared.status_code == 200 and cleared.json()["scorecard_overrides"] == {}


def test_merge_keeps_unmentioned_settings():
    merged = bs.merge_config(bs.DEFAULT_CONFIG, {"components": {"sales_volume": {"weight": 99}}})
    assert merged["components"]["sales_volume"]["weight"] == 99
    # Band and label untouched…
    assert merged["components"]["sales_volume"]["full"] == 1_000_000
    # …and every other component still present, with the global tiers intact.
    assert len(merged["components"]) == len(bs.DEFAULT_CONFIG["components"])
    assert merged["tiers"] == bs.DEFAULT_CONFIG["tiers"]
    # The global config itself is not mutated.
    assert bs.DEFAULT_CONFIG["components"]["sales_volume"]["weight"] == 20
