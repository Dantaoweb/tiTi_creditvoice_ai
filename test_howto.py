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
    # round 3 — stock & categories
    ("how do i add more stock to rice", "stock_add_more"),
    ("new goods arrived how do i add them", "stock_add_more"),
    ("my supplier brought 20 cartons how do i add it", "stock_add_more"),
    ("how do i restock", "stock_add_more"),
    ("how do i add many products at once", "many_products"),
    ("how do i add all my drugs fast", "many_products"),
    ("how do i set low stock alert", "low_stock_alert"),
    ("how do i get notified when stock is running low", "low_stock_alert"),
    ("how do i set expiry warning days", "expiry_warn"),
    ("can tiTi warn me before my drugs expire", "expiry_warn"),
    ("how do i add expiry date to my drugs", "expiry_add_date"),
    ("how do i see expired goods", "expiry_list"),
    ("which products are expiring", "expiry_list"),
    ("how do i hide the numbers during stock count", "count_blind"),
    ("how do i approve stock count", "count_approve"),
    ("i entered the same product twice", "duplicates"),
    ("how do i find duplicate products", "duplicates"),
    ("how do i change the price of rice", "price_change"),
    ("how do i update my selling price", "price_change"),
    ("how do i set wholesale price", "wholesale_price"),
    ("how do i give cheaper price for bulk buyer", "wholesale_price"),
    ("how do i sell sachets from a pack", "sub_unit"),
    ("how do i sell tablets from a pack of drugs", "sub_unit"),
    ("how do i change cost price", "cost_price"),
    ("how do i rename a product", "product_rename"),
    ("i spelt my product name wrong", "product_rename"),
    ("how do i see stock history of a product", "stock_history"),
    ("who removed stock from my inventory", "stock_history"),
    ("how do i see damaged goods report", "removed_stock_report"),
    ("how do i keep goods aside for customers", "keep_aside"),
    ("customer has not collected his goods what do i do", "keep_aside"),
    ("how do i hide the part delivery option", "part_delivery_switch"),
    ("how do i create categories", "category_create"),
    ("how do i move products to a category", "category_move"),
    ("how do i put rice under provisions category", "category_move"),
    ("how do i rename a category", "category_rename"),
    ("how do i delete a category", "category_rename"),
    ("how do i show my stock by category", "category_group_view"),
    ("how do i group products by category at the till", "category_group_view"),
    ("how do i stop staff from creating categories", "category_only_list"),
    ("can titi suggest categories for me", "category_suggest"),
    ("how do i arrange my categories", "category_order"),
    ("how do i remove damaged stock", "remove_stock"),
    ("how do i do stock count", "stock_count"),
    ("how do i sell when stock is finished", "sell_out_of_stock"),
    ("how do i change the price on my quotation", "edit_invoice"),
    ("how do i hide cost price from staff", "staff_limits"),
    ("how do i make my own barcode", "make_barcode"),
    ("how do i order stock from my supplier", "purchase_order"),
    ("some products have no vat how do i do it", "vat_exempt"),
    # broad questions still get the feature's full guide
    ("how do i add vat to my invoice", "vat"),
    ("how do i make a quotation", "quotation"),
    ("how do i create an invoice", "invoices"),
    # Round 4: customers
    ("how do I book an appointment?", "appointment_book"),
    ("how can I book customers for a time", "appointment_book"),
    ("how can customers book online with a booking link", "booking_link"),
    ("how do I confirm payment", "payment_claim_confirm"),
    ("how to reward loyal customers", "loyalty"),
    ("how do i send reminder to customers?", "reminder"),
    ('how do i add a new customer', 'customer_add'),
    ('how do i add costumer', 'customer_add'),
    ('how can i register a client', 'customer_add'),
    ('how do i change customer name', 'customer_edit'),
    ('how do i edit my customer phone number', 'customer_edit'),
    ('customer name is spelt wrong how do i fix it', 'customer_edit'),
    ('how do i delete a customer', 'customer_delete'),
    ('how to remove customer', 'customer_delete'),
    ('same customer is showing two times', 'customer_duplicate'),
    ('how do i merge two customers', 'customer_duplicate'),
    ('customer appears twice what do i do', 'customer_duplicate'),
    ('how do i send customer their balance', 'customer_send_balance'),
    ('how can i tell my customer how much he owes', 'customer_send_balance'),
    ('how do i change due date', 'due_date_change'),
    ('how do i extend the due date for a debt', 'due_date_change'),
    ('where can i see my debtors', 'debtors_list'),
    ('how do i see people owing me', 'debtors_list'),
    ('how do i see all overdue customers', 'debtors_list'),
    ('how do i turn on reminders', 'reminder_mode'),
    ('how do i stop debt reminders', 'reminder_mode'),
    ('how do i make reminders automatic', 'reminder_mode'),
    ('how do i see my best customers', 'best_customers'),
    ('who are my top customers?', 'best_customers'),
    ('how do i set up loyalty', 'loyalty_setup'),
    ('how do i start stamp card', 'loyalty_setup'),
    ('how do i turn off loyalty points', 'loyalty_setup'),
    ('how does a customer use their points', 'loyalty_use'),
    ('how do i redeem a customers reward', 'loyalty_use'),
    ('how do i book an appointment', 'appointment_book'),
    ('how do i make a new appoinment', 'appointment_book'),
    ('how can customers book by themselves', 'booking_link'),
    ('how do i get my booking link', 'booking_link'),
    ('how do i mark appointment done', 'appointment_status'),
    ('customer did not come for appointment how do i mark it', 'appointment_status'),
    ('how do i copy pay link', 'pay_link_copy'),
    ('where is the pay link for invoice', 'pay_link_copy'),
    ('customer said they paid how do i confirm', 'payment_claim_confirm'),
    ('how do i confirm a transfer', 'payment_claim_confirm'),
    ('how do i see customers waiting for goods', 'waiting_for_goods'),
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


