"""
"Ade delivered cement 5000" — Ade may be a supplier who brought it or a
customer it went to. tiTi asks and records nothing (it used to record a
customer debt for an item called "delivered cement"). "Ade delivered ME
cement 5000" is a supplier purchase.
"""
import re

import pytest

from models import Customer, SupplierPurchase, Transaction
from parser import parse_message
from test_whatsapp_part_delivery import shop  # noqa: F401


@pytest.mark.parametrize("text", ["ade delivered cement 5000", "ade delivered 10 bags cement 50000",
                                  "ade delivered cement 5000 paid 2000"])
def test_which_way_is_asked(text):
    assert parse_message(text)["type"] == "DELIVERED_WHICH_WAY"


def test_delivered_me_is_a_supplier_and_others_unchanged():
    p = parse_message("ade delivered me 10 bags cement 50000 paid 20000")
    assert (p["type"], p["action"], p["product"], p["quantity"], p["buy_amount"], p["paid_amount"]) == \
        ("SUPPLIER_TRANSACTION", "SUPPLIER_PURCHASE", "cement", 10, 50000, 20000)
    assert parse_message("ade delivered cement for 5000")["action"] == "SUPPLIER_PURCHASE"
    assert parse_message("delivered 25 cement to ade")["type"] == "DELIVER_GOODS"
    assert parse_message("ade bought cement 5000")["type"] == "TRANSACTION"


def test_asks_records_nothing_and_every_example_works(shop):
    Session, say, phone = shop
    for text in ("ade delivered cement 5000", "ade delivered 10 bags cement 50000"):
        _, reply, _ = say(text)
        assert "Did Ade *bring* you" in reply and "Nothing was recorded" in reply
        examples = re.findall(r"_([^_\n]+)_", reply)
        assert len(examples) == 3, reply
        kinds = [parse_message(e)["type"] for e in examples]
        assert kinds == ["SUPPLIER_TRANSACTION", "TRANSACTION", "DELIVER_GOODS"], (examples, kinds)
    db = Session()
    try:
        assert db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone).count() == 0
        assert db.query(SupplierPurchase).filter(SupplierPurchase.owner_phone == phone).count() == 0
    finally:
        db.close()
