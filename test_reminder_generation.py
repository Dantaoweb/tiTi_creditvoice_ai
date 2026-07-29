"""
Reminders are generated from the owner's LIVE unpaid debtors (not only the
ReminderMemory table) — so every debtor with a phone gets a draft message.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import User, Customer, Transaction, ReminderQueue
from reminder_automation import queue_debtor_reminders

OWNER = "2348000000066"


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(User(id="o", phone=OWNER, name="Shop", role="owner"))
    db.commit()
    return db


def _debtor(db, name, amount, phone):
    c = Customer(name=name, owner_phone=OWNER, customer_phone=phone, balance=0)
    db.add(c); db.flush()
    if amount:
        db.add(Transaction(customer_id=c.id, type="BUY", amount=amount, message_id=f"b-{uuid.uuid4()}"))
    db.commit()
    return c


def test_generates_a_draft_per_debtor_with_phone():
    db = _db()
    _debtor(db, "Ada", 5000, "2348001")
    _debtor(db, "Bola", 3000, "2348002")
    _debtor(db, "NoPhone", 2000, None)      # skipped — no phone
    _debtor(db, "Settled", 0, "2348003")     # skipped — owes nothing

    res = queue_debtor_reminders(db, OWNER)
    assert res["queued"] == 2 and res["no_phone"] == 1

    q = db.query(ReminderQueue).all()
    names = {x.customer_name for x in q}
    assert names == {"Ada", "Bola"}
    # each has a real message body with the customer's name + amount
    for x in q:
        assert x.customer_name.title() in x.message_text
        assert "balance" in x.message_text.lower()
        assert x.status == "PENDING_OWNER_CONFIRMATION"


def test_generation_is_idempotent_same_day():
    db = _db()
    _debtor(db, "Ada", 5000, "2348001")
    assert queue_debtor_reminders(db, OWNER)["queued"] == 1
    assert queue_debtor_reminders(db, OWNER)["queued"] == 0   # no duplicate
    assert db.query(ReminderQueue).count() == 1
