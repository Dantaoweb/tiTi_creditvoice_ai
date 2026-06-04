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
    "teach me", "explain",
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

    # ── Fast mode ─────────────────────────────────────────────────────────────
    if "fast mode" in q or ("fast" in q and "mode" in q):
        return "fast_mode"

    # ── Upgrade / plan ────────────────────────────────────────────────────────
    if any(k in q for k in ["upgrade", "go plan", "subscription", "what does go", "go include"]):
        return "upgrade"

    # ── Due date / reminders (check before customer) ──────────────────────────
    if any(k in q for k in [
        "due date", "payment due", "set reminder", "remind customer",
        "when to pay", "debt reminder", "payment reminder",
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

    # ── Supplier (before generic stock) ──────────────────────────────────────
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
        "inventory", "stock list", "how much stock", "quantity left",
    ]):
        return "check_stock"
    if "stock" in q and any(k in q for k in ["check", "view", "see", "list", "show", "left", "remaining"]):
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

    # ── Check balance / what a customer owes ──────────────────────────────────
    if any(k in q for k in [
        "customer balance", "what does balance", "what is balance",
        "customer owe", "how much owe", "check debt", "see what customer",
        "customer account", "outstanding balance",
    ]):
        return "check_balance"
    if "balance" in q and any(k in q for k in ["what", "how", "check", "see", "view", "mean"]):
        return "check_balance"
    if re.search(r"\bowes?\b", q):
        return "check_balance"

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
        "Ade account\n\n"
        "Balance = total charged minus what they have paid.\n"
        "tiTi tracks this with every sale and payment you record."
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
    "add_supplier": (
        "How to record a supplier purchase:\n\n"
        "Ayo supply me 10 bags rice at 5000 each\n"
        "I buy 12 liters oil from Ayo at 3000\n\n"
        "To record payment to supplier:\n"
        "I paid Ayo 14000 for rice\n\n"
        "To see all suppliers:\n"
        "suppliers"
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
        "tiTi will remind the customer when the balance is due."
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
    "formats": (
        "Send this to see all examples and commands:\n\n"
        "formats"
    ),
}


def get_faq_answer(key):
    return FAQ_ANSWERS.get(key, FAQ_ANSWERS["formats"])
