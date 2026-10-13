"""
A salon's and a consultant's first hour on WhatsApp, through the real webhook.

Each step here was broken when a new user was walked through by hand:
- "Amaka braids 15000 paid 10000" saved a payment by "Amaka Braids 15000"
- "Kemi audit 150000 due friday" and "Dangote Ltd ..." weren't understood
  ("Dangote" + a job called "ltd consulting fee")
- "I received 8000 for haircut" warned "Stock item not found: Haircut"
- "add price list" wasn't understood, and anything typed while the price list
  was open crashed (an undefined name in the pending router)
- profit for a salon said "add a cost when you add stock"
- "invoice" wasn't understood
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

import whatsapp_client
from models import Customer
from parser import parse_message
from test_whatsapp_pharmacy_flow import make_webhook_flow, onboard_business


_numbers = iter(range(9000, 9999))


def _business(monkeypatch, name, category, btype):
    phone = f"234805123{next(_numbers):04d}"      # one per test: tiTi rate-limits a phone
    Session, sent, send = make_webhook_flow(monkeypatch, phone, "service")
    fake = lambda to, m, *a, **k: sent.append((to, m))
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message", fake)
    import webhook_fallback_parser
    monkeypatch.setattr(webhook_fallback_parser, "send_whatsapp_message", fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    onboard_business(send, name, category, btype)

    def say(text):
        before = len(sent)
        result = send(text)
        return result, "\n".join(m for to, m in sent[before:] if to == phone)

    return Session, say, phone


@pytest.fixture
def salon(monkeypatch):
    return _business(monkeypatch, "Glow Hair Studio", 4, 1)


@pytest.fixture
def consultant(monkeypatch):
    return _business(monkeypatch, "Bayo Advisory", 10, 5)


def _balance(Session, phone, name):
    db = Session()
    try:
        c = db.query(Customer).filter(Customer.owner_phone == phone, Customer.name == name).first()
        return None if c is None else c.balance
    finally:
        db.close()


@pytest.mark.parametrize("text,name,action,total,paid,product", [
    ("Amaka braids 15000 paid 10000", "amaka", "COMBINED", 15000, 10000, "braids"),
    ("Mama Bisi retouch 8000", "mama bisi", "BUY", 8000, 0, "retouch"),
    ("Dangote Ltd consulting fee 500000 paid 200000", "dangote ltd", "COMBINED", 500000, 200000, "consulting fee"),
    ("Kemi audit 150000 due friday", "kemi", "BUY", 150000, 0, "audit"),
])
def test_a_job_jotted_down_without_a_verb(text, name, action, total, paid, product):
    p = parse_message(text)
    assert (p["name"], p["action"], p["buy_amount"], p["paid_amount"], p["product"]) == (
        name, action, total, paid, product)


@pytest.mark.parametrize("text", ["rent 50000", "rent 50000 paid 20000", "add rice 20", "Ade 5000"])
def test_no_name_is_made_of_numbers_or_commands(text):
    p = parse_message(text)
    assert not p or p.get("type") != "TRANSACTION"


def test_salon_first_hour(salon):
    Session, say, phone = salon
    r, _text = say("add price list")
    assert r["status"] == "guided_service_started"
    _r, text = say("Amaka braids 15000 paid 10000")           # while the price list is open
    assert "Price list not saved yet" in text and "Paid: N10,000" in text
    say("yes")
    assert _balance(Session, phone, "amaka") == 5000

    say("I received 8000 for haircut")
    _r, text = say("yes")
    assert "Saved" in text and "Stock item not found" not in text

    say("Amaka paid 5000"); say("yes")
    assert _balance(Session, phone, "amaka") == 0

    _r, text = say("my profit this month")
    assert "add stock" not in text.lower() and "Expenses" in text


def test_consultant_first_hour(consultant):
    Session, say, phone = consultant
    say("Dangote Ltd consulting fee 500000 paid 200000"); say("yes")
    say("Kemi audit 150000 due friday"); say("yes")
    say("Dangote Ltd paid 100000"); say("yes")
    assert _balance(Session, phone, "dangote ltd") == 200000
    assert _balance(Session, phone, "dangote") is None
    r, text = say("remind Kemi")
    assert r["status"] == "remind_by_name" and "due on" in text
    r, _text = say("invoice")
    assert r["status"] == "app_guide"
