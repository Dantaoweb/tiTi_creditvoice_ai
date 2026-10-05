"""
What tiTi knows about a business, and how it says it.

The point of the registry is that a question is answered from what the business
recorded — so these tests seed real stock entries and sales and check the
figures, not the wording. Two rules it must never break: a cost nobody recorded
is "I don't know", never zero; and a question it did not understand falls
through to the older handlers instead of guessing.
"""
import os
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-business-facts-0000000")

import pytest

import business_facts as facts
from database import Base, SessionLocal, engine

# This module tests the facts directly rather than over HTTP, so it never
# imports the app — and the app is what normally creates the schema.
Base.metadata.create_all(engine)
from models import Customer, InventoryItem, InventoryMovement, Transaction, User, utcnow
from query_handler import handle_natural_language_query

_seq = iter(range(100, 900))


@pytest.fixture
def shop():
    """A business with one product and a history of buying it."""
    phone = f"23480900661{next(_seq)}"
    db = SessionLocal()
    try:
        user = User(phone=phone, name="Ade Stores")
        db.add(user)
        db.commit()
        return phone
    finally:
        db.close()


def _item(phone, name="Rice", unit="bag", sell=80_000, cost=None, qty=10):
    db = SessionLocal()
    try:
        item = InventoryItem(owner_phone=phone, name=name, unit=unit,
                             selling_price=sell, cost_price=cost, quantity=qty,
                             is_available=True)
        db.add(item)
        db.commit()
        return item.id
    finally:
        db.close()


def _stock_in(phone, item_id, quantity, unit_price, days_ago=0):
    db = SessionLocal()
    try:
        db.add(InventoryMovement(
            owner_phone=phone, item_id=item_id, movement_type="IN",
            quantity=quantity, unit_price=unit_price,
            created_at=utcnow() - timedelta(days=days_ago),
        ))
        db.commit()
    finally:
        db.close()


def _ask(phone, text):
    db = SessionLocal()
    try:
        return handle_natural_language_query(db, phone, text)
    finally:
        db.close()


# ── Average cost: the figure, and how it is weighted ─────────────────────────

def test_average_cost_is_weighted_by_quantity(shop):
    """50 bags at ₦68k and 1 at ₦90k is not an average of ₦79k — the business
    paid near ₦68k, and that is the number it has to be told."""
    item_id = _item(shop)
    _stock_in(shop, item_id, 50, 68_000, days_ago=30)
    _stock_in(shop, item_id, 1, 90_000, days_ago=1)

    reply = _ask(shop, "what is the average cost of rice")
    assert reply
    expected = round((50 * 68_000 + 1 * 90_000) / 51)
    assert f"₦{expected:,}" in reply
    assert "₦79,000" not in reply          # the unweighted answer


def test_the_average_counts_every_entry(shop):
    item_id = _item(shop)
    for price in (60_000, 70_000, 80_000):
        _stock_in(shop, item_id, 10, price)
    reply = _ask(shop, "average cost of rice")
    assert "₦70,000" in reply
    assert "3 stock entries" in reply


def test_a_purchase_nobody_priced_is_not_a_free_purchase(shop):
    item_id = _item(shop)
    _stock_in(shop, item_id, 10, 70_000)
    db = SessionLocal()
    try:                                   # a stock-in with no cost recorded
        db.add(InventoryMovement(owner_phone=shop, item_id=item_id,
                                 movement_type="IN", quantity=10, unit_price=None))
        db.commit()
    finally:
        db.close()
    reply = _ask(shop, "average cost of rice")
    assert "₦70,000" in reply              # not ₦35,000
    assert "1 stock entry" in reply


def test_no_cost_recorded_says_so_instead_of_zero(shop):
    _item(shop)
    reply = _ask(shop, "average cost of rice")
    assert reply
    assert "₦0" not in reply
    assert "don't know" in reply.lower()
    assert "add stock rice" in reply.lower()    # and how to fix it


def test_the_margin_is_worked_out_against_what_they_pay(shop):
    item_id = _item(shop, sell=80_000)
    _stock_in(shop, item_id, 10, 68_000)
    reply = _ask(shop, "average cost of rice")
    assert "₦12,000" in reply              # 80,000 − 68,000
    assert "15%" in reply


def test_selling_below_cost_is_called_out(shop):
    item_id = _item(shop, sell=60_000)
    _stock_in(shop, item_id, 10, 68_000)
    reply = _ask(shop, "average cost of rice")
    assert "below" in reply.lower()
    assert "₦8,000" in reply


# ── Cost over time ───────────────────────────────────────────────────────────

def test_the_rise_in_cost_is_reported_with_what_it_costs_them(shop):
    item_id = _item(shop, sell=80_000)
    _stock_in(shop, item_id, 10, 68_000, days_ago=60)
    _stock_in(shop, item_id, 10, 74_000, days_ago=2)

    reply = _ask(shop, "has the cost of rice gone up")
    assert "₦68,000" in reply and "₦74,000" in reply
    assert "₦6,000" in reply
    # The part they feel but may not have worked out.
    assert "less" in reply.lower()


