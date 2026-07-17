"""
Regression: a debtor's payment must deduct, not create a duplicate customer.

The parser lowercases the typed name ("Ade" -> "ade"), while web-added
customers are stored mixed-case ("Ade"). A case-sensitive lookup never matched,
so every WhatsApp payment spawned a duplicate customer and left the real debt
untouched. Customer lookups on the transaction path are now case-insensitive.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, Transaction, User
from parser import parse_message
from transaction_setup import handle_transaction_setup
from transaction_save import save_confirmed_pending_transaction
from models import PendingAction

OWNER = "2348000000001"
PRO = {"plan": "PRO", "status": "ACTIVE",
       "limits": {"customers": None, "transactions_per_month": None, "active_inventory_items": None}}


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(User(id="u-owner", phone=OWNER, name="Shop", role="user"))
    db.commit()
    return db


def _named(db, name):
    return db.query(Customer).filter(
        func.lower(Customer.name) == name.lower(), Customer.owner_phone == OWNER
    ).all()


def _pay(db, text):
    parsed = parse_message(text)
    sent = []
    handle_transaction_setup(db, "2348000000009", parsed, db.query(User).get("u-owner"),
                             OWNER, PRO, "u-owner", None, lambda p, m: sent.append(m))
    pending = db.query(PendingAction).filter(PendingAction.phone == "2348000000009").first()
    assert pending is not None, f"no pending for {text!r}: {sent}"
    save_confirmed_pending_transaction(db, "2348000000009", pending,
                                       db.query(User).get("u-owner"), OWNER, "u-owner",
                                       f"msg-{uuid.uuid4()}", [], PRO, lambda p, m: None)
    db.expire_all()


def _make_debtor(db, name, debt=5000):
    c = Customer(name=name, owner_phone=OWNER, balance=0)
    db.add(c); db.commit()
    db.add(Transaction(customer_id=c.id, type="BUY", amount=debt,
                       message_id=f"buy-{uuid.uuid4()}", recorded_by_id="u-owner"))
    db.commit()
    return c


def test_payment_deducts_mixed_case_customer_no_duplicate():
    db = _db()
    _make_debtor(db, "Ade", 5000)          # stored capitalised (as web creates it)
    _pay(db, "Ade paid 2000")              # parser lowercases to "ade"
    rows = _named(db, "ade")
    assert len(rows) == 1, f"duplicate created: {[(c.id, c.name) for c in rows]}"
    assert rows[0].balance == 3000         # 5000 - 2000, deducted


def test_second_payment_still_deducts():
    db = _db()
    _make_debtor(db, "Ngozi", 5000)
    _pay(db, "Ngozi paid 2000")
    _pay(db, "NGOZI PAID 1000")            # shouting also matches
    rows = _named(db, "ngozi")
    assert len(rows) == 1
    assert rows[0].balance == 2000         # 5000 - 2000 - 1000


def test_new_payer_lowercase_created_once():
    # A genuinely new payer is still created (once), lowercased — unchanged behaviour
    db = _db()
    _pay(db, "Bola paid 1000")
    rows = _named(db, "bola")
    assert len(rows) == 1
    assert rows[0].balance == -1000        # credit balance for a pure payment
