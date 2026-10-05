"""
What tiTi notices without being asked.

Two things decide whether this feature is worth having. It has to spot the slow
problems a trader cannot see from inside the day — a cost that crept up, a
shelf about to empty, a regular who stopped coming. And it has to stay quiet
otherwise, because a warning that fires for everyone teaches people to ignore
warnings.
"""
import os
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-insights-00000000000000")

import pytest

import business_insights as insights
import proactive_scheduler as scheduler
from database import Base, SessionLocal, engine
from models import (
    AppNotification, Customer, InventoryItem, InventoryMovement, ProactiveLog,
    Transaction, User, utcnow,
)

Base.metadata.create_all(engine)
_seq = iter(range(100, 900))


@pytest.fixture
def shop():
    phone = f"23480900771{next(_seq)}"
    db = SessionLocal()
    try:
        db.add(User(phone=phone, name="Ade Stores"))
        db.commit()
        return phone
    finally:
        db.close()


def _item(phone, name="Rice", unit="bag", sell=80_000, qty=10, low_alert=None):
    db = SessionLocal()
    try:
        item = InventoryItem(owner_phone=phone, name=name, unit=unit, selling_price=sell,
                             quantity=qty, is_available=True, low_stock_alert=low_alert)
        db.add(item)
        db.commit()
        return item.id
    finally:
        db.close()


def _stock_in(phone, item_id, quantity, unit_price, days_ago=0):
    db = SessionLocal()
    try:
        db.add(InventoryMovement(owner_phone=phone, item_id=item_id, movement_type="IN",
                                 quantity=quantity, unit_price=unit_price,
                                 created_at=utcnow() - timedelta(days=days_ago)))
        db.commit()
    finally:
        db.close()


def _sale(phone, product, amount, quantity=1, days_ago=1, customer=None):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        cust = db.query(Customer).filter(Customer.owner_phone == phone,
                                         Customer.name == (customer or "Regular")).first()
        if not cust:
            cust = Customer(owner_phone=phone, name=customer or "Regular", balance=0)
            db.add(cust)
            db.flush()
        db.add(Transaction(customer_id=cust.id, type="SALE", amount=amount, product=product,
                           quantity=quantity, recorded_by_id=user.id,
                           created_at=utcnow() - timedelta(days=days_ago)))
        db.commit()
    finally:
        db.close()


def _found(phone):
    db = SessionLocal()
    try:
        return {i["key"]: i for i in insights.find_insights(db, phone)}
    finally:
        db.close()


# ── A quiet business hears nothing ───────────────────────────────────────────

def test_a_healthy_business_is_left_alone(shop):
    item_id = _item(shop, qty=100)
    _stock_in(shop, item_id, 100, 68_000, days_ago=10)
    _sale(shop, "Rice", 80_000, days_ago=1)
    assert _found(shop) == {}


def test_a_business_with_no_records_is_left_alone(shop):
    assert _found(shop) == {}


# ── The slow problems ────────────────────────────────────────────────────────

def test_a_cost_that_crept_up_is_noticed_with_what_it_costs_them(shop):
    item_id = _item(shop, sell=80_000, qty=100)
    _stock_in(shop, item_id, 10, 68_000, days_ago=90)
    _stock_in(shop, item_id, 10, 68_000, days_ago=60)
    _stock_in(shop, item_id, 10, 78_000, days_ago=2)

    found = _found(shop)
    assert "cost_up" in found
    body = found["cost_up"]["body"]
    assert "₦68,000" in body and "₦78,000" in body
    assert "₦10,000" in body
    # The part they feel but rarely work out: what the margin was, and is now.
    assert "₦2,000" in body and "₦12,000" in body


def test_a_small_cost_wobble_is_not_worth_interrupting_anyone(shop):
    item_id = _item(shop, sell=80_000)
    _stock_in(shop, item_id, 10, 68_000, days_ago=60)
    _stock_in(shop, item_id, 10, 69_000, days_ago=2)      # +1.5%
    assert "cost_up" not in _found(shop)


def test_one_purchase_is_not_a_trend(shop):
    item_id = _item(shop, sell=80_000)
    _stock_in(shop, item_id, 10, 90_000, days_ago=2)
    assert "cost_up" not in _found(shop)


def test_selling_below_cost_outranks_everything(shop):
    item_id = _item(shop, sell=60_000, qty=100)
    _stock_in(shop, item_id, 10, 68_000, days_ago=30)
    _stock_in(shop, item_id, 10, 80_000, days_ago=2)      # also a cost rise

    db = SessionLocal()
    try:
        found = insights.find_insights(db, shop)
    finally:
        db.close()
    assert found[0]["key"] == "below_cost"
    assert "lose" in found[0]["body"].lower()


