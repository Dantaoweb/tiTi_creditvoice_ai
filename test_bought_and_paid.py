"""
A sale with a payment, through WhatsApp: the item, quantity and stock are kept.
- "Ade bought 2 bags rice 10000 paid 5000" (already worked — kept working)
- "Ade bought rice paid 2000 balance 3000" (no price: paid + balance is the
  price; it made a customer called "ade bought rice")
- "Ade bought 2 bags rice paid 5000" (no price: the stock price settles it;
  the item used to be dropped)
- "sold 100 cement to Ade 500000 paid 200000 delivered 60" (part paid AND
  part delivered; it was refused as "one product at a time")
"""
import pytest

from models import Customer, InventoryItem, Transaction, TransactionItem
from test_whatsapp_part_delivery import shop  # noqa: F401


@pytest.fixture
def rice_shop(shop):
    Session, say, phone = shop
    db = Session()
    db.add(InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=50, selling_price=5000,
                         is_available=True))
    db.commit(); db.close()
    return shop


def _records(Session, phone):
    db = Session()
    try:
        out = []
        for t in db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone).order_by(Transaction.id):
            items = [(i.product, i.quantity) for i in db.query(TransactionItem).filter_by(transaction_id=t.id)]
            out.append((db.get(Customer, t.customer_id).name.lower(), t.type, t.amount, items))
        return out
    finally:
        db.close()


def _stock(Session, phone, name):
    db = Session()
    try:
        return db.query(InventoryItem).filter_by(owner_phone=phone, name=name).one().quantity
    finally:
        db.close()


@pytest.mark.parametrize("text,total,paid,qty", [
    ("ade bought 2 bags rice 10000 paid 5000", 10000, 5000, 2),
    ("ade bought rice paid 2000 balance 3000", 5000, 2000, 1),
    ("ade bought 2 bags rice paid 5000 balance 5000", 10000, 5000, 2),
])
def test_bought_and_paid_keeps_the_item(rice_shop, text, total, paid, qty):
    Session, say, phone = rice_shop
    say(text)
    result, reply, _ = say("yes")
    assert result["status"] == "saved", reply
    assert _records(Session, phone) == [("ade", "BUY", total, [("rice", qty)]), ("ade", "PAY", paid, [])]
    assert _stock(Session, phone, "rice") == 50 - qty


def test_no_price_uses_the_stock_price(rice_shop):
    Session, say, phone = rice_shop
    _, reply, _ = say("ade bought 2 bags rice paid 5000")
    if "yes" not in reply.lower():          # tiTi may confirm the stock price first
        say("1")
    result, reply, _ = say("yes")
    assert result["status"] == "saved", reply
    recs = _records(Session, phone)
    assert recs[0][:3] == ("ade", "BUY", 10000) and recs[1][:3] == ("ade", "PAY", 5000), recs
    assert _stock(Session, phone, "rice") == 48


def test_part_paid_and_part_delivered(shop):
    Session, say, phone = shop
    _, reply, _ = say("sold 100 cement to ade 500000 paid 200000 delivered 60")
    assert "still to deliver to Ade: 40" in reply, reply
    result, reply, _ = say("yes")
    assert result["status"] == "saved", reply
    assert _stock(Session, phone, "cement") == 60
    db = Session()
    try:
        buy = db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone,
                                                           Transaction.type == "BUY").one()
        line = db.query(TransactionItem).filter_by(transaction_id=buy.id).one()
        assert (buy.amount, line.quantity, line.delivered_qty, line.held_qty) == (500000, 100, 60, 40)
        assert db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone,
                                                           Transaction.type == "PAY").one().amount == 200000
    finally:
        db.close()
