"""
Regression: a debtor's payment sends them a receipt (issue #7).

Previously only BUY / COMBINED transactions notified the customer; a standalone
PAY sent nothing. Now, when the customer has a saved phone, a PAY sends a
"PAYMENT RECEIVED" receipt with the amount and remaining balance.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, Transaction, User, PendingAction
from parser import parse_message
from transaction_setup import handle_transaction_setup
from transaction_save import save_confirmed_pending_transaction

OWNER = "2348000000001"
OWNER_WA = "2348000000009"
CUST_PHONE = "2348111111111"
PRO = {"plan": "PRO", "status": "ACTIVE",
       "limits": {"customers": None, "transactions_per_month": None, "active_inventory_items": None}}


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(User(id="u-owner", phone=OWNER, name="Ada Store", role="user"))
    db.commit()
    return db


def _make_debtor(db, name, debt=5000, phone=None):
    c = Customer(name=name, owner_phone=OWNER, balance=0, customer_phone=phone)
    db.add(c); db.commit()
    db.add(Transaction(customer_id=c.id, type="BUY", amount=debt,
                       message_id=f"buy-{uuid.uuid4()}", recorded_by_id="u-owner"))
    db.commit()
    return c


def _pay(db, text):
    """Record a payment; return list of (phone, message) that were sent."""
    sent = []
    cb = lambda p, m: sent.append((p, m))
    parsed = parse_message(text)
    handle_transaction_setup(db, OWNER_WA, parsed, db.query(User).get("u-owner"),
                             OWNER, PRO, "u-owner", None, cb)
    pending = db.query(PendingAction).filter(PendingAction.phone == OWNER_WA).first()
    assert pending is not None, f"no pending for {text!r}: {sent}"
    sent.clear()
    save_confirmed_pending_transaction(db, OWNER_WA, pending,
                                       db.query(User).get("u-owner"), OWNER, "u-owner",
                                       f"msg-{uuid.uuid4()}", [], PRO, cb)
    db.expire_all()
    return sent


def test_payment_sends_receipt_to_customer_with_phone():
    db = _db()
    _make_debtor(db, "Bola", 5000, phone=CUST_PHONE)
    sent = _pay(db, "Bola paid 2000")

    to_customer = [m for (p, m) in sent if p == CUST_PHONE]
    assert to_customer, f"no message sent to customer phone; sent={sent}"
    receipt = to_customer[0]
    assert "PAYMENT RECEIVED" in receipt
    assert "2,000" in receipt          # amount paid, comma-formatted
    assert "3,000" in receipt          # remaining balance 5000-2000

    to_owner = [m for (p, m) in sent if p == OWNER_WA]
    assert any("Payment receipt sent to" in m for m in to_owner)


def test_full_payment_shows_settled():
    db = _db()
    _make_debtor(db, "Chika", 4000, phone=CUST_PHONE)
    sent = _pay(db, "Chika paid 4000")
    receipt = next(m for (p, m) in sent if p == CUST_PHONE)
    assert "PAYMENT RECEIVED" in receipt
    assert "Fully paid" in receipt


def test_payment_without_customer_phone_gives_owner_the_receipt():
    # No saved phone must not mean "no evidence": the receipt is still generated
    # and delivered to whoever recorded it (here, the owner) for their records.
    db = _db()
    _make_debtor(db, "Dele", 5000, phone=None)
    sent = _pay(db, "Dele paid 2000")

    # Nothing is sent to a customer phone (there is none)
    assert all(p == OWNER_WA for (p, m) in sent), f"unexpected recipient: {sent}"
    # The owner receives the payment receipt as evidence
    owner_msgs = [m for (p, m) in sent if p == OWNER_WA]
    assert any("PAYMENT RECEIVED" in m and "2,000" in m for m in owner_msgs), \
        f"owner did not get receipt evidence: {owner_msgs}"
    assert any("no phone on file" in m.lower() for m in owner_msgs)
