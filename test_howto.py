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
    # round 2 — staff
    ("how do i add staff", "staff_invite"),
    ("how do i add my sales girl", "staff_invite"),
    ("i want to add a worker", "staff_invite"),
    ("how can i give my cashier access to the app", "staff_invite"),
    ("how do i invite my stafs", "staff_invite"),
    ("how do i give my staff admin", "staff_make_admin"),
    ("how do i make my manager see everything", "staff_make_admin"),
    ("i want my staff to run the shop when i travel", "staff_make_admin"),
    ("how do i stop staff from seeing profit", "staff_limits"),
    ("how do i hide cost price from staff", "staff_limits"),
    ("i don't want my admin to see expenses", "staff_limits"),
    ("can my staff see my customers", "staff_customers"),
    ("how do i let my staff serve my customers", "staff_customers"),
    ("my sales girl can't see customers", "staff_customers"),
    ("how do i remove a staff", "staff_remove"),
    ("my worker has left how do i remove him", "staff_remove"),
    ("how do i sack my staff from the app", "staff_remove"),
    ("my staff lost his phone what do i do", "staff_sign_out"),
    ("how do i log out my staff", "staff_sign_out"),
    ("how do i move staff to another branch", "staff_branch"),
    ("how do i see which staff sold the most", "staff_performance"),
    ("how do i check my staff performance", "staff_performance"),
    ("how do i set my staff salary", "staff_profile"),
    ("my staff forgot his pin", "staff_pin"),
    ("what can my staff see", "staff_what_they_see"),
    ("what is the difference between staff and admin", "staff_what_they_see"),
    ("the staff code has expired", "staff_code_expired"),
    ("my staff did not get the code", "staff_code_expired"),
    ("how do i cancel a staff invitation", "staff_cancel_invite"),
    ("my boss invited me how do i join", "staff_accept"),
    ("i have the code how do i accept the invite", "staff_accept"),
    ("it says the number already has an account when i invite staff", "staff_number_taken"),
    ("how do i add a partner", "partner"),
    ("how do i record salary as expense", "expenses"),
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


def test_staff_answers_use_the_staff_page_words():
    import pathlib
    page = pathlib.Path(__file__).with_name("frontend").joinpath("src", "pages", "Staff.jsx").read_text(encoding="utf-8")
    for label in ("Invite a staff member", "Send Invitation", "Send on WhatsApp", "Copy link", "Join as admin",
                  "Make admin", "Make ordinary staff", "This admin can't see", "Can see the business's customers",
                  "Sign out their phone", "Remove from business", "Resend invite", "Pending Invitations",
                  "HR Profiles", "Staff Leaderboard", "Monthly Salary"):
        assert label in page, label
    login = pathlib.Path(__file__).with_name("frontend").joinpath("src", "pages", "Login.jsx").read_text(encoding="utf-8")
    for label in ("Accept a staff invitation", "Accept Code", "Create your PIN", "Your Phone Number"):
        assert label in login, label


def test_answers_point_at_the_real_settings_card():
    # the Settings card names in the answers are the ones on the page
    import pathlib
    page = pathlib.Path(__file__).with_name("frontend").joinpath("src", "pages", "Settings.jsx").read_text(encoding="utf-8")
    for card in ("Receipts & printables", "Bank details on invoices & quotations", "Bank details on receipts",
                 "Paper size", "Receipt title", "Closing line", "TIN / VAT number", "My prices", "VAT collected"):
        assert card in page, card
