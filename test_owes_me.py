"""
"Ade owes me 5000" records a debt of 5000 for Ade with no item — it used to
make "ade owes me" the product ("ade dey owe me" made a customer "ade dey").
"I owe Ade 5000" is money the business owes, so nothing is recorded on Ade.
"""
import pytest

from models import Customer, Transaction, TransactionItem
from parser import parse_message
from test_whatsapp_part_delivery import shop  # noqa: F401  (WhatsApp shop fixture)


@pytest.mark.parametrize("text,name,amount", [
    ("ade owes me 5000", "ade", 5000), ("Ade is owing me 5k", "ade", 5000), ("ade dey owe me 5000", "ade", 5000),
    ("ade owes 5000", "ade", 5000), ("ade has a debt of 5000", "ade", 5000),
    ("mama bola owes me 12,000", "mama bola", 12000), ("my customer ade owes me 5000", "ade", 5000),
])
def test_owes_me_is_a_debt_with_no_item(text, name, amount):
    p = parse_message(text)
    assert (p["type"], p["action"], p["name"], p["buy_amount"], p["product"]) == ("TRANSACTION", "BUY", name, amount, None)


def test_due_date_kept_and_lookalikes_unchanged():
    assert parse_message("ade owes me 5000 due friday")["due_date"] is not None
    assert parse_message("i owe ade 5000")["type"] == "I_OWE_HELP"
    assert parse_message("who owes me")["type"] == "UNPAID_DEBTORS"
    assert parse_message("ade bought rice 5000")["product"] == "rice"
    assert parse_message("ade paid 5000")["action"] == "PAY"
    assert parse_message("ade owes me?") is None


def test_owes_me_end_to_end(shop):
    Session, say, phone = shop
    _, reply, _ = say("ade dey owe me 5000")
    assert "No product details captured" not in reply
    result, reply, _ = say("yes")
    assert result["status"] == "saved", reply
    db = Session()
    try:
        tx = db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone).one()
        assert (tx.type, tx.amount, db.get(Customer, tx.customer_id).name.lower()) == ("BUY", 5000, "ade")
        assert db.query(TransactionItem).filter_by(transaction_id=tx.id).count() == 0     # no "ade owes me" item
        assert db.query(Customer).filter(Customer.owner_phone == phone,
                                         Customer.name.ilike("ade dey%")).count() == 0
    finally:
        db.close()
    _, reply, _ = say("i owe ade 5000")
    assert "money *you* owe Ade" in reply and "supplied me 10 bags cement for 5000" in reply
    db = Session()
    assert db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone).count() == 1
    db.close()