def test_the_last_price_paid(shop):
    item_id = _item(shop)
    _stock_in(shop, item_id, 10, 68_000, days_ago=30)
    _stock_in(shop, item_id, 10, 71_500, days_ago=1)
    reply = _ask(shop, "what was the last price i bought rice")
    assert "₦71,500" in reply


def test_total_spent_on_a_product(shop):
    item_id = _item(shop)
    _stock_in(shop, item_id, 10, 68_000)
    _stock_in(shop, item_id, 5, 70_000)
    reply = _ask(shop, "how much have i spent on rice")
    assert f"₦{10 * 68_000 + 5 * 70_000:,}" in reply


# ── Periods ──────────────────────────────────────────────────────────────────

def test_a_period_narrows_the_answer(shop):
    item_id = _item(shop)
    _stock_in(shop, item_id, 10, 50_000, days_ago=200)     # long ago
    _stock_in(shop, item_id, 10, 90_000, days_ago=1)       # recent

    lifetime = _ask(shop, "average cost of rice")
    recent = _ask(shop, "average cost of rice in the last 7 days")
    assert "₦70,000" in lifetime
    assert "₦90,000" in recent


# ── Questions about the whole shop ───────────────────────────────────────────

def test_best_seller_comes_from_the_sales(shop):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == shop).first()
        cust = Customer(owner_phone=shop, name="Regular", balance=0)
        db.add(cust)
        db.flush()
        for product, amount, times in (("rice", 80_000, 3), ("sugar", 5_000, 2)):
            for _ in range(times):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=amount,
                                   product=product, recorded_by_id=user.id,
                                   created_at=utcnow() - timedelta(days=2)))
        db.commit()
    finally:
        db.close()
    reply = _ask(shop, "what is my best selling product")
    assert "Rice" in reply
    assert reply.index("Rice") < reply.index("Sugar")


def test_dead_stock_names_what_is_tying_up_money(shop):
    _item(shop, name="Candles", sell=500, cost=300, qty=100)
    reply = _ask(shop, "which products are not selling")
    assert "Candles" in reply
    assert f"₦{100 * 300:,}" in reply


def test_nothing_idle_is_said_plainly(shop):
    item_id = _item(shop, name="Rice", qty=5)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == shop).first()
        db.add(Transaction(type="SALE", amount=80_000, product="Rice",
                           recorded_by_id=user.id, created_at=utcnow() - timedelta(days=1)))
        db.commit()
    finally:
        db.close()
    assert "✓" in _ask(shop, "any dead stock")


# ── Routing: what it must not do ─────────────────────────────────────────────

def test_a_selling_price_question_is_still_a_selling_price_question(shop):
    """The older handler owns this one — "price of rice" is what they sell at."""
    item_id = _item(shop, sell=80_000)
    _stock_in(shop, item_id, 10, 68_000)
    reply = _ask(shop, "how much is rice")
    assert "₦80,000" in reply
    assert "average" not in reply.lower()


def test_an_unknown_product_is_asked_about_not_guessed(shop):
    _item(shop, name="Rice")
    reply = _ask(shop, "average cost of helicopter")
    assert reply
    assert "which product" in reply.lower()
    assert "Rice" in reply


def test_an_unrelated_question_falls_through(shop):
    _item(shop)
    db = SessionLocal()
    try:
        assert facts.answer(db, shop, "good morning titi") is None
        assert facts.answer(db, shop, "sold 2 bags rice 160000") is None
    finally:
        db.close()


def test_a_broken_fact_never_breaks_the_reply(shop, monkeypatch):
    item_id = _item(shop)
    _stock_in(shop, item_id, 10, 68_000)

    def boom(db, owner_phone, ask):
        raise RuntimeError("metric exploded")

    monkeypatch.setitem(
        next(m for m in facts.METRICS if m["key"] == "avg_cost"), "compute", boom
    )
    db = SessionLocal()
    try:
        assert facts.answer(db, shop, "average cost of rice") is None
    finally:
        db.close()


# ── Profit: only what can honestly be counted ────────────────────────────────

def _sale(phone, product, amount, quantity=1, days_ago=1):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        cust = db.query(Customer).filter(Customer.owner_phone == phone).first()
        if not cust:
            cust = Customer(owner_phone=phone, name="Regular", balance=0)
            db.add(cust)
            db.flush()
        db.add(Transaction(customer_id=cust.id, type="SALE", amount=amount,
                           product=product, quantity=quantity,
                           recorded_by_id=user.id,
                           created_at=utcnow() - timedelta(days=days_ago)))
        db.commit()
    finally:
        db.close()


