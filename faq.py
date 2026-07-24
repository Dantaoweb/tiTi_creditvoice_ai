"""
Keyword FAQ for CreditVoice.

detect_faq(text) -> key | None
get_faq_answer(key) -> str
"""
import re

# ── Detection ─────────────────────────────────────────────────────────────────

_QUESTION_STARTERS = (
    "how", "what", "where", "when", "why",
    "can i", "do i", "is there", "show me",
    "help me", "help with", "i don't know", "i dont know",
    "teach me", "explain", "check", "list of",
)


def _is_question(text):
    q = text.lower().strip()
    if "?" in q:
        return True
    if any(q.startswith(s) for s in _QUESTION_STARTERS):
        return True
    # "how do i …" or "how to …" anywhere in the text
    if re.search(r"\bhow\s+(do|to|can|should)\b", q):
        return True
    return False


def detect_faq(text):
    if not _is_question(text):
        return None
    q = text.lower()

    # ── Receipt (specific — check before customer) ────────────────────────────
    if any(k in q for k in ["receipt", "print receipt", "send receipt"]):
        return "receipt"

    # ── Customer profile / measurements / vehicle / device details ───────────
    if any(k in q for k in [
        "measurement", "measurements", "write measurement", "save measurement",
        "add measurement", "record measurement", "tailor measurement",
        "customer profile", "customer details", "customer measurement",
        "vehicle details", "device details", "customer note about", "save details",
    ]):
        return "customer_profile"

    # ── Delivery / ready-by date & deliveries ────────────────────────────────
    if any(k in q for k in [
        "delivery date", "deliver by", "ready by", "ready date", "collection date",
        "pickup date", "when to deliver", "deliveries", "delivery reminder",
        "job ready", "remind me to deliver", "promise date", "when will it be ready",
    ]):
        return "delivery_date"

    # ── Catalog / price list (fast product/service setup) ────────────────────
    if any(k in q for k in [
        "catalog", "catalogue", "product catalog", "price list", "pricelist",
        "add my products", "add products fast", "bulk add", "add many products",
        "ready made list", "suggested price", "add services fast", "service list",
    ]):
        return "catalog"

    # ── Overdue / unpaid debtors ──────────────────────────────────────────────
    if any(k in q for k in [
        "overdue", "who owes me", "who owe me", "who are owing me",
        "who are owning me", "who is owing me", "owing me",
        "unpaid debtor", "debtors", "due debtor", "check debtor",
        "overdue customer", "who owe", "check due", "due customer",
        "my debtors", "all debtors", "people owing me",
        "those who owe me", "customers owing me", "who still owe",
        "past due", "check who owes",
    ]):
        return "overdue_debtors"

    # ── Customer account / balance check ─────────────────────────────────────
    if any(k in q for k in [
        "customer balance", "customer account", "what does balance", "what is balance",
        "customer owe", "how much owe", "check debt", "see what customer",
        "outstanding balance", "customer summary", "ade balance", "ade account",
        "check balance", "view balance", "see balance",
    ]):
        return "check_balance"
    if "balance" in q and any(k in q for k in ["what", "how", "check", "see", "view", "mean"]):
        return "check_balance"
    if re.search(r"\bowes?\b", q):
        return "check_balance"

    # ── Customer list ─────────────────────────────────────────────────────────
    if any(k in q for k in [
        "customer list", "list of customer", "list of my customer",
        "check customer list", "see customer", "view customer",
        "all customer", "all customers", "my customer", "show customer",
        "check customers", "list customers", "show customers",
    ]):
        return "customer_list"

    # ── Stock item management (edit/rename/delete from stock menu) ────────────
    if any(k in q for k in [
        "edit stock", "rename stock", "rename item", "delete stock", "remove item",
        "edit item", "update stock item", "change stock name", "fix stock",
        "wrong stock name", "fix product name", "edit product name",
        "how do i edit", "how to edit stock", "how to rename", "how to delete stock",
        "manage stock", "manage item",
    ]):
        return "stock_management"

    # ── Product alias ─────────────────────────────────────────────────────────
    if any(k in q for k in [
        "product alias", "alias", "shorthand", "short name", "same as",
        "eba means garri", "teach titi", "titi shorthand", "product shortcut",
    ]):
        return "product_alias"

    # ── Change business name / profile ───────────────────────────────────────
    if any(k in q for k in [
        "change name", "rename business", "update name", "change my name",
        "update business name", "change business name", "rename my business",
        "change profile", "update profile", "change my business type",
        "edit profile", "edit my name", "wrong name", "fix my name",
    ]):
        return "change_name"

    # ── Send reminders to customers ───────────────────────────────────────────
    if any(k in q for k in [
        "send reminder", "remind customer", "send payment reminder",
        "remind someone", "how to remind", "how do i remind",
        "send debt reminder", "manual reminder", "reminder to customer",
        "whatsapp reminder", "notify customer",
    ]):
        return "send_reminders"
    if "reminder" in q and any(k in q for k in ["send", "how", "customer", "whatsapp"]):
        return "send_reminders"

    # ── Reminder automation ───────────────────────────────────────────────────
    if any(k in q for k in [
        "reminder automation", "auto reminder", "automatic reminder",
        "daily reminder", "reminder time", "reminder queue",
        "set up reminder", "setup reminder", "enable reminder",
        "auto send reminder", "schedule reminder",
    ]):
        return "reminder_automation"

    # ── Thrift / ajo / esusu ──────────────────────────────────────────────────
    if any(k in q for k in [
        "thrift", "ajo", "esusu", "contribution", "cooperative",
        "how to record contribution", "record ajo", "record thrift",
        "daily saving", "group saving", "savings group",
    ]):
        return "thrift_ajo"

    # ── Multiple products in one sale ─────────────────────────────────────────
    if any(k in q for k in [
        "multiple product", "multiple items", "more than one product",
        "sell many", "sell multiple", "multi item", "two products",
        "record many items", "several products", "list of products",
        "buy many", "bought many",
    ]):
        return "multi_item_sale"

    # ── Direct sale / income without customer name ────────────────────────────
    if any(k in q for k in [
        "direct sale", "no customer", "without customer", "cash sale",
        "walk in customer", "one time customer", "anonymous sale",
        "record income", "service income", "i sold", "i received",
        "personal sale", "sell without name",
    ]):
        return "direct_sale"

    # ── Account recovery / PIN ────────────────────────────────────────────────
    if any(k in q for k in [
        "recover account", "account recovery", "lost my number", "lost phone",
        "lost phone number", "change my number", "new number", "transfer account",
        "move account", "recover my account", "how do i recover",
    ]):
        return "account_recovery"

    if any(k in q for k in [
        "recovery pin", "set pin", "set a pin", "create pin",
        "protect my account", "account protection", "how do i protect",
        "change pin", "remove pin", "what is pin",
    ]):
        return "recovery_pin"

    # ── Linked phones / multi-phone ───────────────────────────────────────────
    if any(k in q for k in [
        "link phone", "linked phone", "second phone", "two phones",
        "another phone", "multiple phones", "second number",
        "unlink phone", "unlink a phone", "unlink number", "remove linked",
        "my phones", "second device", "use two phones",
    ]):
        return "linked_phones"

    # ── Shop tag ──────────────────────────────────────────────────────────────
    if any(k in q for k in ["shop tag", "my shop tag", "change shop tag",
                              "shop name", "what is shop tag", "set shop tag"]):
        return "shop_tag"

    # ── Customer bot / WhatsApp Status selling ────────────────────────────────
    if any(k in q for k in [
        "customer bot", "whatsapp status", "status selling", "sell on status",
        "bot on", "bot off", "how does bot", "how do customer order",
        "how do customers order", "customer order", "customers order",
        "online selling", "sell online", "status order", "from my status",
        "from status", "set up bot", "setup bot", "enable bot", "activate bot",
        "auto order", "delivery note", "payment mode",
    ]):
        return "customer_bot"
    if "bot" in q and any(k in q for k in ["how", "set", "enable", "what", "turn"]):
        return "customer_bot"
    if "status" in q and any(k in q for k in ["sell", "order", "customer", "selling", "how"]):
        return "customer_bot"

    # ── Void / undo transaction ───────────────────────────────────────────────
    if any(k in q for k in [
        "void transaction", "undo transaction", "cancel transaction",
        "reverse transaction", "correct transaction", "delete transaction",
        "remove transaction", "void a sale", "undo a sale", "cancel a sale",
        "how do i void", "how do i undo", "how to void", "how to undo",
    ]):
        return "void_transaction"
    if "void" in q and any(k in q for k in ["how", "what", "transaction", "sale", "last"]):
        return "void_transaction"

    # ── Conversational analytics ──────────────────────────────────────────────
    if any(k in q for k in [
        "why are my sales", "why is my sale", "why sales declining",
        "who owes me the most", "biggest debtor", "top debtors", "top debtor",
        "best selling product", "best product", "most popular product",
        "what sells most", "what do i sell most",
        "when am i busiest", "my peak period", "busiest day", "peak time",
        "most sales day", "when do i make most",
        "is this product profitable", "is it profitable", "product profit",
        "how profitable", "should i keep selling",
    ]):
        return "analytics"
    if any(k in q for k in ["ask titi", "titi can answer", "analyse", "analyze"]):
        return "analytics"

    # ── Fast mode ─────────────────────────────────────────────────────────────
    if "fast mode" in q or ("fast" in q and "mode" in q):
        return "fast_mode"

    # ── Loan-ready statement / PDF ────────────────────────────────────────────
    if any(k in q for k in [
        "loan statement", "business statement", "financial statement",
        "pdf statement", "download statement", "get statement",
        "statement for bank", "statement for loan", "loan ready",
        "bank statement", "microfinance statement", "loan pdf",
        "statement pdf", "download pdf", "bank pdf",
        "proof of income", "show my business", "statement report",
    ]):
        return "loan_statement"
    if "statement" in q and any(k in q for k in ["download", "get", "how", "pdf", "bank", "loan"]):
        return "loan_statement"
    if "pdf" in q and any(k in q for k in ["download", "get", "how", "statement", "report"]):
        return "loan_statement"

    # ── Staff profile ─────────────────────────────────────────────────────────
    if any(k in q for k in [
        "staff profile", "staff salary", "staff position", "staff level",
        "employee profile", "set salary", "matric number", "employee id",
        "staff id", "staff matric", "set staff", "view staff profile",
        "staff details", "staff info", "update staff",
    ]):
        return "staff_profile"

    # ── Shared notes (check before partners so "note for partner" lands here) ─
    if any(k in q for k in [
        "business note", "shared note", "business notes",
        "add note", "view note", "expense note", "note for partner",
        "partner note", "investor note", "agreement note",
        "record expense note", "shared memo", "note visibility",
        "share a note", "share note",
    ]):
        return "business_notes"

    # ── Business partners / investors ─────────────────────────────────────────
    if any(k in q for k in [
        "partner", "co-founder", "cofounder", "co founder",
        "investor", "silent investor", "business partner",
        "invite partner", "add partner", "add investor",
        "partner access", "investor access", "equity",
        "partnership", "join my business",
        "accept partner", "decline partner", "remove partner",
        "partner view", "what can partner see", "partner permission",
    ]):
        return "business_partners"

    # ── Invoices ──────────────────────────────────────────────────────────────
    if any(k in q for k in [
        "invoice", "invoices", "send invoice", "create invoice", "make invoice",
        "bill customer", "invoice number", "unpaid invoice", "invoice status",
    ]):
        return "invoices"

    # ── Branch / location tagging ─────────────────────────────────────────────
    if any(k in q for k in [
        "branch", "add branch", "create branch", "my branch",
        "location tag", "tag location", "which branch", "set branch",
        "branches", "shop location", "tag by location", "branch tag",
        "track by branch", "branch filter", "branch name",
    ]):
        return "branch_location"

    # ── PWA / install / offline ───────────────────────────────────────────────
    if any(k in q for k in [
        "install app", "install on phone", "add to home screen",
        "home screen", "pwa", "progressive web", "app icon",
        "offline mode", "no internet", "without internet", "work offline",
        "app offline", "offline queue", "offline sync", "pending sync",
        "how to install", "install the app", "save to phone",
        "install creditvoice", "install titi",
    ]):
        return "pwa_install"
    if "offline" in q and any(k in q for k in ["how", "what", "work", "use", "record", "sync"]):
        return "pwa_install"
    if "install" in q and any(k in q for k in ["how", "app", "phone", "android", "iphone"]):
        return "pwa_install"

    # ── Quick Record / web form ───────────────────────────────────────────────
    if any(k in q for k in [
        "quick record", "web form", "record from web", "record on web",
        "web dashboard record", "manual entry", "web app record",
        "use the website", "use the web", "form to record",
        "record without whatsapp", "record on computer",
        "dashboard form", "capture form",
    ]):
        return "quick_record"
    if "web" in q and any(k in q for k in ["record", "sale", "payment", "how", "capture"]):
        return "quick_record"

    # ── CSV export / download data ────────────────────────────────────────────
    if any(k in q for k in [
        "export", "download my data", "export data", "download data",
        "export transactions", "download transactions",
        "export to excel", "excel export", "csv", "spreadsheet",
        "download customers", "export customers", "export debtors",
        "download debtors", "export stock", "download stock",
        "backup my data", "get my data",
    ]):
        return "export_data"

    # ── Staff accounts ────────────────────────────────────────────────────────
    if any(k in q for k in [
        "add staff", "staff account", "staff member", "invite staff",
        "staff access", "my assistant", "give access", "delegate",
        "staff invite", "create staff", "new staff", "staff can",
        "staff permission", "who can record", "second user",
        "another user", "another person record",
    ]):
        return "staff_accounts"
    if "staff" in q and any(k in q for k in ["how", "add", "invite", "access", "what"]):
        return "staff_accounts"

    # ── Upgrade / plan ────────────────────────────────────────────────────────
    if any(k in q for k in ["upgrade", "go plan", "subscription", "what does go", "go include"]):
        return "upgrade"

    # ── Due date / reminders (check before customer) ──────────────────────────
    if any(k in q for k in [
        "due date", "payment due", "set reminder", "remind customer",
        "when to pay", "debt reminder", "payment reminder",
        "check due", "due debtor", "check overdue", "how to check due",
        "how do i check due", "see due", "view due",
    ]):
        return "due_date"

    # ── Sell from stock / select product (check before add_stock) ────────────
    if any(k in q for k in ["sell from stock", "select product", "product list", "use stock to sell"]):
        return "sell_from_stock"
    if "select" in q and "product" in q:
        return "sell_from_stock"

    # ── Restock at new price → add_stock (check before add_supplier) ─────────
    if "restock" in q and any(k in q for k in ["price", "cost", "new", "update"]):
        return "add_stock"

    # ── Supplier list (before generic supplier add) ───────────────────────────
    if any(k in q for k in [
        "supplier list", "list suppliers", "my suppliers", "show suppliers",
        "check suppliers", "view suppliers", "see suppliers", "all suppliers",
    ]):
        return "supplier_list"

    # ── Supplier (add / record) ───────────────────────────────────────────────
    if any(k in q for k in [
        "add supplier", "record supplier", "supplier purchase",
        "bought from supplier", "supply me", "i buy from",
        "stock i bought", "bought stock",
    ]):
        return "add_supplier"
    if "supplier" in q and any(k in q for k in ["how", "add", "record", "save"]):
        return "add_supplier"
    if "restock" in q and "supplier" in q:
        return "add_supplier"

    # ── Check / view stock (before generic stock) ─────────────────────────────
    if any(k in q for k in [
        "check stock", "view stock", "see stock", "my stock",
        "show stock", "show my stock", "show inventory",
        "inventory", "stock list", "how much stock", "quantity left",
        "what is in stock", "what i have in stock",
    ]):
        return "check_stock"
    if "stock" in q and any(k in q for k in ["check", "view", "see", "list", "show", "left", "remaining"]):
        return "check_stock"
    if "inventory" in q and any(k in q for k in ["check", "view", "see", "show", "list"]):
        return "check_stock"

    # ── Dashboard / reports (before record_sale) ──────────────────────────────
    if any(k in q for k in [
        "dashboard", "sales report", "see report", "daily report",
        "sales today", "how much i made", "how much did i make",
        "total sales", "my sales", "profit", "how much have i",
    ]):
        return "dashboard"
    if "report" in q and any(k in q for k in ["how", "see", "check", "view", "get"]):
        return "dashboard"

    # ── Record a payment ──────────────────────────────────────────────────────
    if any(k in q for k in [
        "record payment", "record a payment", "customer paid",
        "paid me", "mark as paid", "payment received", "collect payment",
        "record that he paid", "record that she paid",
    ]):
        return "record_payment"
    if "payment" in q and any(k in q for k in ["how", "record", "save", "enter"]):
        return "record_payment"
    if "paid" in q and any(k in q for k in ["record", "save", "how do i", "how to"]):
        return "record_payment"

    # ── Add / save customer (before record_sale) ──────────────────────────────
    if "debt" not in q and any(k in q for k in [
        "add customer", "save customer", "register customer",
        "customer number", "customer phone", "new customer", "create customer",
    ]):
        return "add_customer"
    if "customer" in q and "debt" not in q and any(k in q for k in ["add", "save", "create", "register", "new"]):
        return "add_customer"

    # ── Record a sale / customer debt ─────────────────────────────────────────
    if any(k in q for k in [
        "record sale", "record a sale", "customer bought", "someone bought",
        "add debt", "record debt", "credit sale", "sell to customer",
        "sold to customer", "give on credit",
    ]):
        return "record_sale"
    if any(k in q for k in ["debt", "credit"]) and any(k in q for k in ["how", "record", "add"]):
        return "record_sale"

    # ── Add stock / set prices ────────────────────────────────────────────────
    if any(k in q for k in [
        "add stock", "set price", "add product", "add item", "new product",
        "selling price", "cost price", "stock price", "set up product",
        "setup product", "create product", "restock at", "new cost",
        "update price", "change price",
    ]):
        return "add_stock"
    if "product" in q and any(k in q for k in ["add", "create", "set up", "new", "how"]):
        return "add_stock"
    if "stock" in q and any(k in q for k in ["add", "create", "new", "put", "enter"]):
        return "add_stock"

    # ── Generic help / formats ────────────────────────────────────────────────
    if any(k in q for k in ["help", "formats", "what can", "commands", "what do"]):
        return "formats"

    return None


