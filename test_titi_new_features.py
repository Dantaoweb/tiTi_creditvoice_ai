"""
tiTi explains every recent feature, asked the way people ask — through the
same path the chat uses (the parser's app guide first, then the FAQ). A
question about a feature must never be recorded as a sale or a job.
"""
import pytest

from faq import FAQ_ANSWERS, detect_faq
from parser import parse_message

ASKED = [
    ("how do i hold a sale?", "hold_sale"),
    ("my customer is not ready, what do i do?", "hold_sale"),
    ("can i save a sale as draft?", "hold_sale"),
    ("what does completed mean on my invoice?", "invoices"),
    ("how do i track a quotation?", "quotation"),
    ("how do i get a business page?", "business_page"),
    ("can i have my own website?", "business_page"),
    ("how do i add a recipe?", "production"),
    ("i bake bread, how do i record it?", "production"),
    ("how do i know the cost to make one loaf?", "production"),
    ("how do i see wastage?", "production"),
    ("how do i record rejects?", "production"),
    ("how do i record my distributors?", "distributors"),
    ("sales rep brought back unsold bread, what do i do?", "distributors"),
    ("how do i remove damaged stock?", "remove_stock"),
    ("my product has no barcode, how do i make one?", "make_barcode"),
    ("how do i change the phone number on my receipt?", "receipt_phone"),
]


def _topic(text):
    p = parse_message(text)
    if p and p.get("type") == "APP_GUIDE":
        return p["topic"]
    assert not (p and p.get("type") in ("TRANSACTION", "SERVICE_JOB")), f"{text!r} was recorded as {p}"
    return detect_faq(text)


@pytest.mark.parametrize("text,topic", ASKED)
def test_titi_answers(text, topic):
    assert _topic(text) == topic
    assert topic in FAQ_ANSWERS


def test_real_jobs_and_sales_still_record():
    assert parse_message("Bayo brought 3 shirts")["type"] == "SERVICE_JOB"
    assert parse_message("John brought 10 shirts, 5 trousers paid 2000")["type"] == "SERVICE_JOB"
    assert parse_message("Ade bought rice 5000")["type"] == "TRANSACTION"


def test_receipt_phone_answer_points_to_profile_and_branches():
    a = FAQ_ANSWERS["receipt_phone"]
    assert "My Profile" in a and "Phone on receipts" in a and "Branches" in a
