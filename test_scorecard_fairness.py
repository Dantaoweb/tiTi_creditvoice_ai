"""
Businesses don't all trade the same way. A component with nothing to measure —
no suppliers recorded, nothing sold on credit, no cost prices — must drop out
and hand its weight to the rest, instead of scoring the business zero for
something it simply doesn't do.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-fairness-000000000000000")

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
from database import SessionLocal
from models import (
    Customer, InventoryItem, InventoryMovement, Supplier, SupplierPurchase,
    Transaction, User, utcnow,
)

client = TestClient(app)
_seq = iter(range(1000, 3000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    # Start every test from the built-in rules; other modules share this DB.
    db = SessionLocal()
    try:
        bs.save_config(db, bs.DEFAULT_CONFIG, updated_by="test", note="baseline")
    finally:
        db.close()
    yield
    # …and leave the defaults live: these tests save configs, and other test
    # modules share this in-memory database.
    db = SessionLocal()
    try:
        bs.save_config(db, bs.DEFAULT_CONFIG, updated_by="test", note="restore")
    finally:
        db.close()
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    phone = f"234858{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Trader", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        db.commit()
    finally:
        db.close()
    return phone, cookies


def _cash_only_trading(phone, months=4, per_month=4, amount=100_000):
    """Cash sales with no customer, no credit, no suppliers, no cost prices."""
    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.phone == phone).first().id
        for m in range(months):
            for i in range(per_month):
                db.add(Transaction(customer_id=None, type="SALE", amount=amount,
                                   recorded_by_id=uid,
                                   created_at=utcnow() - timedelta(days=30 * m + i * 5 + 1)))
        db.commit()
    finally:
        db.close()


def _card(cookies):
    r = client.get("/app/api/scorecard", cookies=cookies)
    assert r.status_code == 200, r.text
    return r.json()


def test_cash_only_trader_is_not_penalised_for_what_it_never_does():
    phone, cook = _owner()
    _cash_only_trading(phone)
    card = _card(cook)

    skipped = {s["key"] for s in card["not_applicable"]}
    assert {"margin", "collections", "supplier_discipline", "repeat_customers"} <= skipped
    assert "repayment_record" in skipped          # never financed
    scored = {c["key"] for c in card["components"]}
    assert scored == {"sales_volume", "sales_floor", "consistency", "tenure"}

    # The remaining weights carry the whole score…
    assert sum(c["weight"] for c in card["components"]) == 60
    # …and every scored component still reports its own value.
    assert card["scored"] is True and card["score"] > 0
    for c in card["components"]:
        assert c["score"] >= 0


def test_the_same_trading_scores_higher_than_under_the_old_zero_rule():
    """Skipping beats scoring zero: the score must exceed what it would be if the
    four absent components were counted as 0."""
    phone, cook = _owner()
    _cash_only_trading(phone)
    card = _card(cook)

    counted = sum(c["score"] * c["weight"] for c in card["components"])
    all_weights = sum(
        float(spec.get("weight", 0))
        for spec in bs.DEFAULT_CONFIG["components"].values()
    )
    if_zeroed = round(counted / all_weights, 1)
    assert card["score"] > if_zeroed


def test_a_component_starts_counting_as_soon_as_there_is_data():
    phone, cook = _owner()
    _cash_only_trading(phone)
    assert "supplier_discipline" in {s["key"] for s in _card(cook)["not_applicable"]}

    db = SessionLocal()
    try:
        sup = Supplier(name="Rice Depot", owner_phone=phone)
        db.add(sup); db.flush()
        db.add(SupplierPurchase(supplier_id=sup.id, owner_phone=phone, product="rice",
                                total=80_000, paid_amount=80_000))
        db.commit()
    finally:
        db.close()

    card = _card(cook)
    assert "supplier_discipline" not in {s["key"] for s in card["not_applicable"]}
    comp = next(c for c in card["components"] if c["key"] == "supplier_discipline")
    assert comp["value"] == 100.0 and comp["score"] == 100.0


def test_margin_counts_only_once_a_cost_price_exists():
    phone, cook = _owner()
    _cash_only_trading(phone, months=1, per_month=1, amount=10_000)
    assert "margin" in {s["key"] for s in _card(cook)["not_applicable"]}

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
    card = _card(cook)
    assert "margin" not in {s["key"] for s in card["not_applicable"]}
    assert next(c for c in card["components"] if c["key"] == "margin")["value"] == 30.0


def test_credit_trader_keeps_the_collections_component():
    phone, cook = _owner()
    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.phone == phone).first().id
        cust = Customer(owner_phone=phone, name="Ade", balance=0)
        db.add(cust); db.flush()
        for m in range(3):
            db.add(Transaction(customer_id=cust.id, type="BUY", amount=100_000,
                               recorded_by_id=uid, created_at=utcnow() - timedelta(days=30 * m + 1)))
            db.add(Transaction(customer_id=cust.id, type="PAY", amount=90_000,
                               recorded_by_id=uid, created_at=utcnow() - timedelta(days=30 * m)))
        db.commit()
    finally:
        db.close()
    card = _card(cook)
    keys = {c["key"] for c in card["components"]}
    assert "collections" in keys and "repeat_customers" in keys
    assert next(c for c in card["components"] if c["key"] == "collections")["value"] == 90.0


def test_a_business_with_nothing_measurable_is_unrated_not_zero():
    """All components gated out → say so, rather than publishing a 0 score."""
    phone, cook = _owner()
    _cash_only_trading(phone, months=2, per_month=2)
    db = SessionLocal()
    try:
        cfg = {"components": {
            "supplier_discipline": {
                "label": "Pays suppliers", "metric": "supplier_paid_pct", "weight": 100,
                "zero": 0, "full": 100, "requires": "supplier_purchases_total",
            }}}
        bs.save_config(db, cfg, updated_by="test", note="suppliers only")
    finally:
        db.close()
    card = _card(cook)
    assert card["scored"] is False and card["score"] is None
    assert "Nothing measurable" in card["not_scored_reason"]
    assert card["tier"] == "Unrated"
