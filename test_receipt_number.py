"""
Receipt numbers are per-business (1, 2, 3 for each business), not the global
transaction id.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import uuid

from database import Base
from models import User, Customer, Transaction
from web_pos import save_pos_sale, get_pos_receipt, next_receipt_number


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _sale(db, owner_phone, owner_id):
    r = save_pos_sale(db, owner_phone, owner_id, None,
                      [{"name": "x", "qty": 1, "unit_price": 100}], 100)
    rec = get_pos_receipt(db, r["receipt_id"], user=db.query(User).filter(User.phone == owner_phone).first())
    return rec["receipt_number"], r["receipt_id"]


def test_receipt_numbers_are_per_business():
    db = _db()
    db.add(User(id="a", phone="234800000111", name="A", role="owner"))
    db.add(User(id="b", phone="234800000222", name="B", role="owner"))
    db.commit()

    # Business A: three sales → 1, 2, 3
    a_nums = [_sale(db, "234800000111", "a")[0] for _ in range(3)]
    assert a_nums == [1, 2, 3]

    # Business B starts fresh at 1, even though global tx ids continue
    b_num, b_txid = _sale(db, "234800000222", "b")
    assert b_num == 1
    assert b_txid > 3            # global id kept climbing; the receipt # did not


def test_debt_payment_gets_per_business_receipt_number():
    """A standalone debt payment (PAY) must carry its own per-business receipt
    number and expose it on the receipt — not fall back to the global tx id."""
    db = _db()
    db.add(User(id="o", phone="234800000333", name="Shop", role="owner"))
    db.commit()

    # Two sales first → the owner counter is now at 2
    _sale(db, "234800000333", "o")
    _sale(db, "234800000333", "o")

    cust = Customer(owner_phone="234800000333", name="ada", customer_phone="234800000999")
    db.add(cust)
    db.commit()
    db.add(Transaction(customer_id=cust.id, type="BUY", amount=5000,
                       product="goods", recorded_by_id="o", message_id="m1"))
    db.commit()

    # Record a debt payment the way the web pay endpoint now does
    pay = Transaction(
        customer_id=cust.id, type="PAY", amount=2000, product="Payment",
        recorded_by_id="o", message_id=f"web-pay-{uuid.uuid4()}",
        receipt_number=next_receipt_number(db, "234800000333"),
    )
    db.add(pay)
    db.commit()

    owner = db.query(User).filter(User.phone == "234800000333").first()
    rec = get_pos_receipt(db, pay.id, user=owner)
    assert rec["type"] == "PAY"
    assert "receipt_number" in rec           # PAY branch must expose the field
    assert rec["receipt_number"] == 3        # continues the per-business sequence
    assert pay.id > 3                         # global id is larger — number is not the id