# ── Answers ───────────────────────────────────────────────────────────────────

FAQ_ANSWERS = {
    "catalog": (
        "To add your products/services fast from the ready-made list:\n\n"
        "Open the web app → *Inventory* (Stock) → tap *Catalog*.\n\n"
        "tiTi shows items matched to your business type:\n"
        "• Shops → products by category (phone shop sees chargers/cases, not garri, etc.)\n"
        "• Services (laundry, barber, mechanic…) → a *price list* with suggested prices\n\n"
        "Tick what you sell and tap *Add*. For services the suggested price is added for you; "
        "for products you set the price after in the Inventory table.\n\n"
        "To add many names at once, tap *Bulk add*. On WhatsApp, add one at a time:\n"
        "add stock rice cost 3000 sell 4000"
    ),
    "customer_profile": (
        "To save a customer's measurements/details:\n\n"
        "Open the web app → *Customers* → tap the pencil (Details) button next to the customer.\n\n"
        "The form shows the right fields for your business:\n"
        "• Tailor → neck, shoulder, chest, waist, hip, lengths, etc.\n"
        "• Mechanic → vehicle make, model, plate number, colour\n"
        "• Phone repair → device, model, IMEI, fault, unlock\n"
        "• Others → a Notes box\n\n"
        "Fill them in and tap *Save*. The details stay on the customer for next time.\n\n"
        "(This is on the web app dashboard, not a WhatsApp command yet.)"
    ),
    "delivery_date": (
        "To set when a job/order will be ready and be reminded:\n\n"
        "1. Record the sale on the web app POS (*Select product*).\n"
        "2. Set the *Deliver / ready by* date before saving.\n\n"
        "tiTi reminds you *2 days before, 1 day before, and on the day*.\n\n"
        "Open *Deliveries* in the app to change the date, or to send the customer a "
        "'your order is ready' message (you type it and tap send — never automatic).\n\n"
        "(This is on the web app dashboard.)"
    ),
    "overdue_debtors": (
        "To see who owes you:\n\n"
        "Send: due\n"
        "Then choose:\n"
        "1. Debts due in 2 days\n"
        "2. Debts due today\n"
        "3. Overdue debtors\n\n"
        "Or send: dashboard → then choose 8 for Unpaid Debtors."
    ),
    "customer_list": (
        "To see your customer list, send:\n\n"
        "customer list\n\n"
        "Or go to dashboard → choose 7 for Customer List.\n\n"
        "To see who owes you the most, send: due"
    ),
    "add_stock": (
        "How to add stock:\n\n"
        "With quantity + price in one message:\n"
        "add stock honey 10 liters at 10000, selling price 12000\n\n"
        "Price only (no quantity):\n"
        "add stock rice cost 3000 sell 4000\n\n"
        "Quantity only (keeps existing price):\n"
        "add stock 10 bags rice\n\n"
        "Restock at a new price (adds to what is already there):\n"
        "add stock eggs 150 crates at 5600, selling price 6200\n\n"
        "Update price only (no quantity change):\n"
        "add stock eggs crate cost 5600 sell 6200\n\n"
        "Send  formats  to see all examples."
    ),
    "record_sale": (
        "How to record a customer sale:\n\n"
        "Ade bought rice 5000\n"
        "Ade bought 3 bags rice at 2000 each\n"
        "Ade bought rice 5000 paid 2000\n\n"
        "With due date:\n"
        "Ade bought rice 5000 paid 2000 due tomorrow\n\n"
        "Sold form:\n"
        "i sold 3 liters honey to Ade at 4000 paid 2000"
    ),
    "record_payment": (
        "How to record a payment:\n\n"
        "Ade paid 3000\n"
        "Ade paid 5000 balance 2000\n\n"
        "To clear the full debt:\n"
        "Ade paid 10000\n\n"
        "tiTi will update the balance automatically."
    ),
    "check_balance": (
        "To see what a customer owes:\n\n"
        "Ade balance\n"
        "Ade account\n"
        "Ade balance this month\n"
        "customer summary Ade\n\n"
        "Balance = total charged minus what they have paid.\n"
        "tiTi tracks this with every sale and payment you record.\n\n"
        "To see all customers:\n"
        "customer list\n\n"
        "To see overdue debtors:\n"
        "due"
    ),
    "sell_from_stock": (
        "To sell from your product list:\n\n"
        "select product\n\n"
        "tiTi shows your products with prices.\n"
        "Pick a number, send quantity, then checkout.\n\n"
        "To sell at a different price send:\n"
        "3 at 2500\n"
        "instead of just the quantity."
    ),
    "supplier_list": (
        "To see your supplier list, send:\n\n"
        "suppliers\n\n"
        "To see what you owe each supplier:\n"
        "supplier debts\n\n"
        "To see payments due today:\n"
        "supplier due\n\n"
        "To see upcoming supplier payments:\n"
        "supplier due this week"
    ),
    "add_supplier": (
        "How to record a supplier purchase:\n\n"
        "Ayo supply me 10 bags rice at 5000 each\n"
        "I buy 12 liters oil from Ayo at 3000\n\n"
        "To record payment to supplier:\n"
        "I paid Ayo 14000 for rice\n\n"
        "To see all suppliers:\n"
        "suppliers\n\n"
        "To see supplier payments due today:\n"
        "supplier due\n\n"
        "To see payments due this week:\n"
        "supplier due this week"
    ),
    "check_stock": (
        "To see your current stock:\n\n"
        "stock\n\n"
        "To check a specific product:\n"
        "stock honey\n"
        "stock rice"
    ),
    "add_customer": (
        "To add a customer:\n\n"
        "add customer Ade\n\n"
        "To save their phone number:\n"
        "Ade phone 08012345678\n\n"
        "Saving the number lets tiTi send receipts directly to the customer."
    ),
    "dashboard": (
        "To see your sales and reports:\n\n"
        "dashboard\n\n"
        "Or ask directly:\n"
        "sales today\n"
        "sales this week\n"
        "sales this month\n"
        "margin report\n"
        "products below cost"
    ),
    "due_date": (
        "To set a due date on a sale:\n\n"
        "Ade bought rice 5000 paid 2000 due tomorrow\n"
        "Ade bought rice 5000 due 15/6/2026\n\n"
        "To send WhatsApp reminders when balances are due:\n"
        "due\n\n"
        "tiTi will show you debts due in 2 days, due today, and overdue.\n"
        "Pick a customer number to preview and send their reminder."
    ),
    "fast_mode": (
        "Fast mode is for busy market hours.\n\n"
        "Turn on:\n"
        "fast mode on\n"
        "fast mode on 8am to 6pm\n\n"
        "tiTi records instantly without confirmation.\n"
        "When done for the day send:\n"
        "close sales\n\n"
        "Turn off:\n"
        "fast mode off"
    ),
    "upgrade": (
        "To upgrade:\n\n"
        "upgrade\n\n"
        "GO plan includes:\n"
        "- Inventory and stock tracking\n"
        "- Supplier records\n"
        "- Product reports\n"
        "- Debt reminders\n"
        "- Staff accounts\n\n"
        "Send  my plan  to see your current plan."
    ),
    "receipt": (
        "To print a receipt for a customer:\n\n"
        "print receipt Ade\n"
        "receipt 42\n\n"
        "Receipts are sent automatically when you use:\n"
        "select product\n\n"
        "Save the customer number first:\n"
        "Ade phone 08012345678"
    ),
    "shop_tag": (
        "Your shop tag is a short name customers use to find your shop.\n\n"
        "When you turn the bot on, tiTi creates one automatically.\n"
        "You can change it anytime:\n\n"
        "shop tag demopharmacy\n\n"
        "Rules:\n"
        "- One word, no spaces\n"
        "- Letters and numbers only\n"
        "- Must be unique across all shops\n\n"
        "Customers use it like this:\n"
        "shop demopharmacy\n\n"
        "To see your current tag:\n"
        "bot settings"
    ),
    "customer_bot": (
        "The customer bot lets people order from your WhatsApp Status.\n\n"
        "Setup steps:\n\n"
        "1. Add your products with selling prices\n"
        "2. Turn the bot on:\n"
        "   bot on\n"
        "3. Set delivery info:\n"
        "   delivery note Same day delivery within Lagos\n"
        "4. Set payment info:\n"
        "   payment mode Transfer to 0123456789 GTB\n"
        "5. Post the caption tiTi gives you on your WhatsApp Status\n\n"
        "Customers message you with your shop tag:\n"
        "shop demopharmacy\n\n"
        "tiTi shows your products, takes orders, and alerts you.\n\n"
        "Other bot commands:\n"
        "auto order on\n"
        "bot off\n"
        "bot settings\n"
        "pending orders\n"
        "confirm payment 1\n"
        "deliver order 1"
    ),
    "recovery_pin": (
        "A recovery PIN protects your account if you ever lose or change your phone number.\n\n"
        "Set a PIN (4 to 6 digits):\n"
        "set pin 1234\n\n"
        "Change your PIN:\n"
        "change pin 1234 5678\n\n"
        "Remove your PIN:\n"
        "remove pin 1234\n\n"
        "Keep your PIN somewhere safe — tiTi cannot reset it for you."
    ),
    "account_recovery": (
        "If you lose or change your phone number, you can recover your account using your PIN.\n\n"
        "From your new number, send:\n"
        "recover 08012345678 1234\n\n"
        "Replace 08012345678 with your old number and 1234 with your PIN.\n\n"
        "All your data, customers, stock, and transactions will transfer to the new number.\n\n"
        "No PIN set? Recovery is not possible without one.\n"
        "Set yours now before you need it:\n"
        "set pin 1234"
    ),
    "linked_phones": (
        "You can link a second phone number to access your account from two devices.\n\n"
        "From your main phone:\n"
        "link phone 08012345678\n\n"
        "tiTi sends a code to you. Tell the second phone to send:\n"
        "link confirm [code]\n\n"
        "The linked phone gets full owner access — same as your main number.\n\n"
        "To see your linked phones:\n"
        "my phones\n\n"
        "To remove a linked phone:\n"
        "unlink phone 08012345678\n\n"
        "Maximum 2 linked phones per account."
    ),
    "void_transaction": (
        "To void (undo) a transaction:\n\n"
        "void last\n"
        "void 42\n"
        "void last customer returned goods\n\n"
        "The transaction will no longer count in balances or reports.\n"
        "A note is saved recording who voided it and when.\n\n"
        "If a staff member voids a transaction, the business owner gets an alert immediately.\n\n"
        "Staff can only void transactions they personally recorded.\n"
        "To void a transaction recorded by someone else, the owner must do it."
    ),
    "analytics": (
        "You can ask tiTi questions about your business and get answers from your actual records.\n\n"
        "Examples:\n\n"
        "who owes me the most\n"
        "why are my sales declining\n"
        "what is my best selling product\n"
        "when am i busiest\n"
        "is honey profitable\n\n"
        "tiTi will check your records and give you an honest answer with suggestions.\n\n"
        "Send  formats  to see all commands."
    ),
    "change_name": (
        "To update your business name or type:\n\n"
        "change name\n\n"
        "tiTi will walk you through the update step by step.\n"
        "Your customers, records, and transactions are not affected."
    ),
    "send_reminders": (
        "To send payment reminders to your debtors:\n\n"
        "1. Send:  due\n"
        "2. Choose a list:\n"
        "   1. Due in 2 days\n"
        "   2. Due today\n"
        "   3. Overdue\n"
        "3. Pick a customer number to preview their reminder\n"
        "4. Reply YES to send it via WhatsApp\n\n"
        "To skip a customer:\n"
        "skip reminder\n\n"
        "To set up automatic daily reminders:\n"
        "reminder automation"
    ),
    "reminder_automation": (
        "Reminder automation sends daily WhatsApp payment reminders to your debtors.\n\n"
        "See current settings:\n"
        "reminder automation\n\n"
        "Preview reminders before they go out:\n"
        "reminder preview on\n\n"
        "Turn on automatic sending:\n"
        "auto reminders on\n\n"
        "Set the time reminders go out:\n"
        "reminder time 8am\n\n"
        "See today's reminder queue:\n"
        "reminder queue\n\n"
        "Turn off automatic sending:\n"
        "auto reminders off"
    ),
    "thrift_ajo": (
        "To record a thrift, ajo, or esusu contribution:\n\n"
        "Amina contributed 5000\n"
        "Tunde paid thrift 2000\n"
        "Ade saved 3000\n\n"
        "tiTi records it as a payment and updates their balance.\n\n"
        "To check a member's total contributions:\n"
        "Amina balance\n"
        "customer summary Amina"
    ),
    "multi_item_sale": (
        "To record a sale with multiple products at once:\n\n"
        "Ade bought rice 4000, beans 3000\n"
        "Ade bought rice 4000, beans 3000, oil 2000 paid 5000\n"
        "Ade bought 2kg rice at 2000, 3 tins tomato at 500\n\n"
        "Separate each item with a comma.\n"
        "Add 'paid [amount]' at the end for a part payment.\n\n"
        "To sell from your product price list:\n"
        "select product"
    ),
    "direct_sale": (
        "To record a cash sale or service income without a named customer:\n\n"
        "I sold phone 45000\n"
        "I received 2000 for washing\n"
        "I supply 1 truck of sand 60000\n"
        "I collected 5000 for haircut\n\n"
        "tiTi records it as direct income. No customer debt is created.\n\n"
        "To record a walk-in sale and still track stock:\n"
        "select product"
    ),
    "stock_management": (
        "To manage a stock item, first send:\n\n"
        "stock\n\n"
        "tiTi shows your product list with numbers.\n"
        "Type the number of the item you want, then choose:\n\n"
        "1. Add more quantity\n"
        "2. Update price\n"
        "3. Delete item\n"
        "4. Rename item\n\n"
        "To add stock with prices in one message:\n"
        "add stock rice cost 3000 sell 4000"
    ),
    "product_alias": (
        "Product aliases let tiTi understand your shorthand.\n\n"
        "If your customers say 'eba' but your stock says 'garri':\n"
        "alias eba = garri\n\n"
        "Other ways to teach tiTi:\n"
        "eba same as garri\n"
        "panadol means paracetamol\n\n"
        "After saving, tiTi will automatically match the alias to the correct product."
    ),
    "formats": (
        "Send this to see all examples and commands:\n\n"
        "formats"
    ),
    "loan_statement": (
        "The business statement is a professional PDF showing your revenue, receivables, and stock.\n"
        "It is ready to share with a bank or microfinance institution when applying for a loan.\n\n"
        "To download it from the web dashboard:\n"
        "1. Open your CreditVoice web dashboard\n"
        "2. Go to Dashboard\n"
        "3. Click  Download Statement PDF\n\n"
        "Via WhatsApp:\n"
        "Send:  dashboard\n"
        "Then choose option 11 (Business statement PDF)\n"
        "tiTi will send you a download link that works for 24 hours.\n\n"
        "The PDF includes:\n"
        "- Revenue and sales summary\n"
        "- Outstanding receivables (who owes you)\n"
        "- Stock assets and value\n"
        "- Full transaction history"
    ),
    "invoices": (
        "Invoices turn a credit sale into a formal bill with its own number "
        "(INV-0001). They're on the web app.\n\n"
        "To create one:\n"
        "1. Open the web dashboard → a customer's history (or the sale's receipt)\n"
        "2. Tap 'Invoice' / 'View as Invoice' — it gets a number automatically\n\n"
        "The Invoices page:\n"
        "- Lists every invoice with status Open, Overdue or Paid\n"
        "- Shows what's still outstanding\n"
        "- Lets you send an invoice to the customer's WhatsApp, and print/save as PDF\n\n"
        "An invoice is a request for payment (not a 'keep this receipt' slip). "
        "A paid-up customer's invoices show as Paid automatically."
    ),
    "branch_location": (
        "Branches let you run several locations, each with its own staff and its "
        "own separate records. They are set up and run *on the web app only* — not "
        "on WhatsApp.\n\n"
        "To set up branches (web app):\n"
        "1. Open the web dashboard → Menu → Branches\n"
        "2. Add a branch and enter its name (star one as default)\n"
        "3. Go to Staff → invite each staff, attaching them to a branch (you can do "
        "this right in the invite), or set their branch later with the Branch dropdown\n\n"
        "How a branch works:\n"
        "- A branch staff logs in on the web with THEIR OWN phone number and PIN "
        "(never the owner's), from their own device. They don't pick a branch at "
        "login — they're automatically scoped to the branch you assigned them.\n"
        "- A regular staff sees only what they personally recorded. Mark a staff as "
        "*branch admin* to let them see ALL records in their branch. You (the owner) "
        "see every branch and can filter the Dashboard/Transactions by branch.\n"
        "- New sales, customers and stock are tagged to the staff's branch.\n\n"
        "On WhatsApp you can't create or list branches — just record your sales as "
        "normal. Everything branch-related is done in the web app."
    ),
    "pwa_install": (
        "CreditVoice works as an app on your phone without downloading from an app store.\n\n"
        "To install:\n"
        "1. Open your web dashboard in Chrome or Safari on your phone\n"
        "2. Tap the browser menu (three dots or share button)\n"
        "3. Choose  Add to Home Screen\n"
        "4. Tap Install or Add\n\n"
        "The CreditVoice icon will appear on your home screen like any other app.\n\n"
        "Offline mode:\n"
        "If you record a sale or payment while offline, tiTi saves it locally and syncs it "
        "automatically the moment your internet returns.\n\n"
        "You will see:\n"
        "- Offline chip in the top bar when there is no connection\n"
        "- X pending when records are waiting to sync\n"
        "- Synced message when records upload successfully"
    ),
    "quick_record": (
        "Quick Record is the fast web form for recording sales, payments, and stock changes "
        "directly from your computer or phone browser.\n\n"
        "To use it:\n"
        "1. Open your CreditVoice web dashboard\n"
        "2. Click  Quick Record  in the sidebar\n"
        "3. Choose the tab:\n"
        "   - Sale: enter product, amount, and optional customer for credit sales\n"
        "   - Payment: search for a debtor and enter what they paid\n"
        "   - Stock: search a product and add or remove quantity\n"
        "4. Select a branch if you have locations set up\n"
        "5. Click the Record button\n\n"
        "All records sync to the same data as your WhatsApp messages.\n"
        "Works offline too — records save locally and sync when internet returns."
    ),
    "export_data": (
        "To export your data as a spreadsheet:\n\n"
        "From the web dashboard:\n"
        "1. Go to Transactions or Dashboard\n"
        "2. Click  Export\n"
        "3. Choose what to download:\n"
        "   - Transactions CSV\n"
        "   - Unpaid Debtors CSV\n"
        "   - Customer List CSV\n"
        "   - Stock Inventory CSV\n\n"
        "Files open in Excel, Google Sheets, or any spreadsheet app.\n\n"
        "Via WhatsApp:\n"
        "Send:  dashboard\n"
        "Then choose option 10 (Export data CSV)\n"
        "tiTi will send you a download link."
    ),
    "staff_accounts": (
        "Staff accounts (Pro plan) let your assistant or sales team record "
        "transactions on your behalf, with you keeping full oversight.\n\n"
        "To invite a staff member (web app → Staff):\n"
        "1. Enter their name and phone number\n"
        "2. Optionally attach them to a branch (and tick 'Join as branch admin')\n"
        "3. Share the invite link or accept code with them\n"
        "4. They open the link, enter the code, and create their PIN right there — "
        "then they're signed in. No extra code needed to log in afterwards.\n\n"
        "Everyday login: staff sign in with THEIR OWN phone number and PIN — never "
        "yours.\n\n"
        "What staff can do:\n"
        "- Record sales and payments via WhatsApp or web\n"
        "- View transactions they personally recorded\n\n"
        "What staff cannot do (unless you allow it):\n"
        "- See other people's transactions\n"
        "- Void another person's transactions\n"
        "- Add, edit or adjust stock (owner or branch admin only)\n"
        "- Manage branches or other staff\n\n"
        "Branch admin: go to Staff and tap 'Make branch admin' (they must be "
        "assigned to a branch). A branch admin sees all records in their branch "
        "AND can manage that branch's stock — but nothing outside their branch. A "
        "regular staff just records sales and sees only their own. If an invite "
        "code expired or was lost, tap 'Resend invite' for a fresh one."
    ),
    "staff_profile": (
        "Staff profiles let you keep HR records for each team member — position, level, salary, and employee ID.\n\n"
        "To set a staff profile send:\n"
        "  set staff profile [name] position cashier level junior salary 50000 matric EMP001\n\n"
        "You can update just one field at a time:\n"
        "  set staff profile Emeka salary 60000\n"
        "  set staff profile Amaka position senior cashier\n\n"
        "To view a profile:\n"
        "  view staff profile Emeka\n\n"
        "To see all staff profiles:\n"
        "  view staff profiles\n\n"
        "Or send *staff profiles* from the main menu, or go to More → Staff."
    ),
    "business_partners": (
        "Business partners let you bring a co-founder, active partner, investor, or silent investor "
        "into your business with controlled visibility.\n\n"
        "*Access levels:*\n"
        "- Co-Founder: Full view — sales, stock, customers, costs\n"
        "- Partner: Operations — sales, stock, customers\n"
        "- Investor: Financial summary — P&L and returns\n"
        "- Silent Investor: Investment status only\n\n"
        "*To invite a partner:*\n"
        "  invite partner 08012345678 co_founder 30%\n"
        "  invite partner 08012345678 investor 500000\n\n"
        "Your partner will receive a WhatsApp invitation.\n"
        "They reply:  ACCEPT PARTNER [your phone]\n\n"
        "*To view your partners:*\n"
        "  view partners\n\n"
        "*To remove a partner:*\n"
        "  remove partner 08012345678\n\n"
        "*If you are a partner in someone else's business:*\n"
        "  partner status  — see which businesses you are linked to\n"
        "  business overview  — see a summary based on your access level\n\n"
        "Partners can only observe — they cannot record transactions in your business.\n"
        "They can run their own business separately on tiTi."
    ),
    "business_notes": (
        "Business notes are shared memos, expense records, and agreements that you "
        "can make visible to your partners or investors.\n\n"
        "*To add a note:*\n"
        "  note rent paid 45000               ← visible to you only\n"
        "  note rent paid 45000 partners       ← visible to partners\n"
        "  note rent paid 45000 all            ← visible to partners and investors\n"
        "  note agreement Emeka owns 30% all   ← agreement visible to all\n\n"
        "*Categories tiTi auto-detects:*\n"
        "  expense — paid, buy, rent, salary, fuel, electricity\n"
        "  income  — received, income, revenue, profit\n"
        "  agreement — agreement, contract, signed, deal\n"
        "  memo    — everything else\n\n"
        "*To view notes:*\n"
        "  view notes\n"
        "  view notes expenses\n\n"
        "Partners and investors only see notes you have shared with them.\n"
        "Owner always sees all notes.\n\n"
        "You can also access Notes from the main menu → More → Notes."
    ),
}


def get_faq_answer(key):
    return FAQ_ANSWERS.get(key, FAQ_ANSWERS["formats"])
