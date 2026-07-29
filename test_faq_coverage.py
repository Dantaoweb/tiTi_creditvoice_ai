"""
tiTi should answer varied phrasings of questions about the app's functions —
not only rigid keyword forms. And it must NOT mistake a transaction for a
question.
"""
from faq import detect_faq
from parser import parse_message


def _answered(t):
    if detect_faq(t):
        return True
    p = parse_message(t) or {}
    return p.get("type") in ("APP_GUIDE", "WHAT_CAN_DO", "CONVO_PRODUCT_PROFIT")


ANSWERABLE = [
    "tell me about invoices",
    "do you support multiple shops",
    "do you allow multiple users",
    "how do i change my business name",
    "how do i add my shop address",
    "is it possible to export my data",
    "is there a way to void a sale",
    "what does void mean",
    "can i give my staff access",
    "can i add another worker",
    "can i add more shops",
    "how can i download my receipt",
    "whats the process to record a payment",
    "i want to know my best selling product",
    "explain how branches work",
    "do you have staff accounts",
]

# Real transactions/commands must never be treated as help questions
NOT_QUESTIONS = [
    "Ada bought rice 5000",
    "Tunde paid 3000",
    "i sold egg 3 crates to Ayo for 15000",
    "add stock rice 50 bags cost 3000 sell 4000",
    "Ade paid 2000",
]


def test_varied_questions_are_answered():
    missed = [t for t in ANSWERABLE if not _answered(t)]
    assert not missed, f"unanswered: {missed}"


def test_transactions_are_not_treated_as_faq():
    wrong = [t for t in NOT_QUESTIONS if detect_faq(t)]
    assert not wrong, f"transactions misrouted to FAQ: {wrong}"
