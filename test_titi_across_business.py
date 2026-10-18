"""
tiTi answers in each business's own terms, and reads amounts the way people
say them: "10 crates eggs 35000" is ₦35,000 for all ten (not ₦350,000);
"at 60000" / "60000 each" is the price of one; and when the product's stock
price says the bare amount was the price of one, it is.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

import whatsapp_client
from business_templates import BUSINESS_CATEGORIES
from models import Customer, User
from test_whatsapp_pharmacy_flow import make_webhook_flow, onboard_business

_numbers = iter(range(1000, 9999))
CAT = {key: (ci, ti) for ci, cat in enumerate(BUSINESS_CATEGORIES, start=1)
       for ti, (key, _l) in enumerate(cat["businesses"], start=1)}


def _business(monkeypatch, btype):
    phone = f"234806234{next(_numbers):04d}"
    Session, sent, send = make_webhook_flow(monkeypatch, phone, f"acr{btype[:4]}")
    fake = lambda to, m, *a, **k: sent.append((to, m))
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message", fake)
    import webhook_fallback_parser
    monkeypatch.setattr(webhook_fallback_parser, "send_whatsapp_message", fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    onboard_business(send, f"Test {btype}", *CAT[btype])
    db = Session()
    u = db.query(User).filter(User.phone == phone).one()
    u.subscription_plan = "PRO"; u.subscription_status = "ACTIVE"; db.commit(); db.close()

    def say(text):
        before = len(sent)
        result = send(text)
        return result, "\n".join(m for to, m in sent[before:] if to == phone)

    def balance(name):
        db = Session()
        try:
            c = db.query(Customer).filter(Customer.owner_phone == phone, Customer.name == name).first()
            return c.balance if c else None
        finally:
            db.close()
    return say, balance


def test_a_bare_amount_is_the_total(monkeypatch):
    say, balance = _business(monkeypatch, "poultry_farm")
    _r, text = say("Bayo bought 10 crates eggs 35000")
    assert "N35,000" in text and "N350,000" not in text
    assert "price of *one*" in text                   # says how to mean "each"
    say("yes")
    assert balance("bayo") == 35000


def test_at_and_each_are_the_price_of_one(monkeypatch):
    say, balance = _business(monkeypatch, "provision_store")
    say("Ade bought 2 bags rice at 60000"); say("yes")
    say("Bola bought 2 bags rice 60000 each"); say("yes")
    assert balance("ade") == 120000 and balance("bola") == 120000


def test_the_stock_price_settles_a_bare_amount(monkeypatch):
    say, balance = _business(monkeypatch, "provision_store")
    say("add stock rice 20 bags cost 50000 sell 60000"); say("yes")
    say("Kemi bought 2 bags rice 60000"); say("yes")          # rice is ₦60,000 a bag
    say("Ade bought 2 bags rice 120000"); say("yes")          # the total
    assert balance("kemi") == 120000 and balance("ade") == 120000


@pytest.mark.parametrize("btype,data,word", [
    ("hair_salon", "Amaka braids 15000 paid 10000", "1 client* owes you"),
    ("property_manager", "Mr Bello rent 300000 paid 100000", "1 tenant* owes you"),
    ("provision_store", "Ade bought rice 5000", "1 customer* owes you"),
])
def test_who_owes_me_in_the_business_own_words(monkeypatch, btype, data, word):
    say, _b = _business(monkeypatch, btype)
    say(data); say("yes")
    _r, text = say("who owes me")
    assert word in text, text


def test_a_school_sees_fees_collected_today(monkeypatch):
    say, _b = _business(monkeypatch, "private_school")
    say("Tunde paid school fees 50000"); say("yes")
    _r, text = say("how much did I sell today")
    assert "Fees received today: *₦50,000*" in text, text


# ── Sentences that read like a sale but aren't one ────────────────────────────

@pytest.mark.parametrize("text,why", [
    ("the man wey come yesterday carry two of them", "described"),
    ("my brother take three yesterday", "described"),
    ("the customer that came today paid 5000", "described"),
    ("Ade paid two", "word_amount"),
])
def test_unclear_sales_get_asked_not_guessed(monkeypatch, text, why):
    from parser import parse_message, why_not_a_transaction
    assert parse_message(text) is None and why_not_a_transaction(text) == why
    say, _b = _business(monkeypatch, "provision_store")
    r, reply = say(text)
    assert r["status"] == f"unclear_sale_{why}"
    assert ("who" in reply.lower()) if why == "described" else ("figures" in reply)


@pytest.mark.parametrize("text,name,amount", [
    ("Ade paid five thousand", "ade", 5000),                 # used to save ₦5
    ("Ade paid two hundred and fifty", "ade", 250),
    ("Ade paid 1.5 million", "ade", 1500000),
    ("Mama Bisi collected rice 3000", "mama bisi", 3000),
    ("my customer Ade paid 5000", "ade", 5000),
    ("Last Born Stores paid 5000", "last born stores", 5000),
    ("Alhaji Musa Danladi paid 20000", "alhaji musa danladi", 20000),
    ("Ade paid 50", "ade", 50),                              # small, but typed in figures
])
def test_real_names_and_amounts_in_words_still_work(text, name, amount):
    from parser import parse_message
    p = parse_message(text)
    assert p and p["name"] == name and max(p["paid_amount"] or 0, p["buy_amount"] or 0) == amount
