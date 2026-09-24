"""
The business scorecard: evidence CreditVoice gives a finance partner about a
business's trading record. Every threshold, weight and tier is admin-editable,
so the tests pin the behaviour of the engine, not one set of numbers.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-scorecard-000000000000000")

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
from database import SessionLocal
from models import (
    Customer, InventoryItem, InventoryMovement, ScorecardConfig, SupplierPurchase,
    Transaction, User, utcnow,
)

client = TestClient(app)
_seq = iter(range(1000, 2000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(months_ago=8):
    phone = f"234853{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=30 * months_ago)
        db.commit()
    finally:
        db.close()
    return phone


def _trade(phone, months=4, per_month=3, amount=100_000, credit=False, paid_each=0,
           with_customer=True, days_apart=7):
    """Seed `months` months of sales, `per_month` each, on separate days."""
    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.phone == phone).first().id
        cust = None
        if with_customer:
            cust = Customer(owner_phone=phone, name=f"cust{next(_seq)}", balance=0)
            db.add(cust); db.flush()
        for m in range(months):
            for i in range(per_month):
                when = utcnow() - timedelta(days=30 * m + i * days_apart + 1)
                db.add(Transaction(
                    customer_id=cust.id if cust else None,
                    type="BUY" if credit else "SALE", amount=amount,
                    recorded_by_id=uid, created_at=when,
                ))
                if credit and paid_each:
                    db.add(Transaction(
                        customer_id=cust.id, type="PAY", amount=paid_each,
                        recorded_by_id=uid, created_at=when + timedelta(days=1),
                    ))
        db.commit()
        return cust.id if cust else None
    finally:
        db.close()


def _metrics(phone, window=6):
    db = SessionLocal()
    try:
        return bs.compute_metrics(db, phone, window)
    finally:
        db.close()


def _score(phone):
    db = SessionLocal()
    try:
        return bs.score_business(db, phone)
    finally:
        db.close()


# ── Metrics ──────────────────────────────────────────────────────────────────

def test_sales_metrics_cover_cash_and_credit_sales():
    phone = _owner()
    _trade(phone, months=4, per_month=3, amount=100_000)
    m = _metrics(phone)
    assert m["total_sales"] == 1_200_000
    assert m["months_recorded"] == 4
    assert m["avg_monthly_sales"] == 300_000
    assert m["min_monthly_sales"] == 300_000        # excludes the part-month
    assert m["avg_active_days_per_month"] == 3.0
    assert m["corroborated_revenue_pct"] == 100.0   # every sale has a customer


def test_credit_sales_count_as_revenue_and_payments_as_collections():
    phone = _owner()
    _trade(phone, months=2, per_month=2, amount=50_000, credit=True, paid_each=20_000)
    m = _metrics(phone)
    assert m["total_sales"] == 200_000        # BUY rows are revenue
    assert m["credit_sales"] == 200_000
    assert m["collected"] == 80_000           # PAY rows are collections
    assert m["collection_rate_pct"] == 40.0
    assert m["receivables"] == 120_000        # still owed
    assert m["debtor_count"] == 1


def test_margin_reports_its_own_coverage():
    phone = _owner()
    _trade(phone, months=1, per_month=1, amount=10_000)
    db = SessionLocal()
    try:
        item = InventoryItem(owner_phone=phone, name="rice", quantity=5,
                             cost_price=700, selling_price=1000)
        db.add(item); db.flush()
        db.add(InventoryMovement(owner_phone=phone, item_id=item.id, movement_type="OUT",
                                 quantity=5, unit_price=1000, created_at=utcnow()))
        db.commit()
    finally:
        db.close()
    m = _metrics(phone)
    assert m["gross_margin_pct"] == 30.0        # (5000 - 3500) / 5000
    assert m["margin_coverage_pct"] == 50.0     # margin drawn from half of sales


def test_supplier_discipline_and_overdue_payables():
    phone = _owner()
    db = SessionLocal()
    try:
        db.add(SupplierPurchase(owner_phone=phone, product="bags", total=100_000,
                                paid_amount=80_000, created_at=utcnow() - timedelta(days=20)))
        db.add(SupplierPurchase(owner_phone=phone, product="salt", total=100_000,
                                paid_amount=0, due_date=utcnow() - timedelta(days=5),
                                created_at=utcnow() - timedelta(days=40)))
        db.commit()
    finally:
        db.close()
    m = _metrics(phone)
    assert m["supplier_paid_pct"] == 40.0       # 80k of 200k
    assert m["overdue_payables"] == 100_000


def test_repeat_customers_and_expected_inflow():
    phone = _owner()
    cid = _trade(phone, months=2, per_month=2, amount=40_000)   # same customer twice+
    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.phone == phone).first().id
        once = Customer(owner_phone=phone, name="one-off", balance=0)
        db.add(once); db.flush()
        db.add(Transaction(customer_id=once.id, type="SALE", amount=5_000,
                           recorded_by_id=uid, created_at=utcnow() - timedelta(days=3)))
        db.add(Transaction(customer_id=cid, type="BUY", amount=70_000, recorded_by_id=uid,
                           created_at=utcnow() - timedelta(days=2),
                           due_date=utcnow() + timedelta(days=10)))
        db.commit()
    finally:
        db.close()
    m = _metrics(phone)
    assert m["active_customers"] == 2
    assert m["repeat_customer_pct"] == 50.0     # 1 of 2 customers came back
    assert m["expected_next_30_days"] == 70_000


# ── Scoring, tiers, confidence ───────────────────────────────────────────────

def test_a_strong_business_scores_higher_than_a_weak_one():
    strong = _owner()
    _trade(strong, months=6, per_month=15, amount=80_000, days_apart=2)
    weak = _owner(months_ago=1)
    _trade(weak, months=1, per_month=1, amount=20_000)

    s, w = _score(strong), _score(weak)
    assert s["scored"] and w["scored"]
    assert s["score"] > w["score"]
    assert s["confidence"] > w["confidence"]
    assert {c["key"] for c in s["components"]} >= {"sales_volume", "consistency", "tenure"}
    assert sum(c["weight"] for c in s["components"]) == 100


def test_too_little_history_is_not_scored_rather_than_flattered():
    phone = _owner(months_ago=0)
    db = SessionLocal()
    try:
        cfg = dict(bs.DEFAULT_CONFIG)
        cfg["min_months_recorded"] = 3
        bs.save_config(db, cfg, updated_by="admin", note="raise minimum")
    finally:
        db.close()
    _trade(phone, months=1, per_month=2, amount=50_000)
    s = _score(phone)
    assert s["scored"] is False and s["score"] is None
    assert s["tier"] == "Unrated" and "month(s) of records" in s["not_scored_reason"]


def test_admin_config_changes_the_outcome_and_keeps_old_versions():
    phone = _owner()
    _trade(phone, months=3, per_month=4, amount=100_000)
    before = _score(phone)

    db = SessionLocal()
    try:
        cfg = json.loads(json.dumps(bs.DEFAULT_CONFIG))
        # Demand ten times the sales for full marks → same business scores lower.
        cfg["components"]["sales_volume"]["full"] = 10_000_000
        cfg["tiers"] = [{"name": "Basic", "min_score": 0}, {"name": "Prime", "min_score": 95}]
        row = bs.save_config(db, cfg, updated_by="admin", note="tighter")
        assert row.version == before["config_version"] + 1
        versions = db.query(ScorecardConfig).count()
        assert versions >= 2                    # old version kept for old reports
        active = db.query(ScorecardConfig).filter(ScorecardConfig.is_active == True).count()
        assert active == 1
    finally:
        db.close()

    after = _score(phone)
    assert after["score"] < before["score"]
    assert after["tier"] == "Basic"
    assert after["config_version"] == before["config_version"] + 1


def test_partial_config_falls_back_to_defaults():
    db = SessionLocal()
    try:
        bs.save_config(db, {"window_months": 3}, updated_by="admin")
        version, cfg = bs.active_config(db)
        assert cfg["window_months"] == 3
        assert cfg["components"]["sales_volume"]["weight"] == 20   # default kept
    finally:
        db.close()


# ── Partner eligibility ──────────────────────────────────────────────────────

def test_eligibility_reports_each_requirement_with_the_actual_value():
    phone = _owner()
    _trade(phone, months=3, per_month=4, amount=100_000)
    card = _score(phone)
    checks = bs.check_eligibility(card, {
        "min_months_recorded": 3,
        "min_avg_monthly_sales": 5_000_000,      # far above this business
        "min_score": 0,
    })
    by_req = {c["requirement"]: c for c in checks}
    assert by_req["months of records"]["passed"] is True
    assert by_req["average monthly sales"]["passed"] is False
    assert by_req["average monthly sales"]["actual"] == card["metrics"]["avg_monthly_sales"]
    assert bs.eligible(checks) is False

    assert bs.eligible(bs.check_eligibility(card, {"min_months_recorded": 1})) is True
    assert bs.eligible(bs.check_eligibility(card, {})) is True   # no minimums set
