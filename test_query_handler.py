"""
tiTi query-engine regression tests
==================================
Locks in the natural-language questions traders actually asked (taken from
real screenshots of tiTi failing to answer them) so the deterministic query
engine never regresses. No external LLM — every answer comes from the user's
own records.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, InventoryItem, Transaction
from query_handler import handle_natural_language_query

OWNER = "2348001111111"


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    olu = Customer(name="olu", owner_phone=OWNER, balance=0)
    baloo = Customer(name="baloo", owner_phone=OWNER, balance=0)
    db.add_all([olu, baloo])
    db.commit()

    def tx(cid, t, amt, **kw):
        row = Transaction(customer_id=cid, type=t, amount=amt,
                          message_id=str(uuid.uuid4()), **kw)
        db.add(row)
        db.commit()
        return row

    tx(olu.id, "BUY", 5000, product="mango")
    tx(olu.id, "PAY", 2000)                      # olu part-paid
    tx(baloo.id, "BUY", 3000, product="rice")    # baloo paid nothing
    voided = tx(baloo.id, "SALE", 99)
    voided.is_voided = True
    db.commit()

    db.add_all([
        InventoryItem(owner_phone=OWNER, name="mango", selling_price=500,
                      quantity=20, is_available=True),
        InventoryItem(owner_phone=OWNER, name="mango juice", selling_price=800,
                      quantity=5, is_available=True),
        InventoryItem(owner_phone=OWNER, name="rice", selling_price=4000,
                      quantity=10, is_available=True),
    ])
    db.commit()
    return olu, baloo


def ask(db, q):
    return handle_natural_language_query(db, OWNER, q, None)


# ── The screenshot phrasings that used to fail ────────────────────────────────

SCREENSHOT_QUESTIONS = [
    "How many business categories do you have",
    "How many business types are on creditvoice",
    "Which customer is owning me?",
    "How many customers are owning me?",
    "When did I make sales last?",
    "Look up for my basket of mango price list",
    "which customer has not pay anything?",
    "How many stocks do I have",
    "How many products have I added",
    "How many voided products do I have",
    "How many mango product types do I have",
]


def test_all_screenshot_questions_get_answers():
    db = make_db()
    seed(db)
    misses = [q for q in SCREENSHOT_QUESTIONS if not ask(db, q)]
    assert not misses, f"query engine missed: {misses}"


# ── Listing business types (not just counting them) ───────────────────────────

def test_list_business_types_enumerates_them_grouped():
    db = make_db(); seed(db)
    for q in ("list the business types you support",
              "what business types do you support",
              "show me the business types"):
        a = ask(db, q)
        assert a, q
        assert "Car Dealer" in a and "Pharmacy" in a, q      # specific types listed
        assert "Retail / Trading" in a                        # grouped under categories
        assert a.count("\n") > 5, q                           # multi-line, not the count reply


def test_how_many_business_types_stays_count_only():
    db = make_db(); seed(db)
    a = ask(db, "How many business types are on creditvoice")
    assert a and "business types" in a and a.rstrip().endswith("categories.")
    assert "Car Dealer" not in a


# ── Precision: "not paid anything" ≠ "owes me" ────────────────────────────────

def test_not_paid_anything_excludes_part_payers():
    db = make_db()
    seed(db)
    reply = ask(db, "which customer has not pay anything?")
    assert "Baloo" in reply
    assert "Olu" not in reply          # olu part-paid ₦2,000 — must not appear


def test_who_owes_me_includes_part_payers():
    db = make_db()
    seed(db)
    reply = ask(db, "who owes me")
    assert "Olu" in reply and "Baloo" in reply


# ── New intents ───────────────────────────────────────────────────────────────

def test_total_outstanding():
    db = make_db()
    seed(db)
    reply = ask(db, "how much am I owed")
    assert "6,000" in reply            # 3000 (olu) + 3000 (baloo)


def test_total_outstanding_does_not_hijack_single_customer():
    db = make_db()
    seed(db)
    reply = ask(db, "how much is olu owing me")
    assert reply and "3,000" in reply
    assert "Baloo" not in reply        # single-customer answer, not the aggregate


def test_sales_today():
    db = make_db()
    seed(db)
    reply = ask(db, "how much did I sell today")
    assert reply and "8,000" in reply  # 5000 + 3000 credit sales today
    reply2 = ask(db, "today's sales")
    assert reply2 and "8,000" in reply2


def test_counts():
    db = make_db()
    seed(db)
    assert "3 product(s)" in ask(db, "How many stocks do I have")
    assert "2" in ask(db, "How many mango product types do I have")
    assert "1 voided" in ask(db, "How many voided products do I have")


def test_non_questions_pass_through():
    db = make_db()
    seed(db)
    # Transactions and commands must NOT be hijacked by the query engine
    assert ask(db, "olu bought rice 5000") is None
    assert ask(db, "add stock rice 10 bags cost 3000 sell 4000") is None
    assert ask(db, "menu") is None
