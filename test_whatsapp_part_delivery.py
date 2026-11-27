"""
Part delivery on WhatsApp (whatsapp_delivery.py), end to end through the
webhook: the cement seller sells 100, 60 go out, then 25 and 15 more.
"""
import pytest

import whatsapp_client
from models import Customer, InventoryItem, Transaction, TransactionItem
from test_whatsapp_pharmacy_flow import make_webhook_flow, onboard_business, set_user_plan

_numbers = iter(range(7000, 7999))


@pytest.fixture
def shop(monkeypatch):
    phone = f"234806123{next(_numbers):04d}"
    Session, sent, send = make_webhook_flow(monkeypatch, phone, "cement")
    fake = lambda to, m, *a, **k: sent.append((to, m))   # noqa: E731
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message", fake)
    import webhook_fallback_parser
    monkeypatch.setattr(webhook_fallback_parser, "send_whatsapp_message", fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    onboard_business(send, "Bello Cement", 2, 1)
    set_user_plan(Session, phone, "GO")
    db = Session()
    db.add(InventoryItem(owner_phone=phone, name="cement", unit="bag", quantity=120, selling_price=5000,
                         cost_price=4000, is_available=True))
    db.add(Customer(owner_phone=phone, name="Ade", customer_phone="2348031112222"))
    db.commit(); db.close()

    def say(text):
        before = len(sent)
        result = send(text)
        return result, "\n".join(m for to, m in sent[before:] if to == phone), sent[before:]
    return Session, say, phone


def _cement(Session, phone):
    db = Session()
    try:
        return db.query(InventoryItem).filter_by(owner_phone=phone, name="cement").one().quantity
    finally:
        db.close()


def test_sale_part_delivered_then_trips(shop):
    Session, say, phone = shop
    _, reply, _ = say("sold 100 cement to ade 500000 delivered 60")
    assert "Handed over now: 60" in reply and "still to deliver to Ade: 40" in reply
    result, reply, out = say("yes")
    assert result["status"] == "saved", reply
    assert _cement(Session, phone) == 60                       # 120 − 60 handed over
    db = Session()
    tx = db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone, Transaction.type == "BUY").one()
    line = db.query(TransactionItem).filter_by(transaction_id=tx.id).one()
    assert (tx.amount, line.quantity, line.delivered_qty, line.held_qty) == (500000, 100, 60, 40)
    db.close()
    receipt = "\n".join(m for to, m in out if to == "2348031112222")
    assert "Goods still to deliver" in receipt and "40 bag" in receipt

    _, reply, _ = say("stock")
    assert "40 kept aside for customers" in reply and "20 free to sell" in reply

    # Someone else can't buy what is kept for Ade
    _, reply, _ = say("sold 30 cement to musa 150000")
    assert "Only 20 bag of Cement can be sold" in reply and "kept aside" in reply

    _, reply, _ = say("who am i owing goods")
    assert "Ade" in reply and "40 bag of 100 bag" in reply

    _, reply, out = say("delivered 25 cement to ade")
    assert "25 bag Cement* handed over to Ade" in reply and "Still to deliver: 15 bag" in reply
    note = "\n".join(m for to, m in out if to == "2348031112222")
    assert "delivery note" in note and "Still to deliver: 15 bag" in note
    assert _cement(Session, phone) == 35

    _, reply, _ = say("ade collected 15 cement")
    assert "All delivered" in reply
    assert _cement(Session, phone) == 20
    _, reply, _ = say("ade collected 5 cement")                 # nothing left to wait for: no sale made
    assert "isn't waiting for any goods" in reply
    db = Session()
    assert db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone,
                                                       Transaction.type == "BUY").count() == 1
    db.close()


def test_numbers_are_never_taken_for_money(shop):
    Session, say, phone = shop
    for text in ("sold 100 cement to ade delivered 60", "Ade collected 35 cement paid 20000"):
        result, reply, _ = say(text)
        assert result["status"] == "part_delivery_help", (text, result)
        assert "Put the price in" in reply
    db = Session()
    assert db.query(Transaction).join(Customer).filter(Customer.owner_phone == phone).count() == 0
    db.close()
    assert _cement(Session, phone) == 120


def test_a_trip_for_goods_not_waiting_records_nothing(shop):
    Session, say, phone = shop
    _, reply, _ = say("delivered 10 cement to ade")
    assert "isn't waiting for any goods" in reply and "bought 10 cement" in reply
    assert _cement(Session, phone) == 120


def test_how_much_do_i_owe_suppliers(shop):
    # It used to be read as "who supplies 'how much do i owe'"
    from models import Supplier, SupplierPurchase
    Session, say, phone = shop
    db = Session()
    ayo = Supplier(owner_phone=phone, name="ayo")
    db.add(ayo); db.flush()
    db.add(SupplierPurchase(supplier_id=ayo.id, owner_phone=phone, product="cement", quantity=10,
                            total=50000, paid_amount=20000))
    db.commit(); db.close()
    for text in ("how much do i owe suppliers", "what am i owing my suppliers", "which supplier do i owe",
                 "supplier debt"):
        _, reply, _ = say(text)
        assert "30,000" in reply and "Ayo" in reply, (text, reply)      # the total AND who
    _, reply, _ = say("how do i pay my supplier")               # how-to still gets the steps
    assert "Pay" in reply and "Ayo: Debt" not in reply
    _, reply, _ = say("i paid ayo 20000")                       # the payment the answer suggests works
    _, reply, _ = say("yes")
    _, reply, _ = say("how much do i owe suppliers")
    assert "10,000" in reply, reply
