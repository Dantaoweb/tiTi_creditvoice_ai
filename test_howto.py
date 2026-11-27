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
    # Round 5a: production & distributors
    ('how do i add a recipe?', 'recipe_add'),
    ('how do i set the recipe for bread', 'recipe_add'),
    ('how do i change my recipe', 'recipe_add'),
    ('how do i delete a recipe', 'recipe_delete'),
    ('how do i record production', 'production_record'),
    ('how do i record what we made today', 'production_record'),
    ("how do i enter today's batch", 'production_record'),
    ('how do i record rejects', 'production_rejects'),
    ('some bread got burnt during baking how do i record it', 'production_rejects'),
    ('how do i record regrind', 'production_rejects'),
    ('how do i know the cost to make one loaf', 'production_cost'),
    ('what does it cost to make my product', 'production_cost'),
    ('how do i know my production cost', 'production_cost'),
    ('i recorded production wrong how do i undo it', 'production_undo'),
    ('how do i delete a batch', 'production_undo'),
    ('how do i see production report', 'production_report'),
    ('how do i check waste in production', 'production_report'),
    ('how do i know if material is missing', 'production_report'),
    ('how do i send goods out with a seller', 'seller_send_out'),
    ('my sales rep is taking bread out how do i record it', 'seller_send_out'),
    ('how do i give goods to distributor', 'seller_send_out'),
    ('sales rep brought back unsold bread, what do i do?', 'seller_settle'),
    ('how do i settle a seller', 'seller_settle'),
    ('distributor came back how do i record', 'seller_settle'),
    ('my van seller paid part, how do i record it', 'seller_settle'),
    ('how do i see what my seller owes', 'seller_owes'),
    ('which distributor owes me', 'seller_owes'),
    ('how do i set my distributor price', 'seller_price'),
    ('how do i give my seller commission', 'seller_price'),
    ("i can't find production in the menu", 'production_menu'),
    ('where is production', 'production_menu'),
    # Branches
    ("how do i move stock to another branch", "branch_transfer"),
    ("how can i transfer goods from ikeja branch to lekki branch?", "branch_transfer"),
    ("how do i send 20 bags to my other branch", "branch_transfer"),
    # Round 5b: money
    ('how do i record an expense', 'expenses'),
    ('where do i add my expenses', 'expenses'),
    ('how do i record money i spent on fuel', 'expenses'),
    ('i entered wrong expense how do i change it', 'expense_edit'),
    ('how do i delete an expense', 'expense_edit'),
    ('how do i approve expense my staff sent', 'expenses'),
    ('where do i see expenses waiting for review', 'expenses'),
    ('how do i see my total expenses this month', 'expense_total'),
    ('where can i see what i spent', 'expense_total'),
    ('how do i add a supplier', 'supplier_add'),
    ('how do i add new supplier', 'supplier_add'),
    ('how do i record goods i bought from supplier', 'supplier_purchase'),
    ('i bought goods on credit from my supplier how do i record it', 'supplier_purchase'),
    ('how do i pay my supplier', 'supplier_owed'),
    ('i paid my supplier how do i record it', 'supplier_owed'),
    ('where do i see what i owe suppliers', 'supplier_owed'),
    ('how do i check my supplier balance', 'supplier_owed'),
    ('how do i download my records', 'export_csv'),
    ('can i export my transactions to excel', 'export_csv'),
    ('how do i download my customer list', 'export_csv'),
    ('how do i get my loan statement', 'loan_statement'),
    ('how do i download bank statement pdf', 'loan_statement'),
    ('how do i get bought vs sold report', 'bought_vs_sold'),
    ('how do i see my profit', 'profit_see'),
    ('where can i see profit for each product', 'profit_see'),
    ('my profit is showing zero', 'profit_wrong'),
    ('why is my profit wrong', 'profit_wrong'),
    ('how do i see sales for each branch', 'branch_sales'),
    ('how do i compare my branches', 'branch_sales'),
    # Round 5c: business set-up
    ('how do i change my business name', 'change_name'),
    ('my shop name is wrong on receipt how do i correct it', 'change_name'),
    ('how do i change my business address', 'change_name'),
    ('how do i change my business type', 'change_name'),
    ('how do i add my logo', 'logo'),
    ('how do i upload my logo', 'logo'),
    ('how do i change my pin', 'pin_help'),
    ('i forgot my pin', 'pin_help'),
    ('how do i reset my pin', 'pin_help'),
    ('i lost my phone number how do i get my account back', 'account_recovery'),
    ('i changed my number what do i do', 'account_recovery'),
    ('where do i enter my plan code', 'redeem_code'),
    ('i have a token code how do i use it', 'redeem_code'),
    ('how do i upgrade', 'upgrade_pay'),
    ('how do i pay for go plan', 'upgrade_pay'),
    ('how do i renew my subscription', 'upgrade_pay'),
    ('how can i pay for premium', 'upgrade_pay'),
    ('which plan am i on', 'plan_current'),
    ('when does my plan expire', 'plan_current'),
    ('how do i downgrade my plan', 'plan_downgrade'),
    ('how do i cancel my subscription', 'plan_downgrade'),
    ('do you have a plan for big companies', 'enterprise'),
    ('how do i get enterprise', 'enterprise'),
    ('how do i get a business page', 'business_page'),
    ('how do i turn on my business page', 'business_page'),
    ('how do i put products on my business page', 'page_products'),
    ('how do i hide prices on my page', 'page_products'),
    ('where do i see quotation requests from my page', 'page_requests'),
    ('how do i share my business page link', 'page_link'),
    ('where is my page link', 'page_link'),
    # Round 5d: business types
    ("i can't find school fees in the menu", 'vertical_menu'),
    ('egg and feed is not showing in my menu', 'vertical_menu'),
    ('how do i set up my school year', 'school_setup'),
    ('how do i add a class', 'school_setup'),
    ('how do i set fees for each class', 'school_setup'),
    ('how do i start a new term', 'school_setup'),
    ('how do i charge this term fees', 'school_charge_term'),
    ('how do i register a new pupil', 'school_pupil_add'),
    ('how do i add a student', 'school_pupil_add'),
    ('how do i record school fees payment', 'school_payment'),
    ('a parent paid part of the fees how do i record it', 'school_payment'),
    ('how do i give a pupil scholarship', 'school_arrangement'),
    ('staff child pays nothing how do i set it', 'school_arrangement'),
    ('how do i charge a pupil for books', 'school_books'),
    ('how do i add uniform for a student', 'school_books'),
    ('how do i see pupils owing', 'school_owing'),
    ('how do i record eggs collected today', 'egg_collection'),
    ('how do i enter crates of eggs', 'egg_collection'),
    ('how do i record feed used today', 'feed_usage'),
    ('how do i log layer mash usage', 'feed_usage'),
    ('how do i see egg report', 'egg_report'),
    ('how do i see margin over feed', 'egg_report'),
    ('how do i add a pump', 'fuel_setup'),
    ('how do i set fuel price per litre', 'fuel_setup'),
    ('how do i add a tank', 'fuel_setup'),
    ('how do i open a shift', 'fuel_shift'),
    ('how do i close shift and reconcile', 'fuel_shift'),
    ('how do i record tanker delivery', 'fuel_delivery'),
    ('how do i record a tank dip', 'fuel_dip'),
    ('how do i start an ajo group', 'thrift_group_create'),
    ('how do i create a thrift group', 'thrift_group_create'),
    ('how do i invite people to my ajo group', 'thrift_invite'),
    ('how do i approve someone who wants to join my group', 'thrift_invite'),
    ('how do i record ajo contribution', 'thrift_contribution'),
    ('how do i collect daily contribution', 'thrift_contribution'),
    ('how do i pay out the pot', 'thrift_payout'),
    ('whose turn is it to collect the pot', 'thrift_payout'),
    ('how do i cash out a customer', 'thrift_payout'),
    ('how do i add an approver to my group', 'thrift_approver'),
    ('how do i record my personal savings', 'thrift_personal'),
    ('how do i record school fees?', 'school_payment'),
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


