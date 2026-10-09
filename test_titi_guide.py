"""
tiTi must know every screen in the menu and every feature people ask about.

The first test reads the real menu (Layout.jsx): a new screen added there
without an entry in nav_guide fails here, so tiTi can't be left not knowing
where it is.
"""
import re
from pathlib import Path

import faq
import llm_fallback
from nav_guide import NAV_GUIDE

LAYOUT = Path(__file__).parent / "frontend" / "src" / "components" / "Layout.jsx"


def _menu_routes():
    text = LAYOUT.read_text(encoding="utf-8")
    return set(re.findall(r'\{\s*to:\s*"(/[a-z-]*)"', text))


def test_every_menu_item_is_in_the_guide():
    routes = _menu_routes()
    assert len(routes) > 20                       # the parser found the menu
    missing = routes - set(NAV_GUIDE)
    assert not missing, f"Menu items tiTi doesn't know about — add them to nav_guide.py: {sorted(missing)}"


def test_the_guide_reaches_titi():
    prompt = llm_fallback._SYSTEM_PROMPT
    assert "{NAV_GUIDE}" not in prompt
    assert "WHERE TO FIND THINGS" in prompt
    for entry in NAV_GUIDE.values():
        assert entry["name"] in prompt


def test_payment_and_plans_are_described_correctly():
    prompt = llm_fallback._SYSTEM_PROMPT
    assert "PREMIUM" in prompt and "card" in prompt.lower()
    assert "Payment is via bank transfer and confirmed by admin" not in prompt
    upgrade = faq.get_faq_answer("upgrade")
    assert "card" in upgrade and "PREMIUM" in upgrade
    assert "PRO: GO + staff accounts" in upgrade        # staff is a Pro feature


QUESTIONS = {
    "how do i give a discount?": "discount",
    "can I put discount on receipt?": "discount",
    "how can i scan barcode with my phone?": "barcode_scan",
    "how do I use the camera to scan?": "barcode_scan",
    "where do i add barcode to my product?": "barcode_scan",
    "how do i write a review?": "site_review",
    "how can i get a free advert?": "site_review",
    "how do i become a verified supplier?": "supplier_directory",
    "how do I find a supplier?": "supplier_directory",
    "what is my business score?": "finance_scorecard",
    "how do I get financing for a motorcycle?": "finance_scorecard",
    "how do i record a repayment?": "finance_scorecard",
    # Older topics still land where they did.
    "how do I print a receipt?": "receipt",
    "who owes me?": "overdue_debtors",
    "how do i send invoice?": "invoices",
}


def test_questions_reach_the_right_answer():
    wrong = {q: (faq.detect_faq(q), want) for q, want in QUESTIONS.items() if faq.detect_faq(q) != want}
    assert not wrong, wrong


def test_each_new_answer_says_where_to_tap():
    for key, needle in {
        "discount": "Discount",
        "barcode_scan": "📷 Scan",
        "site_review": "My Profile",
        "supplier_directory": "Suppliers",
        "finance_scorecard": "Business Score",
    }.items():
        assert needle in faq.get_faq_answer(key), key
