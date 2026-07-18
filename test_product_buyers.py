"""
Regression: "who buys sugar" must find buyers from itemised sales too (#8).

The select-product / cart flow stores Transaction.product as a comma-joined
summary ("sugar, rice") and the real products as TransactionItem rows. The
buyers lookup matched only Transaction.product with exact equality, so buyers
from any multi-item sale disappeared. It must match either the product field
or a line item.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, Transaction, TransactionItem, User
from reports import get_product_buyers

OWNER = "2348000000001"


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(User(id="u-owner", phone=OWNER, name="Shop", role="user"))
    db.commit()
    return db


def _customer(db, name):
    c = Customer(name=name, owner_phone=OWNER, balance=0)
    db.add(c); db.commit()
    return c


def _cart_sale(db, customer, products):
    """A multi-item sale: Transaction.product is a comma-joined summary, real
    products live in TransactionItem (mirrors the select-product flow)."""
    tx = Transaction(customer_id=customer.id, type="BUY", amount=1000,
                     product=", ".join(products), message_id=f"buy-{uuid.uuid4()}",
                     recorded_by_id="u-owner")
    db.add(tx); db.flush()
    for p in products:
        db.add(TransactionItem(transaction_id=tx.id, product=p, quantity=1, unit_price=500, total=500))
    db.commit()
    return tx


def _simple_sale(db, customer, product):
    tx = Transaction(customer_id=customer.id, type="BUY", amount=500,
                     product=product, message_id=f"buy-{uuid.uuid4()}", recorded_by_id="u-owner")
    db.add(tx); db.commit()
    return tx


def test_buyers_found_from_itemised_cart_sale():
    db = _db()
    ada = _customer(db, "Ada")
    _cart_sale(db, ada, ["sugar", "rice", "milk"])
    buyers = get_product_buyers(db, OWNER, "sugar")
    assert [b["name"] for b in buyers] == ["Ada"], buyers


def test_buyers_found_from_simple_sale():
    db = _db()
    bola = _customer(db, "Bola")
    _simple_sale(db, bola, "sugar")
    buyers = get_product_buyers(db, OWNER, "sugar")
    assert [b["name"] for b in buyers] == ["Bola"]


def test_buyers_combines_both_paths_without_duplicates():
    db = _db()
    ada = _customer(db, "Ada")
    bola = _customer(db, "Bola")
    _cart_sale(db, ada, ["sugar", "rice"])     # itemised
    _simple_sale(db, bola, "Sugar")            # simple, different case
    _cart_sale(db, ada, ["sugar"])             # Ada buys sugar again — still one row
    buyers = get_product_buyers(db, OWNER, "sugar")
    names = sorted(b["name"] for b in buyers)
    assert names == ["Ada", "Bola"], buyers
    ada_row = next(b for b in buyers if b["name"] == "Ada")
    assert ada_row["buy_count"] == 2           # two sugar purchases, deduped by tx


def test_non_buyer_not_listed():
    db = _db()
    ada = _customer(db, "Ada")
    _cart_sale(db, ada, ["rice", "milk"])
    assert get_product_buyers(db, OWNER, "sugar") == []