def test_production_answers_use_the_page_words():
    import pathlib
    src = pathlib.Path(__file__).with_name("frontend").joinpath("src")
    page = src.joinpath("pages", "Production.jsx").read_text(encoding="utf-8")
    for label in ("Record production", "Recipes", "Distributors", "Report", "History", "+ Add or change a recipe for…",
                  "One batch makes how many", "What one batch uses", "Add material", "Other costs per batch",
                  "Save recipe", "Delete recipe", "What did you make?", "How many good ones", "Rejects",
                  "Turned back into", "Other costs (gas, labour…)", "Best before", "to make", "Undo",
                  "Made, sold and removed", "Materials: used vs the recipe", "Left now",
                  "Send goods out with a seller", "Send out", "Out with sellers now", "Settle", "Back, good",
                  "Back, spoilt", "Paid now", "Pay by", "Sellers", "Owes now", "Their price"):
        assert label in page, label
    settings = src.joinpath("pages", "Settings.jsx").read_text(encoding="utf-8")
    assert "Show Production in the menu" in settings


def test_money_answers_use_the_page_words():
    import pathlib
    src = pathlib.Path(__file__).with_name("frontend").joinpath("src", "pages")
    read = lambda n: src.joinpath(n).read_text(encoding="utf-8")   # noqa: E731
    exp = read("Expenses.jsx")
    for label in ("Add expense", "Amount (₦)", "Type", "Date spent", "Note (optional)", "Save expense", "To review",
                  "Approve", "Not an expense", "Total spent", "This week", "All time"):
        assert label in exp, label
    sup = read("Suppliers.jsx")
    for label in ("+ Add supplier", "New purchase", "Cost/unit (₦)", "Payment due", "Save purchase", ">Pay<",
                  "Record payment", "Total owed to suppliers", "Balance owed", "Suppliers with overdue"):
        assert label in sup, label
    tx = read("Transactions.jsx")
    for label in ("Export", "Transactions CSV", "Unpaid Debtors CSV", "Customer List CSV", "Stock Inventory CSV",
                  "All branches"):
        assert label in tx, label
    dash = read("Dashboard.jsx")
    for label in ("Gross profit", "Net profit", "Add costs", "You owe suppliers", "Bought vs Sold Report",
                  "Download Report PDF", "Download Statement PDF", "Branch:"):
        assert label in dash, label
    ins = read("Insights.jsx")
    for label in ("Profit by product", "Margin snapshot", "No cost"):
        assert label in ins, label