def test_stock_answers_use_the_inventory_words():
    import pathlib
    src = pathlib.Path(__file__).with_name("frontend").joinpath("src")
    inv = src.joinpath("pages", "Inventory.jsx").read_text(encoding="utf-8")
    for label in ("Adjust stock", "Add Stock", "Remove Stock", "Confirm removal", "Edit details", "Save Changes",
                  "Low-stock alert", "Wholesale price (₦)", "From qty (buy ≥)", "Retail Breakdown", "Sub-unit name",
                  "Sub-unit price (₦)", "Cost price (₦)", "Cost per unit", "Expiry date", "Batch no.", "Quick Add",
                  "Catalog", "Check duplicates", "Removed stock", "Expiry", "Count stock", "Stock movements",
                  "Price changes", "Remove product", "No VAT on this", "Kept aside for customers"):
        assert label in inv, label
    counts = src.joinpath("pages", "StockCount.jsx").read_text(encoding="utf-8") + \
        src.joinpath("pages", "StockCounts.jsx").read_text(encoding="utf-8")
    assert "Write off expired" in src.joinpath("components", "ExpiryModal.jsx").read_text(encoding="utf-8")
    for label in ("Start a count", "Send for approval", "Approve — fix my stock", "Waiting for approval"):
        assert label in counts, label
    settings = src.joinpath("pages", "Settings.jsx").read_text(encoding="utf-8")
    for label in ("Low-stock alert for new products", "Warn me before goods expire", "Group stock by category",
                  "Where grouping shows", "New categories come from", "Only categories from my list",
                  "Let tiTi suggest categories", "Put products into a category", "Keep goods aside for customers",
                  "hide the app's numbers while counting"):
        assert label in settings, label


def test_answers_point_at_the_real_settings_card():
    # the Settings card names in the answers are the ones on the page
    import pathlib
    page = pathlib.Path(__file__).with_name("frontend").joinpath("src", "pages", "Settings.jsx").read_text(encoding="utf-8")
    for card in ("Receipts & printables", "Bank details on invoices & quotations", "Bank details on receipts",
                 "Paper size", "Receipt title", "Closing line", "TIN / VAT number", "My prices", "VAT collected"):
        assert card in page, card


def test_customer_answers_use_the_page_words():
    import pathlib
    src = pathlib.Path(__file__).with_name("frontend").joinpath("src")
    cust = src.joinpath("pages", "Customers.jsx").read_text(encoding="utf-8")
    for label in ("Duplicates", "Merge into the ticked one", "Record payment", "Record Payment", "Send balance",
                  "Payment amount", "Edit due date", "Due Date", "Transaction history", "Reminder mode:", "Review",
                  "Automatic", "Generate Reminders", "Send Reminders", "Total Outstanding", "Next Due",
                  "Days Overdue", "To deliver", "Waybill", "Best", "Last ", "Edit"):
        assert label in cust, label
    assert "Add Customer" in src.joinpath("lib", "bizLabels.js").read_text(encoding="utf-8")
    appt = src.joinpath("pages", "Appointments.jsx").read_text(encoding="utf-8")
    for label in ("Book", "Booking link", "Send on WhatsApp", "Arrived", "Done", "No-show", "Confirm", "Decline",
                  "What was done", "Paid now", "Record sale"):
        assert label in appt, label
    settings = src.joinpath("pages", "Settings.jsx").read_text(encoding="utf-8")
    for label in ("Loyalty", "Reward customers who come back", "Stamp card", "Points", "Stamps for a free one",
                  "Points for every ₦100 spent", "Rewards expire", "Products that count", "Appointments",
                  "Show Appointments in the menu", "Customers can book from a link", "When a customer books from the link",
                  "Opening hours", "Save hours"):
        assert label in settings, label
    pos = src.joinpath("pages", "POS.jsx").read_text(encoding="utf-8")
    assert "Use reward" in pos and "Use points" in pos
    claims = src.joinpath("pages", "PaymentClaims.jsx").read_text(encoding="utf-8")
    for label in ("Payments to confirm", "Confirm — money is in", "Not received", "Amount that arrived"):
        assert label in claims, label
    assert "Copy pay link" in src.joinpath("pages", "InvoiceView.jsx").read_text(encoding="utf-8")