def test_profit_is_revenue_minus_what_it_cost(shop):
    item_id = _item(shop, name="Rice", sell=80_000)
    _stock_in(shop, item_id, 10, 68_000)
    _sale(shop, "Rice", 80_000, quantity=1)
    _sale(shop, "Rice", 80_000, quantity=1)

    reply = _ask(shop, "how much profit did i make this month")
    assert "₦160,000" in reply           # revenue
    assert "₦24,000" in reply            # 2 × (80,000 − 68,000)


def test_sales_without_a_known_cost_are_excluded_not_counted_as_pure_profit(shop):
    item_id = _item(shop, name="Rice", sell=80_000)
    _stock_in(shop, item_id, 10, 68_000)
    _sale(shop, "Rice", 80_000, quantity=1)
    _sale(shop, "Firewood", 20_000, quantity=1)      # never stocked, no cost

    reply = _ask(shop, "how much profit did i make this month")
    assert "₦12,000" in reply            # only the rice is counted
    assert "₦20,000" in reply            # and the uncounted part is named
    assert "no cost recorded" in reply.lower()


def test_profit_without_any_costs_says_so(shop):
    _item(shop, name="Rice", sell=80_000)
    _sale(shop, "Rice", 80_000)
    reply = _ask(shop, "am i making profit this month")
    assert "cannot work out your profit" in reply.lower()
    assert "₦80,000" in reply            # but the sales figure is still given


# ── Running out: from this shop's own pace ───────────────────────────────────

def test_when_a_product_runs_out_is_predicted_from_its_own_sales(shop):
    item_id = _item(shop, name="Rice", qty=30)
    for day in range(0, 30):                       # exactly 2 bags a day
        _sale(shop, "Rice", 80_000, quantity=2, days_ago=day)
    reply = _ask(shop, "when will rice run out")
    assert "2.0 a day" in reply
    assert "15 days" in reply
    assert "restock" not in reply.lower()          # 15 days is not urgent


def test_running_out_soon_says_to_restock(shop):
    item_id = _item(shop, name="Rice", qty=4)
    for day in range(1, 31):
        _sale(shop, "Rice", 80_000, quantity=2, days_ago=day)
    reply = _ask(shop, "do i need to restock rice")
    assert "restock" in reply.lower()


def test_no_recent_sales_means_no_prediction_rather_than_a_guess(shop):
    _item(shop, name="Rice", qty=30)
    reply = _ask(shop, "when will rice run out")
    assert "cannot say" in reply.lower()


# ── Stock value and quiet customers ──────────────────────────────────────────

def test_stock_value_uses_what_was_paid(shop):
    item_id = _item(shop, name="Rice", sell=80_000, qty=10)
    _stock_in(shop, item_id, 10, 68_000)
    reply = _ask(shop, "what is the value of my stock")
    assert f"₦{10 * 68_000:,}" in reply
    assert f"₦{10 * 80_000:,}" in reply


def test_quiet_customers_are_listed_with_when_they_were_last_seen(shop):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == shop).first()
        old = Customer(owner_phone=shop, name="Gone Quiet", balance=5_000,
                       last_transaction_at=utcnow() - timedelta(days=120))
        recent = Customer(owner_phone=shop, name="Still Here", balance=0)
        db.add_all([old, recent])
        db.flush()
        db.add(Transaction(customer_id=recent.id, type="SALE", amount=1_000,
                           recorded_by_id=user.id,
                           created_at=utcnow() - timedelta(days=2)))
        db.commit()
    finally:
        db.close()
    reply = _ask(shop, "which customers have stopped buying")
    assert "Gone Quiet" in reply
    assert "Still Here" not in reply
    assert "owes ₦5,000" in reply


# ── Sales totals: filling the gap without shadowing what works ───────────────

def test_sales_for_a_period_the_old_handler_cannot_do(shop):
    _sale(shop, "Rice", 50_000, days_ago=1)
    reply = _ask(shop, "how much did i sell yesterday")
    assert reply and "₦50,000" in reply


def test_today_is_left_to_the_handler_that_already_answers_it(shop):
    _sale(shop, "Rice", 8_000, days_ago=0)
    db = SessionLocal()
    try:
        # The registry declines, so the established answer is what comes back.
        assert facts.answer(db, shop, "how much did i sell today") is None
    finally:
        db.close()
    assert "8,000" in _ask(shop, "how much did i sell today")


# ── The phrasings people actually use ────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "average cost of rice",
    "what is the average cost of rice",
    "avg cost rice",
    "how much do i buy rice",
    "what do i pay for rice",
    "cost price of rice",
    "wetin i dey buy rice",
])
def test_the_same_question_asked_different_ways(shop, question):
    item_id = _item(shop)
    _stock_in(shop, item_id, 10, 68_000)
    reply = _ask(shop, question)
    assert reply and "₦68,000" in reply, question