def test_setup_answers_use_the_page_words():
    import pathlib
    src = pathlib.Path(__file__).with_name("frontend").joinpath("src")
    read = lambda *p: src.joinpath(*p).read_text(encoding="utf-8")   # noqa: E731
    up = read("pages", "Upgrade.jsx")
    for label in ("Monthly", "Yearly", "by Bank Transfer", "Reference / Narration", "I've made the transfer",
                  "Contact support to downgrade", "Enterprise", "Talk to us", "Send — we'll call you",
                  "Current plan: ", "currently unavailable"):
        assert label in up, label
    assert "Have a plan code?" in read("pages", "Dashboard.jsx") and "Activate" in read("pages", "Dashboard.jsx")
    assert "Upgrade Plan ✦" in read("components", "Layout.jsx")
    page = read("pages", "BusinessPage.jsx")
    for label in ("Products on your page", "Show prices (off: \"Ask for price\")", "Save", "Quotation requests",
                  "Make quotation", "Open quotation", "Your page", "Copy link", "Share on WhatsApp", "Open"):
        assert label in page, label
    assert "Forgot PIN or never set one?" in read("pages", "Login.jsx")


def test_pin_and_upgrade_guides_tell_the_truth():
    # My Profile has no PIN change (it's a WhatsApp command); card payment is off;
    # the plan-code box is on the Dashboard, not the Upgrade page
    from faq import FAQ_ANSWERS
    pin = FAQ_ANSWERS["pin_help"]
    assert "My Profile" not in pin and "change pin 1234 5678" in pin and "Forgot PIN or never set one?" in pin
    up = FAQ_ANSWERS["upgrade"]
    assert "Card payment is unavailable" in up and "Have a plan code?" in up and "on the Upgrade page" not in up


def test_business_type_answers_use_the_page_words():
    import pathlib
    src = pathlib.Path(__file__).with_name("frontend").joinpath("src", "pages")
    read = lambda n: src.joinpath(n).read_text(encoding="utf-8")   # noqa: E731
    school = read("School.jsx")
    for label in ("Collect fees", "Pupils", "This term", "Setup", "School year", "Start session", "Classes",
                  "Add class", "What you charge for", "What each class owes this term", "Save fees",
                  "Charge this term", "Register pupil", "Pupil's name *", "Parent / guardian", "Parent's phone",
                  "Find a pupil", "Amount paid", "Pay all", "Record payment", "Fees", "Arrangement", "Pays nothing",
                  "Percentage off", "Amount off the bill", "Pays an agreed amount", "Applies to", "For how long",
                  "Every term", "This term only", "Books and extras", "Charge ticked items", "Outstanding",
                  "Collection rate"):
        assert label in school, label
    egg = read("Poultry.jsx")
    for label in ("Egg Collection", "Feed Usage", "Report", "Crates collected — by grade", "Save collection",
                  "Feed used today", "Save feed used", "Eggs — collected vs sold", "Margin over feed"):
        assert label in egg, label
    fuel = read("FuelStation.jsx")
    for label in ("Overview", "Shifts", "Deliveries", "Dips", "Add tank", "Save tank", "Add pump", "Save pump",
                  "Set pump price", "Price per litre (₦)", "Save price", "Open shift", "Close shift", "Closing meter",
                  "Close & reconcile", "Record delivery", "Litres delivered", "Save delivery", "Record tank dip",
                  "Dipped litres (physical reading)", "Save dip"):
        assert label in fuel, label
    thrift = read("Thrift.jsx") + read("ThriftGroups.jsx")
    for label in ("Group Thrift / Ajo", "Personal Savings", "Create Ajo / Thrift group", "Rotating (ajo)",
                  "Daily collection", "Target (shared goal)", "Group name *", "Frequency", "Member limit *",
                  "Who collects the pot?", "Create group", "Invite link — share it so people can join", "Copy",
                  "Add participant", "Add customer", "Pending approvals", "Approve", "Decline", "Collect", "Record",
                  "Add saving", "Pot collector:", "Choose member…", "Pay", "Record payout", "I received it",
                  "Cash out", "Give approval power", "Your savings plan", "How often do you save?", "Save plan",
                  "Record Saving"):
        assert label in thrift, label


def test_school_guide_uses_the_page_words():
    from faq import FAQ_ANSWERS
    a = FAQ_ANSWERS["school_fees"]
    for gone in ("Record fee payment", "My students", "Add Student"):
        assert gone not in a, gone
    for word in ("Collect fees", "Register pupil", "Charge this term", "Start session", "Save fees"):
        assert word in a, word
