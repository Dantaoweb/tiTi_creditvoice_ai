"""
A new shop owner's first hour on WhatsApp, through the real webhook handler.

Each step here was broken when a new user was walked through by hand:
- "add stock rice 20 bags ..." saved a product called "rice 20" with 0 stock,
  so no sale ever reduced it ("Stock item not found")
- after "Ade balance" every message was read as a choice in that view
- a payment got advice to add product details
- a cash sale was called "service/direct income"
- the guided sale lost the whole sale when a command came at the due-date step,
  and "friday" wasn't a date anywhere ("due friday" was silently dropped)
- the same product added twice made two cart lines
- "remind Bola" wasn't understood
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

import whatsapp_client
from models import Customer, InventoryItem, Transaction, User
from test_whatsapp_pharmacy_flow import make_webhook_flow, onboard_business


_numbers = iter(range(9000, 9999))


@pytest.fixture
def shop(monkeypatch):
    phone = f"234803123{next(_numbers):04d}"      # one per test: tiTi rate-limits a phone
    Session, sent, send = make_webhook_flow(monkeypatch, phone, "journey")
    fake = lambda to, m, *a, **k: sent.append((to, m))
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message", fake)
    import webhook_fallback_parser
    monkeypatch.setattr(webhook_fallback_parser, "send_whatsapp_message", fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    onboard_business(send, "Mama Ngozi Stores", 1, 1)

    def say(text):
        before = len(sent)
        result = send(text)
        return result, "\n".join(m for to, m in sent[before:] if to == phone)

    return Session, say, phone


def _item(Session, phone, name):
    db = Session()
    try:
        return db.query(InventoryItem).filter(InventoryItem.owner_phone == phone,
                                              InventoryItem.name == name).first()
    finally:
        db.close()


def test_add_stock_product_first_then_sales_reduce_it(shop):
    Session, say, phone = shop
    _r, text = say("add stock rice 20 bags cost 50000 sell 60000")
    assert "Rice — 20 bag" in text
    say("yes")
    rice = _item(Session, phone, "rice")
    assert rice is not None and rice.quantity == 20

    _r, text = say("I sold 2 bags rice at 60000")
    assert "Confirm cash sale" in text and "service/direct income" not in text
    _r, text = say("yes")
    assert "Stock item not found" not in text and "18 bag left" in text

    _r, text = say("Ade bought 1 bag rice 60000 paid 20000")
    assert "Ade bought" in text                                   # capitalised
    say("yes")
    assert _item(Session, phone, "rice").quantity == 17


def test_a_payment_gets_no_product_advice(shop):
    _Session, say, _phone = shop
    say("Ade bought rice 5000"); say("yes")
    _r, text = say("Ade paid 2000")
    assert "Ade paid N2,000" in text
    assert "No product details" not in text


def test_the_balance_view_lets_you_move_on(shop):
    _Session, say, _phone = shop
    say("add stock rice 20 bags cost 50000 sell 60000"); say("yes")
    say("Ade bought 1 bag rice 60000"); say("yes")
    r, _text = say("Ade balance")
    assert r["status"] == "customer_summary_menu"
    r, text = say("stock")
    assert r["status"] == "inventory_list" and "Rice" in text
    r, _text = say("summary")
    assert r["status"] == "dashboard_summary"


def test_guided_sale_survives_a_command_and_takes_a_day_name(shop):
    Session, say, phone = shop
    say("add stock beans 10 bags cost 40000 sell 48000"); say("yes")
    say("select product"); say("1"); say("2")
    say("1"); say("1"); say("2")                                  # the same product again
    _r, text = say("discount 5000")
    assert "Beans x 4" in text and "Total:    N187,000" in text
    say("2"); say("Chika"); say("50000")

    _r, text = say("summary")                                     # a command mid-checkout
    assert "isn't saved yet" in text
    r, _text = say("friday")
    assert r["status"] == "select_product_confirm_shown"
    _r, text = say("yes")
    assert text.index("Discount: -N5,000") < text.index("Total:")  # above the total
    assert "6 bag left" in text

    db = Session()
    try:
        chika = db.query(Customer).filter(Customer.owner_phone == phone, Customer.name == "chika").one()
        assert chika.balance == 137000
        sale = db.query(Transaction).filter(Transaction.customer_id == chika.id, Transaction.type == "BUY").one()
        assert sale.due_date is not None and sale.due_date.strftime("%A") == "Friday"
    finally:
        db.close()


def test_due_friday_in_a_typed_sale_is_kept(shop):
    Session, say, phone = shop
    _r, text = say("Bola bought beans 48000 due friday")
    assert "Due:" in text
    say("yes")
    db = Session()
    try:
        bola = db.query(Customer).filter(Customer.owner_phone == phone, Customer.name == "bola").one()
        sale = db.query(Transaction).filter(Transaction.customer_id == bola.id).one()
        assert sale.due_date is not None and sale.due_date.strftime("%A") == "Friday"
    finally:
        db.close()


def test_summary_and_report_are_understood(shop):
    _Session, say, _phone = shop
    for word in ("summary", "report", "today summary"):
        r, _t = say(word)
        assert r["status"] == "dashboard_summary", word


def test_remind_by_name(shop):
    _Session, say, _phone = shop
    say("Bola bought beans 48000"); say("yes")
    r, text = say("remind Bola")
    assert r["status"] == "remind_by_name" and "₦48,000" in text
    r, _text = say("remind Tunde")
    assert r["status"] == "remind_customer_not_found"
