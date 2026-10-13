"""
Goods sold but not all delivered — the cement seller's case.

Ade buys 100 bags, 60 go out; later buys 35 more, none go out. 75 are still
his, waiting in the store: they stay in stock as *reserved* and can't be sold
to anyone else, each trip takes them out of stock, and the customer is told
bought · delivered · still to deliver.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from deliveries import (
    DeliveryError, deliver_goods, delivery_note_text, goods_to_deliver, reserved_by_item,
)
from inventory_suppliers import restore_inventory_for_voided_sale
from models import Customer, InventoryItem, User
from web_pos import format_receipt_text, get_pos_receipt, save_pos_sale

OWNER = "2348007000001"


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    s.add(User(id="owner-1", phone=OWNER, name="Bello Cement"))
    s.add(InventoryItem(owner_phone=OWNER, name="cement", unit="bag", quantity=300,
                        selling_price=9000, cost_price=8000, is_available=True))
    s.add(Customer(owner_phone=OWNER, name="ade", customer_phone="2348031111111"))
    s.commit()
    yield s
    s.close()


def _cement(db):
    return db.query(InventoryItem).filter_by(owner_phone=OWNER, name="cement").one()


def _ade(db):
    return db.query(Customer).filter_by(owner_phone=OWNER, name="ade").one()


def _sell(db, qty, delivered=None, customer=True, paid=0):
    item = {"inventory_item_id": _cement(db).id, "name": "cement", "qty": qty,
            "unit": "bag", "unit_price": 9000}
    if delivered is not None:
        item["delivered_qty"] = delivered
    return save_pos_sale(db, OWNER, "owner-1", _ade(db).id if customer else None,
                         [item], paid)


def test_the_cement_story(db):
    first = _sell(db, 100, delivered=60)
    assert _cement(db).quantity == 240                        # only 60 left the store
    _sell(db, 35, delivered=0)
    assert _cement(db).quantity == 240

    [row] = goods_to_deliver(db, OWNER, _ade(db).id)
    assert (row["bought"], row["delivered"], row["remaining"]) == (135, 60, 75)
    assert reserved_by_item(db, OWNER) == {_cement(db).id: 75}

    # The receipt says what went out at the sale and what's still to come
    receipt = get_pos_receipt(db, first["receipt_id"])
    assert receipt["items"][0]["delivered_qty"] == 60 and receipt["items"][0]["to_deliver"] == 40
    assert "Delivered now: 60 · To deliver: 40" in format_receipt_text(receipt)

    # A trip of 25: out of stock, oldest sale first
    done = deliver_goods(db, OWNER, "owner-1", _ade(db).id, row["key"], 25, "Truck KJA 123")
    db.commit()
    assert (done["bought"], done["delivered"], done["remaining"]) == (135, 85, 50)
    assert _cement(db).quantity == 215
    note = delivery_note_text("Bello Cement", "Ade", done)
    assert "*25 bag*" in note and "Still to deliver: 50 bag" in note and "KJA 123" in note

    # The receipt still says what happened at the sale
    assert get_pos_receipt(db, first["receipt_id"])["items"][0]["delivered_qty"] == 60

    # Can't deliver more than is owed
    with pytest.raises(DeliveryError):
        deliver_goods(db, OWNER, "owner-1", _ade(db).id, row["key"], 51)

    deliver_goods(db, OWNER, "owner-1", _ade(db).id, row["key"], 50)
    db.commit()
    assert goods_to_deliver(db, OWNER) == [] and _cement(db).quantity == 165


def test_reserved_bags_cant_be_sold_again(db):
    _sell(db, 100, delivered=0)                               # 300 in store, 100 reserved
    with pytest.raises(ValueError, match="Only 200 bag of Cement available"):
        _sell(db, 201, customer=False)
    _sell(db, 200, customer=False)                            # exactly what's available
    assert _cement(db).quantity == 100


def test_goods_left_behind_need_a_customer(db):
    with pytest.raises(ValueError, match="Pick the customer"):
        _sell(db, 10, delivered=5, customer=False)


def test_an_ordinary_sale_is_all_delivered(db):
    _sell(db, 10)
    _sell(db, 10, delivered=10)                               # all of it, said explicitly
    assert _cement(db).quantity == 280 and goods_to_deliver(db, OWNER) == []


def test_voiding_the_sale_returns_what_was_delivered_later(db):
    sale = _sell(db, 100, delivered=60)
    [row] = goods_to_deliver(db, OWNER)
    deliver_goods(db, OWNER, "owner-1", _ade(db).id, row["key"], 40)
    db.commit()
    assert _cement(db).quantity == 200

    from models import Transaction
    tx = db.get(Transaction, sale["receipt_id"])
    tx.is_voided = True
    restore_inventory_for_voided_sale(db, OWNER, tx.id)
    db.commit()
    assert _cement(db).quantity == 300                       # 60 at the sale + 40 later


def test_the_statement_lists_goods_still_to_deliver(db):
    from customer_statement import build_balance_message
    _sell(db, 100, delivered=60)
    owner = db.query(User).filter_by(phone=OWNER).one()
    text = build_balance_message(db, owner, _ade(db))
    assert "Goods still to deliver:" in text and "Cement — 40 bag still to deliver (of 100 bag)" in text
