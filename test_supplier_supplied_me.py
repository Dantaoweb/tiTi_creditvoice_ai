"""
"Ade supplied me cement 5000" (no "at"/"for") is a supplier purchase — it used
to record a customer debt for an item called "ade supplied me cement".
"Ade supplied me 5000" (no item) asks what was supplied and records nothing.
"""
import pytest

from models import Customer, InventoryItem, Supplier, SupplierPurchase, Transaction
from parser import parse_message
from test_whatsapp_part_delivery import shop  # noqa: F401


@pytest.mark.parametrize("text,product,qty,total,paid", [
    ("ade supplied me cement 5000", "cement", 1, 5000, 0),
    ("ade supplied me 10 bags cement 50000", "cement", 10, 50000, 0),
    ("ade supplied 10 bags cement 50000 paid 20000", "cement", 10, 50000, 20000),
    ("ade supplies me rice 30000 due friday", "rice", 1, 30000, 0),
    ("Ade supplied me 10 bags cement for 5000", "cement", 10, 5000, 0),      # the "for" form still works
])
def test_supplied_me_is_a_supplier_purchase(text, product, qty, total, paid):
    p = parse_message(text)
    assert (p["type"], p["action"], p["name"], p["product"], p["quantity"], p["buy_amount"], p["paid_amount"]) == \
        ("SUPPLIER_TRANSACTION", "SUPPLIER_PURCHASE", "ade", product, qty, total, paid)


def test_no_item_asks_and_lookalikes_unchanged():
    for text in ("ade supplied me 5000", "ade supplied 5000"):
        assert parse_message(text)["type"] == "SUPPLIER_ITEM_HELP"
    assert parse_message("ade bought cement 5000")["type"] == "TRANSACTION"
    assert parse_message("what did ade supply")["type"] == "SUPPLIER_HISTORY"
    assert parse_message("who supplies rice")["type"] == "PRODUCT_SUPPLIERS"


def test_supplied_me_end_to_end(shop):
    Session, say, phone = shop
    _, reply, _ = say("ade supplied me 10 bags cement 50000 paid 20000")
    if "yes" in reply.lower():
        say("yes")
    db = Session()
    try:
        sup = db.query(Supplier).filter(Supplier.owner_phone == phone).one()
        buy = db.query(SupplierPurchase).filter_by(supplier_id=sup.id).one()
        assert (sup.name.lower(), buy.total, buy.paid_amount) == ("ade", 50000, 20000)
        assert db.query(InventoryItem).filter_by(owner_phone=phone, name="cement").one().quantity == 130
        assert db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone).count() == 0
    finally:
        db.close()
    _, reply, _ = say("ade supplied me 5000")
    assert "What did Ade supply?" in reply
    db = Session()
    assert db.query(SupplierPurchase).filter(SupplierPurchase.owner_phone == phone).count() == 1
    db.close()
