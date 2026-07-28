"""
tiTi must answer void/remove/correct help questions (via APP_GUIDE or FAQ),
in whatever phrasing — and must NOT confuse the actual void command, nor
false-match "avoid".
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from parser import parse_message
from faq import detect_faq
from messages import build_app_guide_message


def _answers_void(text):
    p = parse_message(text)
    if p and p.get("type") == "APP_GUIDE" and p.get("topic") == "void":
        return True
    return detect_faq(text) == "void_transaction"


def test_void_help_questions_in_many_phrasings():
    for t in [
        "how do i void a transaction",
        "how to void",
        "how to remove a transaction",
        "how do i remove a transaction",
        "how do i delete a sale",
        "how to delete a transaction",
        "how do i correct a wrong transaction",
        "how do i cancel a payment",
        "how to undo a transaction",
        "how do i reverse a sale",
        "i made a mistake on a sale how do i fix it",
    ]:
        assert _answers_void(t), f"not answered: {t!r}"


def test_app_guide_void_answer_is_meaningful():
    ans = build_app_guide_message("void").lower()
    assert "void" in ans and "transaction" in ans and "reason" in ans


def test_real_void_command_still_parses_as_command():
    p = parse_message("void 42 wrong amount")
    assert p and p.get("type") == "VOID_TRANSACTION"


def test_avoid_is_not_treated_as_void():
    p = parse_message("how do i avoid running out of stock")
    topic = p.get("topic") if p else None
    assert topic != "void"
    assert detect_faq("how do i avoid running out of stock") != "void_transaction"
