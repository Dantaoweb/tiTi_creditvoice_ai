"""
tiTi answers how-to questions in the words of the business's own menu —
"Select product", "Select service", "Sell textbooks" — never "POS", and part
payment gets a real answer instead of the list of message formats.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from faq import FAQ_ANSWERS, detect_faq, get_faq_answer
from messages import build_app_guide_message
from models import User
from parser import parse_message


def _topic(text):
    p = parse_message(text) or {}
    if p.get("type") == "APP_GUIDE":
        return p["topic"]
    return detect_faq(text)


@pytest.mark.parametrize("text,topic", [
    ("how do I record part payment", "record_payment"),
    ("how to record partial payment", "record_payment"),
    ("how do I record when customer paid part of the money?", "record_payment"),
    ("what if he will pay the rest later?", "record_payment"),
    ("how do I sell", "record_sale"),
    ("how do I sell a service", "record_sale"),
    ("how do i use pos", "pos"),
])
def test_how_to_questions_get_an_answer(text, topic):
    assert _topic(text) == topic


def test_a_payment_is_still_a_payment():
    assert (parse_message("Ade paid 5000") or {}).get("type") == "TRANSACTION"


def test_part_payment_answer_covers_the_three_ways():
    a = build_app_guide_message("record_payment")
    assert "Payment Received" in a and "Save Sale" in a and "*Pay*" in a and "Ade paid 5000" in a


@pytest.mark.parametrize("business_type,category,till", [
    ("pharmacy", "retail_trade", "Select product"),
    ("barber", "beauty_personal_care", "Select service"),
    ("private_school", "education", "Sell textbooks"),
])
def test_answers_name_the_menu_item_the_business_sees(business_type, category, till):
    user = User(phone="1", business_type=business_type, business_category=category)
    for topic in ("record_sale", "pos", "record_payment", "part_delivery"):
        text = build_app_guide_message(topic, user)
        assert f"*{till}*" in text, topic
        assert "POS" not in text and "{till}" not in text and "{record}" not in text, topic


def test_no_answer_says_pos():
    for key in FAQ_ANSWERS:
        assert "POS" not in get_faq_answer(key), key


@pytest.mark.parametrize("text", [
    "tell me what you can", "tell me what you can do", "what can i use you for", "how can i use you",
    "how to use you", "what are you for", "how can you help me", "what can i use titi for",
])
def test_what_can_you_do_in_many_words(text):
    assert (parse_message(text) or {}).get("type") == "WHAT_CAN_DO"


def test_the_intro_works_on_web_and_lists_newer_features():
    from messages import build_what_can_do_message
    intro = build_what_can_do_message(User(phone="1", business_type="pharmacy", business_category="health"))
    assert "Type to me here or on WhatsApp" in intro
    assert "Waybills" in intro and "Pay links" in intro and "Stock count & expiry" in intro


@pytest.mark.parametrize("text", [
    "how to sell when stock is saying stock out", "can i sell when the product is out of stock?",
    "how do I sell when stock is finished",
])
def test_selling_out_of_stock_gets_its_own_answer(text):
    assert _topic(text) == "sell_out_of_stock"
    a = build_app_guide_message("sell_out_of_stock", User(phone="1", business_type="pharmacy", business_category="health"))
    assert "*Select product*" in a and "still to deliver" in a and "walk-in" in a and "{till}" not in a
