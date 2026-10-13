"""
tiTi explains part delivery, cancel / refund and returns, the way people ask.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from faq import detect_faq, get_faq_answer
from messages import build_app_guide_message
from parser import parse_message


def _topic(text):
    p = parse_message(text) or {}
    if p.get("type") == "APP_GUIDE":
        return p["topic"]
    return detect_faq(text)


@pytest.mark.parametrize("text,topic", [
    ("how do I record goods that were partly delivered?", "part_delivery"),
    ("customer bought 100 bags but only 60 delivered, how do I record it", "part_delivery"),
    ("how do I deliver the rest later", "part_delivery"),
    ("what is reserved stock?", "part_delivery"),
    ("part delivery", "part_delivery"),
    ("how do I refund the undelivered goods", "cancel_refund"),
    ("customer no longer want the remaining bags, how do i cancel the rest?", "cancel_refund"),
    ("what is a credit note", "cancel_refund"),
    ("refund", "cancel_refund"),
    ("how do I take back returned goods", "return_goods"),
    ("a customer returned 5 bags that were damaged, what do I do?", "return_goods"),
    ("return goods", "return_goods"),
])
def test_tit_knows_which_answer(text, topic):
    assert _topic(text) == topic


def test_the_answers_say_where_and_how():
    part = build_app_guide_message("part_delivery")
    assert "Not all goods delivered now" in part and "Deliver" in part and "Reserved" in part
    refund = build_app_guide_message("cancel_refund")
    assert "Cancel / refund" in refund and "credit note" in refund and "available to sell again" in refund
    assert "owner or authorised staff" in refund
    ret = get_faq_answer("return_goods")
    assert "Return goods" in ret and "damaged" in ret and "back into stock" in ret
