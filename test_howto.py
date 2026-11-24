"""
tiTi answers the exact task asked ("bank details on my quotation"), not the
whole feature's guide — and never takes a command for a question.
Round 1: selling & paperwork (receipts, invoices, quotations, VAT, bank, printing).
"""
import pytest

from faq import detect_faq, get_faq_answer
from howto import HOWTO, fix_typos, howto_answer, howto_facts
from parser import parse_message


def _answer_key(text):
    """The key tiTi answers with: the parser first, then the FAQ (as the
    message flow does when the parser finds nothing)."""
    p = parse_message(text) or {}
    if p.get("type") == "APP_GUIDE":
        key = p["topic"]
    elif p:
        return p.get("type")
    else:
        key = detect_faq(text)
    return key[len("howto:"):] if key and key.startswith("howto:") else key


CASES = [
    ("how do i add bank details to my qoutation", "bank_on_invoice"),
    ("how do i add bank details to my quotation", "bank_on_invoice"),
    ("how do i add my account number to invoice", "bank_on_invoice"),
    ("i want my acount details on my invoice", "bank_on_invoice"),
    ("how do i show my account number on invoice?", "bank_on_invoice"),
    ("remove bank details from my quotation", "bank_on_invoice"),
    ("how do i put my bank account on receipt", "bank_on_receipt"),
    ("where do i add bank details", "bank_add"),
    ("how do i change my bank account", "bank_add"),
    ("how do i change paper size for my receipt", "paper_size"),
    ("how do i print on A4", "paper_size"),
    ("my receipt printer is 58mm how do i set it", "paper_size"),
    ("how do i change my receipt title", "receipt_title"),
    ("how do i change the word at the top of my reciept", "receipt_title"),
    ("how do i change the closing line on my receipt", "closing_line"),
    ("how do i write goods sold are not returnable on receipt", "closing_line"),
    ("how do i add email to my invoice", "email_on_docs"),
    ("how do i add email address to my invoice", "email_on_docs"),
    ("how do i remove address from receipt", "address_on_docs"),
    ("how do i hide my phone number on receipt", "phone_show_hide"),
    ("how do i move my logo to the left on receipt", "logo_position"),
    ("how do i add my logo to receipt", "logo"),
    ("how do i change the logo on my invoice", "logo"),
    ("how do i make my receipt like a letterhead", "details_align"),
    ("how do i print a receipt", "print_how"),
    ("how do i download invoice as pdf", "print_how"),
    ("how do i void a receipt", "void_receipt"),
    ("i made a mistake on a receipt how do i cancel it", "void_receipt"),
    ("how do i send receipt to customer on whatsapp", "resend_receipt"),
    ("how do i edit an invoice", "edit_invoice"),
    ("how do i change the price on my quotation", "edit_invoice"),
    ("how do i cancel an invoice", "cancel_invoice"),
    ("customer paid half of the invoice how do i record it", "invoice_payment"),
    ("how do i mark invoice delivered", "invoice_delivered"),
    ("how do i send invoice to customer", "invoice_send"),
    ("how do i make invoice repeat every month", "repeat_invoice"),
    ("how do i bill my tenant every month", "repeat_invoice"),
    ("how do i turn off quotations", "quote_show_hide"),
    ("i can't see quotation on invoices page", "quote_show_hide"),
    ("how do i track my quotation status", "quote_status"),
    ("how do i track a quotation?", "quote_status"),
    ("how to send the same invoice every week", "repeat_invoice"),
    ("how do i change a quotation status", "quote_status"),
    ("how do i add deposit to quotation", "quote_deposit"),
    ("customer agreed to my quote what do i do", "quote_to_invoice"),
    ("how do i add my tin to receipt", "vat_number"),
    ("my prices already include vat how do i set it", "vat_inclusive"),
    ("some products have no vat how do i do it", "vat_exempt"),
    ("how much vat did i collect this month", "vat_report"),
    # broad questions still get the feature's full guide
    ("how do i add vat to my invoice", "vat"),
    ("how do i make a quotation", "quotation"),
    ("how do i create an invoice", "invoices"),
]


@pytest.mark.parametrize("text,key", CASES)
def test_exact_answer(text, key):
    assert _answer_key(text) == key


@pytest.mark.parametrize("text", [
    "Ade bought 2 bags rice 50000",
    "receipt Ada",
    "Ade paid 5000",
])
def test_commands_are_not_questions(text):
    p = parse_message(text) or {}
    assert p.get("type") != "APP_GUIDE"


def test_data_questions_left_to_commands():
    # "how much did Ade pay" is about the business's figures, not a how-to
    from howto import exact_for
    assert exact_for("how much did Ade pay on the invoice") is None


def test_typos_fixed():
    assert "quotation" in fix_typos("my qoutation")
    assert "receipt" in fix_typos("my reciept")
    assert "invoice" in fix_typos("the invioce")
    assert "recipe" in fix_typos("my recipe")          # not a receipt


def test_every_answer_is_short_and_reachable():
    for key, entry in HOWTO.items():
        text = howto_answer(key)
        assert text, key
        if entry[1] is not None:
            assert len(text) < 700, key
        assert get_faq_answer(f"howto:{key}")


def test_ai_is_given_the_exact_steps():
    import llm_fallback
    assert "Bank details on invoices & quotations" in llm_fallback._SYSTEM_PROMPT
    assert "EXACT STEPS" in llm_fallback._SYSTEM_PROMPT
    assert howto_facts().count("\n") >= 20


def test_answers_point_at_the_real_settings_card():
    # the Settings card names in the answers are the ones on the page
    import pathlib
    page = pathlib.Path(__file__).with_name("frontend").joinpath("src", "pages", "Settings.jsx").read_text(encoding="utf-8")
    for card in ("Receipts & printables", "Bank details on invoices & quotations", "Bank details on receipts",
                 "Paper size", "Receipt title", "Closing line", "TIN / VAT number", "My prices", "VAT collected"):
        assert card in page, card
