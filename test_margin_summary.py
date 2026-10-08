"""
The Dashboard's "Discount gap": what sales would have made at the selling
price, minus what they were actually recorded at.

It used to add up credit-sale lines from EVERY business on the platform (no
owner filter), skip cash sales, count voided ones, and miss a discount taken
off the whole sale. These tests pin each of those down.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-margin-summary-0000000000")

import uuid

import main  # noqa: F401  (creates the tables)
from database import SessionLocal
from models import Customer, InventoryItem, Transaction, TransactionItem, User
from reports import get_margin_summary

_seq = iter(range(100, 999))


def _business(db):
    phone = f"2348074{next(_seq):06d}"
    owner = User(phone=phone, name="Shop")
    db.add(owner)
    db.add(InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=50, selling_price=1000))
    cust = Customer(owner_phone=phone, name="Ada", balance=0)
    db.add(cust)
    db.commit()
    return phone, owner, cust


def _sale(db, owner, cust, amount, lines, kind="BUY", voided=False):
    tx = Transaction(customer_id=cust.id if cust else None, type=kind, amount=amount,
                     recorded_by_id=owner.id, message_id=f"m-{uuid.uuid4()}", is_voided=voided)
    db.add(tx); db.flush()
    for qty, price in lines:
        db.add(TransactionItem(transaction_id=tx.id, product="rice", quantity=qty,
                               unit_price=price, total=qty * price))
    db.commit()


def test_another_business_sales_never_count():
    db = SessionLocal()
    try:
        a_phone, a_owner, a_cust = _business(db)
        b_phone, b_owner, b_cust = _business(db)
        _sale(db, a_owner, a_cust, 2000, [(2, 1000)])         # A: full price
        _sale(db, b_owner, b_cust, 500, [(5, 100)])           # B: deep discount

        a = get_margin_summary(db, a_phone)
        assert a["expected"] == 2000 and a["actual"] == 2000 and a["discount_gap"] == 0
        b = get_margin_summary(db, b_phone)
        assert b["discount_gap"] == 4500
    finally:
        db.close()


def test_cash_sales_and_whole_sale_discounts_count_voided_do_not():
    db = SessionLocal()
    try:
        phone, owner, cust = _business(db)
        _sale(db, owner, None, 1800, [(2, 900)], kind="SALE")     # cash, 100 off each line
        _sale(db, owner, cust, 2500, [(3, 1000)])                 # N500 off the whole sale
        _sale(db, owner, cust, 1, [(4, 1000)], voided=True)       # voided: ignored

        m = get_margin_summary(db, phone)
        assert m["expected"] == 5000
        assert m["actual"] == 4300
        assert m["discount_gap"] == 700
    finally:
        db.close()
