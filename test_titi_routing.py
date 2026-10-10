"""
tiTi answers questions about every part of the app with the right answer.

Questions are tried as transactions first, then as guides/FAQ. These pin the
routes that used to go wrong: a question recorded as a sale, and specific
features (discount, invoices, expenses, fakes...) swallowed by the generic
"customer" guide.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from faq import detect_faq, get_faq_answer
from messages import build_app_guide_message
from parser import parse_message


def route(q):
    """What tiTi would answer with, before any AI fallback."""
    p = parse_message(q)
    if p:
        if p["type"] == "APP_GUIDE":
            return f"guide:{p['topic']}"
        return p["type"]
    f = detect_faq(q)
    return f"faq:{f}" if f else "ai"


def test_a_question_is_never_recorded_as_a_sale():
    assert parse_message("can i give 10% discount?") is None
    assert parse_message("should i give him credit 5000?") is None
    assert parse_message("Ade paid 5000")["type"] == "TRANSACTION"      # a real one still is


@pytest.mark.parametrize("question, expected", [
    ("how do i give a customer discount?", "guide:discount"),
    ("how do i send invoice to my customer?", "guide:invoices"),
    ("my customer paid part of his debt how do i record it?", "guide:record_payment"),
    ("how do i send reminder to customers?", "guide:reminder"),
    ("how do i tell customer order is ready?", "guide:delivery_date"),
    ("how do i report fake product?", "guide:fake_product"),
    ("how can i know if a product is original?", "guide:fake_product"),
    ("how do i scan barcode?", "guide:barcode_scan"),
    ("how do i record expenses?", "guide:expenses"),
    ("how can my staff share expenses with me?", "guide:expenses"),
    ("how do i become a verified supplier?", "guide:supplier_directory"),
    ("how do i pay my supplier?", "guide:supplier_owed"),
    ("how can i get a loan?", "guide:finance_scorecard"),
    ("how do i write a review?", "guide:site_review"),
    ("how much do i owe my suppliers?", "faq:supplier_owed"),
    ("how do i record school fees?", "faq:school_fees"),
    ("how do i record eggs collected?", "faq:poultry"),
    ("how do i record fuel sales?", "faq:fuel_station"),
    ("how do i change my pin?", "faq:pin_help"),
    ("i forgot my pin", "faq:pin_help"),
    ("how do i pay with card?", "faq:upgrade"),
    ("where is the till?", "faq:where:/pos"),
])
def test_questions_reach_the_right_answer(question, expected):
    assert route(question) == expected


def test_every_guide_topic_has_an_answer():
    for q in ["how do i give a customer discount?", "how do i record expenses?",
              "how do i report fake product?", "how do i pay my supplier?"]:
        topic = parse_message(q)["topic"]
        assert "not sure which feature" not in build_app_guide_message(topic)


def test_where_is_answers_with_the_menu_path():
    text = get_faq_answer("where:/expenses")
    assert "Menu → More → Expenses" in text
    assert "Menu → Select product" in get_faq_answer("where:/pos")
