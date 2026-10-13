"""
When it goes wrong after a sale — Ade bought 100 bags, 60 went out, and the
other 40 are called off and refunded; or delivered bags come back.

A numbered credit note records it. The sale is never edited. Cancelled bags
were never out of the store, so they're sellable again at once; returned bags
go back into stock if they can be sold, or stay out if damaged. The money is
taken off what Ade owes, or handed back.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from deliveries import (
    DeliveryError, cancel_undelivered, credit_note_text, goods_to_deliver, on_transaction_voided,
    reserved_by_item, return_goods, returnable_lines,
)
from inventory_suppliers import restore_inventory_for_voided_sale
from models import Customer, InventoryItem, Transaction, User
from reports import get_balance, profit_from_sales
from web_pos import get_pos_receipt, save_pos_sale

OWNER = "2348007000002"


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    s.add(User(id="owner-1", phone=OWNER, name="Bello Cement"))
    s.add(InventoryItem(owner_phone=OWNER, name="cement", unit="bag", quantity=300,
                        selling_price=9000, cost_price=8000, is_available=True))
    s.add(Customer(owner_phone=OWNER, name="ade", customer_phone="2348031111111", balance=0))
    s.commit()
    yield s
    s.close()


def _cement(db):
    return db.query(InventoryItem).filter_by(owner_phone=OWNER, name="cement").one()


def _ade(db):
    return db.query(Customer).filter_by(owner_phone=OWNER, name="ade").one()


def _sell(db, qty, delivered=None, paid=0, discount=0):
    item = {"inventory_item_id": _cement(db).id, "name": "cement", "qty": qty,
            "unit": "bag", "unit_price": 9000}
    if delivered is not None:
        item["delivered_qty"] = delivered
    r = save_pos_sale(db, OWNER, "owner-1", _ade(db).id, [item], paid, discount=discount)
    return r["receipt_id"]


def _key(db):
    return goods_to_deliver(db, OWNER)[0]["key"]


def test_undelivered_bags_cancelled_off_the_balance(db):
    _sell(db, 100, delivered=60)                       # owes 900,000; 40 reserved
    assert get_balance(db, _ade(db).id) == 900000
    note = cancel_undelivered(db, OWNER, "owner-1", _ade(db).id, _key(db), 40, "credit",
                              "Customer changed his mind")
    db.commit()
    assert note["number"] == "CN-0001" and note["amount"] == 360000
    assert get_balance(db, _ade(db).id) == 540000       # 60 bags' worth
    assert reserved_by_item(db, OWNER) == {} and goods_to_deliver(db, OWNER) == []
    assert _cement(db).quantity == 240                  # never left — just not reserved

    text = credit_note_text("Bello Cement", "Ade", note)
    assert "CN-0001" in text and "N360,000 taken off your balance" in text
    assert "Delivered: 60 bag" in text and "Cancelled: 40 bag" in text and "Nothing left to deliver" in text


def test_paid_bags_cancelled_and_money_handed_back(db):
    sale = _sell(db, 100, delivered=60, paid=900000)     # paid in full
    note = cancel_undelivered(db, OWNER, "owner-1", _ade(db).id, _key(db), 40, "refund", "Out of stock delay")
    db.commit()
    assert get_balance(db, _ade(db).id) == 0             # nobody owes anybody
    credit = db.query(Transaction).filter(Transaction.amount < 0).one()
    assert credit.type == "SALE" and credit.amount == -360000

    # Sales and profit count 60 bags, not 100
    sales = db.query(Transaction).filter(Transaction.type.in_(("SALE", "BUY")),
                                         Transaction.is_voided.isnot(True)).all()
    p = profit_from_sales(db, OWNER, sales)
    assert p["revenue"] == 540000 and p["cost"] == 60 * 8000

    # The sale keeps saying what was sold; the receipt shows the credit note
    receipt = get_pos_receipt(db, sale)
    assert receipt["total"] == 900000 and receipt["items"][0]["cancelled_qty"] == 40
    assert receipt["credit_notes"][0]["number"] == "CN-0001"
    assert get_pos_receipt(db, credit.id)["credit_note"]["sale_receipt"] is not None


def test_cancel_takes_the_newest_purchase_first_and_not_more_than_is_owed(db):
    _sell(db, 100, delivered=60)
    _sell(db, 35, delivered=0)
    with pytest.raises(DeliveryError, match="Only 75"):
        cancel_undelivered(db, OWNER, "owner-1", _ade(db).id, _key(db), 76, "credit", "x")
    with pytest.raises(DeliveryError, match="reason"):
        cancel_undelivered(db, OWNER, "owner-1", _ade(db).id, _key(db), 10, "credit", "  ")
    cancel_undelivered(db, OWNER, "owner-1", _ade(db).id, _key(db), 35, "credit", "Second order called off")
    db.commit()
    [row] = goods_to_deliver(db, OWNER)
    assert row["remaining"] == 40 and row["bought"] == 100


def test_delivered_bags_returned_sellable_go_back_into_stock(db):
    sale = _sell(db, 10)                                 # ordinary sale, all delivered
    assert _cement(db).quantity == 290
    assert returnable_lines(db, OWNER, sale)["lines"][0]["returnable"] == 10
    line_id = returnable_lines(db, OWNER, sale)["lines"][0]["line_id"]
    note = return_goods(db, OWNER, "owner-1", sale, [{"line_id": line_id, "quantity": 3}],
                        "credit", "sellable", "Wrong brand")
    db.commit()
    assert _cement(db).quantity == 293 and note["amount"] == 27000
    assert get_balance(db, _ade(db).id) == 90000 - 27000
    with pytest.raises(DeliveryError, match="Only 7"):
        return_goods(db, OWNER, "owner-1", sale, [{"line_id": line_id, "quantity": 8}],
                     "credit", "sellable", "x")


def test_damaged_returns_stay_out_of_stock(db):
    sale = _sell(db, 10)
    line_id = returnable_lines(db, OWNER, sale)["lines"][0]["line_id"]
    return_goods(db, OWNER, "owner-1", sale, [{"line_id": line_id, "quantity": 2}],
                 "refund", "damaged", "Bags torn")
    db.commit()
    assert _cement(db).quantity == 290


def test_a_refund_follows_the_discount(db):
    sale = _sell(db, 10, discount=9000)                  # 90,000 − 9,000 = 81,000 for 10
    line_id = returnable_lines(db, OWNER, sale)["lines"][0]["line_id"]
    note = return_goods(db, OWNER, "owner-1", sale, [{"line_id": line_id, "quantity": 5}],
                        "refund", "sellable", "Too many")
    assert note["amount"] == 40500                       # half of what was paid, not of list price


def test_voiding_a_credit_note_puts_things_back(db):
    _sell(db, 100, delivered=60)
    cancel_undelivered(db, OWNER, "owner-1", _ade(db).id, _key(db), 40, "credit", "Changed mind")
    db.commit()
    credit = db.query(Transaction).filter(Transaction.amount < 0).one()
    credit.is_voided = True
    on_transaction_voided(db, OWNER, credit, "owner-1")
    db.commit()
    assert get_balance(db, _ade(db).id) == 900000
    assert goods_to_deliver(db, OWNER)[0]["remaining"] == 40


def test_voiding_the_sale_voids_its_credit_notes(db):
    sale_id = _sell(db, 10)
    line_id = returnable_lines(db, OWNER, sale_id)["lines"][0]["line_id"]
    return_goods(db, OWNER, "owner-1", sale_id, [{"line_id": line_id, "quantity": 4}],
                 "credit", "sellable", "Wrong brand")
    db.commit()
    assert _cement(db).quantity == 294
    sale = db.get(Transaction, sale_id)
    sale.is_voided = True
    restore_inventory_for_voided_sale(db, OWNER, sale.id)
    on_transaction_voided(db, OWNER, sale, "owner-1")
    db.commit()
    assert get_balance(db, _ade(db).id) == 0             # not credited twice
    assert _cement(db).quantity == 300                   # exactly as before the sale