def test_the_shelf_emptying_this_week_is_flagged(shop):
    _item(shop, name="Rice", qty=6)
    for day in range(0, 30):
        _sale(shop, "Rice", 80_000, quantity=2, days_ago=day)   # 2 a day
    found = _found(shop)
    assert "runs_out" in found
    assert "3 days" in found["runs_out"]["title"] or "3 days" in found["runs_out"]["body"]


def test_a_product_with_its_own_low_stock_alert_is_left_to_that_alert(shop):
    _item(shop, name="Rice", qty=6, low_alert=10)
    for day in range(0, 30):
        _sale(shop, "Rice", 80_000, quantity=2, days_ago=day)
    assert "runs_out" not in _found(shop)


def test_plenty_of_stock_is_not_a_warning(shop):
    _item(shop, name="Rice", qty=300)
    for day in range(0, 30):
        _sale(shop, "Rice", 80_000, quantity=2, days_ago=day)
    assert "runs_out" not in _found(shop)


def test_a_regular_who_stopped_coming_is_noticed(shop):
    for day in (120, 110, 100):
        _sale(shop, "Rice", 80_000, days_ago=day, customer="Mama Bola")
    found = _found(shop)
    assert "quiet_regular" in found
    assert "Mama Bola" in found["quiet_regular"]["title"]
    assert "3 times" in found["quiet_regular"]["body"]


def test_someone_who_bought_once_is_not_a_regular(shop):
    _sale(shop, "Rice", 80_000, days_ago=120, customer="Passer By")
    assert "quiet_regular" not in _found(shop)


def test_a_regular_still_coming_is_not_chased(shop):
    for day in (60, 30, 2):
        _sale(shop, "Rice", 80_000, days_ago=day, customer="Mama Bola")
    assert "quiet_regular" not in _found(shop)


# ── Delivery: one a day, through the bell ────────────────────────────────────

def test_the_most_valuable_one_is_sent_and_only_one(shop):
    item_id = _item(shop, sell=60_000, qty=6)
    _stock_in(shop, item_id, 10, 68_000, days_ago=30)
    _stock_in(shop, item_id, 10, 80_000, days_ago=2)
    for day in range(0, 30):
        _sale(shop, "Rice", 60_000, quantity=2, days_ago=day)

    db = SessionLocal()
    try:
        scheduler._check_business_insights(db)
        notes = db.query(AppNotification).filter(
            AppNotification.owner_phone == shop,
            AppNotification.event_type == "insight").all()
        assert len(notes) == 1
        assert "below cost" in notes[0].title.lower()
        assert notes[0].link == "/inventory"      # it can be acted on
    finally:
        db.close()


def test_the_same_insight_does_not_arrive_every_morning(shop):
    item_id = _item(shop, sell=80_000, qty=100)
    _stock_in(shop, item_id, 10, 68_000, days_ago=60)
    _stock_in(shop, item_id, 10, 80_000, days_ago=2)

    db = SessionLocal()
    try:
        scheduler._check_business_insights(db)
        scheduler._check_business_insights(db)
        assert db.query(AppNotification).filter(
            AppNotification.owner_phone == shop,
            AppNotification.event_type == "insight").count() == 1
    finally:
        db.close()


def test_it_comes_back_after_the_cooldown(shop):
    item_id = _item(shop, sell=80_000, qty=100)
    _stock_in(shop, item_id, 10, 68_000, days_ago=60)
    _stock_in(shop, item_id, 10, 80_000, days_ago=2)

    db = SessionLocal()
    try:
        scheduler._check_business_insights(db)
        log = db.query(ProactiveLog).filter(
            ProactiveLog.owner_phone == shop,
            ProactiveLog.event_type == "insight:cost_up").first()
        log.sent_at = utcnow() - timedelta(days=8)
        db.commit()
        scheduler._check_business_insights(db)
        assert db.query(AppNotification).filter(
            AppNotification.owner_phone == shop,
            AppNotification.event_type == "insight").count() == 2
    finally:
        db.close()


def test_a_broken_insight_does_not_cost_the_business_the_others(shop, monkeypatch):
    item_id = _item(shop, sell=60_000, qty=100)
    _stock_in(shop, item_id, 10, 68_000, days_ago=30)

    def boom(db, owner_phone):
        raise RuntimeError("generator exploded")

    monkeypatch.setattr(insights, "_cost_crept_up", boom)
    monkeypatch.setattr(insights, "_GENERATORS", (
        ("below_cost", insights._selling_below_cost),
        ("cost_up", boom),
    ))
    found = _found(shop)
    assert "below_cost" in found          # the healthy one still ran
