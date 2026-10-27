"""
Keyword FAQ for CreditVoice.

detect_faq(text) -> key | None
get_faq_answer(key) -> str
"""
import re

# ── Detection ─────────────────────────────────────────────────────────────────

_QUESTION_STARTERS = (
    "how", "what", "whats", "what's", "where", "when", "why", "which", "who",
    "can i", "can you", "can we", "can the", "could i", "could you",
    "do i", "do you", "does", "is there", "are there", "is it", "is my",
    "show me", "tell me", "help me", "help with", "i don't know", "i dont know",
    "teach me", "explain", "check", "list of", "want to", "i want", "i need to",
    "way to", "any way", "please",
)

# Broader help/how-to phrasings anywhere in the message — so we recognise a
# question even when it doesn't start with a classic question word.
_HELP_PATTERNS = re.compile(
    r"\b("
    r"how\s+(do|to|can|should|would|does)|"
    r"tell me (about|how)|"
    r"is it possible|is there (a )?way|any way to|way to|"
    r"do you (support|have|allow|let me)|does (the app|titi|it)|"
    r"can (the app|titi|i|you|we)|"
    r"what('?s| is| are)?\s+(the )?(way|process|steps?|option|options)\b|"
    r"where (do|can|is|are)|"
    r"i want to (know|learn|understand|see|find)|"
    r"walk me through|guide me|"
    r"made a mistake|by mistake|entered (it |the )?wrong|recorded (it |the )?wrong|"
    r"explain|show me how"
    r")\b",
    re.I,
)


def _is_question(text):
    q = text.lower().strip()
    if "?" in q:
        return True
    if any(q.startswith(s) for s in _QUESTION_STARTERS):
        return True
    if _HELP_PATTERNS.search(q):
        return True
    return False


_WHERE = re.compile(r"\b(where (?:is|are|can i find|do i find|do i see)|i can'?t find|cant find|can'?t see|how do i find|how do i get to|where'?s)\b")


def _where_is(q):
    """'Where is expenses?' → the nav-guide answer for that screen."""
    if not _WHERE.search(q):
        return None
    from nav_guide import NAV_GUIDE
    for route, entry in NAV_GUIDE.items():
        names = [entry["name"]] + [n.strip() for n in (entry.get("also") or "").split(",")]
        for n in names:
            core = re.sub(r"\s*\(.*?\)", "", n).strip().lower()
            if core and len(core) > 2 and core in q:
                return f"where:{route}"
    if "till" in q or "pos" in q.split():
        return "where:/pos"
    return None


def detect_faq(text):
    q = text.lower().strip()

    # ── Business name / profile change — HIGH PRIORITY ────────────────────────
    # Handled before the question gate (so statements like "my business name is
    # wrong" are caught) and before generic matchers (so "edit my business name"
    # isn't grabbed by the stock matcher). Scoped to the business/shop name, not
    # customer/product names.
    if (
        re.search(r"\b(business|shop|store|company)\s+name\b", q)
        or re.search(r"\b(rename|re-?name)\s+(my\s+|the\s+)?(business|shop|store|company)\b", q)
        or re.search(r"\b(change|update|edit|correct|fix)\s+(my\s+|the\s+)?(business|shop|store|company)\b(?!\s+(type|category))", q)
        or ("receipt" in q and "name" in q and "wrong" in q)
    ):
        return "change_name"

    # ── Referral / refer a friend — HIGH PRIORITY ────────────────────────────
    # Answered before the question gate so plain statements ("I want to refer my
    # friend", "refer people") are caught too. Scoped tightly to referral intent
    # so it never steals staff/partner invites ("invite staff", "invite partner").
    if (
        "referral" in q
        or "refer a friend" in q or "refer my friend" in q or "refer friend" in q
        or "refer people" in q or "refer someone" in q or "refer somebody" in q
        or "refer others" in q or "refer my friends" in q
        or re.search(r"\b(want to|wanna|like to|how (do i|to|can i)|can i|help me|let me)\s+refer\b", q)
        or "invite a friend" in q or "invite my friend" in q or "invite friends" in q
        or "invite people" in q or "invite my friends" in q
        or "invite bonus" in q or "invite reward" in q or "cashback" in q
    ):
        return "referral"

    # A forgotten PIN is said as a statement ("i forgot my pin"), not a question.
    if any(k in q for k in ["forgot my pin", "forgot pin", "forget my pin", "forgotten my pin"]):
        return "pin_help"

    if not _is_question(text):
        return None

    # ── Newer features — before "receipt", which takes any mention of it ─────
    if any(k in q for k in [
        "fake", "counterfeit", "original", "genuine", "authentic",
        "adulterated", "substandard",
    ]):
        return "fake_product"
    # "How much do I owe my suppliers?" — not a customer's balance.
    if re.search(r"\bowe\b.*\bsuppliers?\b|\bsuppliers?\b.*\b(?:owe|debt|balance)\b", q):
        return "supplier_owed"
    if any(k in q for k in [
        "expense", "rent and salar", "salary", "salaries", "money i spent",
        "spent on transport", "running cost", "net profit",
    ]):
        return "expenses"
    if any(k in q for k in ["change my pin", "forgot my pin", "forgot pin", "forget my pin",
                            "reset pin", "reset my pin", "new pin"]):
        return "pin_help"
    if any(k in q for k in ["pay with card", "card payment", "pay by card", "pay online"]):
        return "upgrade"
    if any(k in q for k in ["school fee", "school fees", "pupil", "student fee", "term fee"]):
        return "school_fees"
    if any(k in q for k in ["egg", "feed used", "poultry", "layers", "broiler"]):
        return "poultry"
    if any(k in q for k in ["fuel sale", "fuel sales", "pump", "litre", "liter", "meter reading", "filling station"]):
        return "fuel_station"
    where = _where_is(q)
    if where:
        return where
    if any(k in q for k in ("loyalty", "loyal customer", "reward my customer", "reward customers", "reward loyal",
                            "customer reward", "stamp card", "loyalty card", "customer points", "loyalty points",
                            "use points", "use reward", "buy 10 get", "buy ten get", "best customers",
                            "top customers", "cashback", "cash back for customers")):
        return "loyalty"
    if re.search(r"\bdiscount", q):
        return "discount"
    if any(k in q for k in [
        "barcode", "bar code", "scanner", "scan product", "scan item", "scan with",
        "scan the", "camera scan", "use my camera", "use the camera", "phone camera",
    ]) or re.search(r"\bscan(ning)?\b", q):
        return "barcode_scan"
    if any(k in q for k in [
        "write a review", "my review", "leave a review", "give a review", "testimonial",
        "free advert", "advertise my business", "homepage", "home page",
        "feature my business", "show my business on",
    ]):
        return "site_review"
    if any(k in q for k in [
        "verified supplier", "supplier directory", "become a supplier", "be a supplier",
        "list my business as", "find a supplier", "find supplier", "find suppliers",
        "connect with supplier", "connect with a supplier", "wholesaler near",
        "rate supplier", "rate a supplier", "supplier rating",
    ]):
        return "supplier_directory"
    if any(k in q for k in [
        "scorecard", "score card", "business score", "credit score", "my score",
        "finance offer", "asset financ", "financing", "financier",
        "repayment", "buy on credit from a financier", "loan for",
    ]):
        return "finance_scorecard"

    # ── Quotations / deposit before work; the business logo ──────────────────
    if any(k in q for k in ("quotation", "quote ", "a quote", "give quote", "send quote", "estimate for",
                            "deposit before", "before work starts", "before starting work", "mobilization",
                            "mobilisation", "advance payment", "balance on completion", "balance after")):
        return "quotation"
    if re.search(r"\blogo\b", q):
        return "logo"

    # ── Settings: display, categories, daily summary ──────────────────────────
    if any(k in q for k in ("setting", "font", "text size", "text bigger", "bigger text", "bigger letters",
                            "letters bigger", "increase the text", "make the text", "zoom", "dark mode",
                            "dark theme", "night mode", "light mode", "group my stock", "group stock",
                            "group products", "stock by category", "products by category",
                            "product categor", "stock categor", "manage categor", "daily summary", "summary every day",
                            "sell below zero", "negative stock", "compact")):
        return "settings"

    # ── Already in stock? / duplicates ────────────────────────────────────────
    if any(k in q for k in ("already in my stock", "already in stock", "already added", "added before",
                            "entered before", "added it before", "add it twice", "added twice",
                            "entered twice", "duplicate", "same product twice", "not sure if i added",
                            "missing from my stock", "missing from stock", "missing in my inventory",
                            "can't find a product", "cant find a product", "can't find my product",
                            "cant find my product", "product is missing", "stock is missing")):
        return "already_in_stock"

    # ── Part delivery, cancel / refund, returns — before "receipt" and
    #    "deliveries", which would take any mention of them ─────────────────────
    refund_words = ("refund", "money back", "credit note", "cancel the rest", "cancel the remaining",
                    "cancel undelivered", "cancel the undelivered", "called off", "doesn't want the rest",
                    "does not want the rest", "no longer want")
    if any(k in q for k in ("returned goods", "return goods", "goods returned", "brought back",
                            "bring back", "returned the", "return the goods", "customer returned",
                            "take back", "damaged goods returned", "returned damaged")):
        return "return_goods"
    if any(k in q for k in refund_words):
        return "cancel_refund"
    if any(k in q for k in ("pay link", "payment link", "link to pay", "pay online", "pay by transfer", "paid by transfer", "confirm payment", "confirm a payment", "payments to confirm", "says he paid", "says she paid", "said he paid", "said she paid", "says they paid", "i've paid button", "i have paid button")):
        return "pay_link"
    if any(k in q for k in ("expiry", "expiries", "expire", "expired", "expiring", "expiration", "batch number", "batch no", "nafdac number", "write off", "write-off", "sell first")) and "subscription" not in q and "plan" not in q \
            and "code" not in q:
        return "expiry"
    if any(k in q for k in ("out of stock", "stock out", "stock-out", "no stock", "zero stock", "stock is finished", "stock finished", "stock is finish", "stock has finished", "finished stock", "says out of stock", "saying stock out", "when stock is 0", "when stock is zero")) and any(
            k in q for k in ("sell", "sale", "how", "can i", "what do i", "customer")):
        return "sell_out_of_stock"
    if re.search(r"\bvat\b|value added tax|\btin\b|tax on (my )?(sales|invoice|receipt)", q) \
            and "filing" not in q:
        return "vat"
    if any(k in q for k in ('repeat invoice', 'repeating invoice', 'recurring invoice', 'recurring bill', 'invoice every', 'bill every', 'bill monthly', 'monthly invoice', 'weekly invoice', 'same invoice every', 'bill a tenant', 'bill my tenant', 'bill my tenants', 'invoice automatically', 'automatic invoice', 'auto invoice', 'make it repeat')):
        return "repeat_invoice"
    if any(k in q for k in ("appointment", "appointments", "book a customer", "book customers", "book my customer", "booking", "bookings", "schedule a customer", "schedule customers")):
        return "appointment"
    if any(k in q for k in ("purchase order", "purchase orders", "order from supplier", "order from my supplier", "order goods from", "order stock", "reorder", "re-order", "place an order", "order more stock")):
        return "purchase_order"
    if any(k in q for k in ("stock count", "stocktake", "stock take", "stock-take", "count my stock",
                            "count stock", "count my shelves", "count my goods", "stock is wrong",
                            "stock not correct", "stock is not correct", "stock loss", "stock lost",
                            "missing goods", "blind count", "approve count", "approve the count")):
        return "stock_count"
    if any(k in q for k in ("waybill", "way bill", "way-bill", "loading order", "loading list",
                            "keep aside", "kept aside", "keep goods aside", "sell more than",
                            "sold more than", "selling more than", "more than i have",
                            "more than is in store", "customers still waiting")):
        return "waybill"
    if any(k in q for k in ("part delivery", "partly delivered", "partially delivered", "part delivered",
                            "not all delivered", "not all the goods", "deliver later", "deliver the rest",
                            "remaining to deliver", "yet to be delivered", "yet to deliver", "still to deliver",
                            "goods to deliver", "reserved stock", "reserved goods", "deliver part",
                            "collect later", "collect the rest", "balance of goods", "deliver in batches")) \
            or re.search(r"\bonly\s+\d+\s+(?:\w+\s+)?(?:was\s+|were\s+|got\s+|have\s+been\s+)?delivered\b", q):
        return "part_delivery"

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

    # ── Change business name / profile / address ─────────────────────────────
    if any(k in q for k in [
        "change name", "rename business", "update name", "change my name",
        "update business name", "change business name", "rename my business",
        "business name", "shop name", "my name", "store name",
        "change profile", "update profile", "change my business type",
        "business type", "edit profile", "edit my name", "wrong name", "fix my name",
        "my profile", "update my details", "edit my details", "my details",
        "business address", "shop address", "store address", "my address",
        "add my address", "set my address", "change my address",
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

    # ── Void / undo / remove / correct a transaction ──────────────────────────
    # Flexible: any remove/undo verb applied to a transaction/sale/entry/payment,
    # so "how to remove a transaction" and "delete a sale" both match.
    if re.search(r"\bvoid\b", q) and any(k in q for k in ["how", "what", "transaction", "sale", "last", "entry", "payment"]):
        return "void_transaction"
    if any(v in q for v in ["undo", "cancel", "reverse", "correct", "delete", "remove", "wrong", "mistake"]) \
       and any(n in q for n in ["transaction", "sale", "entry", "payment", "record", "last"]):
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
        "multiple shop", "multiple store", "more than one shop", "several shops",
        "many shops", "multiple location", "multiple outlet", "different location",
        "second shop", "another shop", "other shops",
    ]):
        return "branch_location"
    if any(w in q for w in ["shop", "store", "outlet", "location", "branch"]) and \
       any(k in q for k in ["multiple", "more", "another", "several", "many", "different", "second", "each"]):
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
        "multiple user", "more users", "other user", "many users",
        "add worker", "add employee", "my worker", "my employee", "my team",
        "team member", "salesperson", "sales person", "cashier account",
    ]):
        return "staff_accounts"
    if "staff" in q and any(k in q for k in ["how", "add", "invite", "access", "what"]):
        return "staff_accounts"
    if any(w in q for w in ["worker", "employee", "assistant", "cashier", "salesperson", "sales person", "team member"]) and \
       any(k in q for k in ["add", "invite", "another", "more", "access", "give", "can", "how", "new", "record"]):
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
        "low stock", "stock is low", "running low", "out of stock",
        "reorder", "need to restock", "restock alert",
    ]):
        return "check_stock"
    if "stock" in q and any(k in q for k in ["check", "view", "see", "list", "show", "left", "remaining"]):
        return "check_stock"
    if "inventory" in q and any(k in q for k in ["check", "view", "see", "show", "list"]):
        return "check_stock"

    # ── Dashboard / reports (before record_sale) ──────────────────────────────
    if any(k in q for k in [
        "dashboard", "sales report", "see report", "daily report",
        "sales today", "today sales", "todays sales", "today's sales",
        "daily sales", "weekly sales", "monthly sales",
        "how much i made", "how much did i make",
        "total sales", "my sales", "profit", "how much have i",
    ]):
        return "dashboard"
    if "report" in q and any(k in q for k in ["how", "see", "check", "view", "get"]):
        return "dashboard"
    if "sales" in q and any(k in q for k in ["today", "daily", "yesterday", "this week", "this month", "weekly", "monthly"]):
        return "dashboard"

    # ── Record a payment ──────────────────────────────────────────────────────
    if any(k in q for k in [
        "record payment", "record a payment", "customer paid",
        "paid me", "mark as paid", "payment received", "collect payment",
        "record that he paid", "record that she paid",
        "part payment", "partial payment", "paid part", "paid some", "part of the money",
        "balance later", "pay small small", "pay the rest later", "pays the rest later",
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
        "update price", "change price", "update prices", "update my price",
        "change my price", "edit price", "adjust price",
        "remove item", "remove an item", "remove product", "delete product",
        "delete item", "remove stock", "delete stock",
    ]):
        return "add_stock"
    if "product" in q and any(k in q for k in ["add", "create", "set up", "new", "how", "remove", "delete", "edit"]):
        return "add_stock"
    if "stock" in q and any(k in q for k in ["add", "create", "new", "put", "enter", "remove", "delete"]):
        return "add_stock"
    if "price" in q and any(k in q for k in ["update", "change", "set", "edit", "adjust", "how"]):
        return "add_stock"

    # ── Redeem a plan/token code ──────────────────────────────────────────────
    if any(k in q for k in [
        "redeem", "redeem code", "redeem a code", "plan code", "token code",
        "activation code", "activate code", "activate my plan", "enter code",
        "have a code", "got a code", "coupon", "voucher",
    ]):
        return "redeem_code"

    # ── Referral / invite bonus ───────────────────────────────────────────────
    if any(k in q for k in [
        "referral", "referral bonus", "referral code", "invite bonus",
        "refer a friend", "invite a friend", "invite friends", "cashback",
        "invite reward", "referral reward", "my invite code",
    ]):
        return "referral"

    # ── Opportunities ─────────────────────────────────────────────────────────
    if any(k in q for k in [
        "opportunities", "opportunity", "loan offer", "grant", "offers for me",
        "apply for loan", "funding", "financing offer",
    ]):
        return "opportunities"

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
    "quotation": (
        "Quotations are for businesses that do jobs (contractors, artisans, tailors, mechanics, "
        "printers, consultants). Web app → *Invoices* → *New quotation*.\n\n"
        "1. Add the job's items and prices, and who it's for.\n"
        "2. *Deposit before work starts* — e.g. 60%. The quotation shows the deposit and the "
        "*balance on completion*.\n"
        "3. Set the completion date (when the balance is due), then send it on WhatsApp or print it.\n\n"
        "Nothing is owed while it's a quotation. When the customer agrees, tap *Customer accepted* — "
        "it becomes an invoice (INV number) with no retyping.\n"
        "Then *Record deposit / payment* → *Deposit*: it shows *Deposit paid — work can start*, and the "
        "balance goes on their debts, due on the completion date, with reminders like any debt."
    ),
    "logo": (
        "To put your logo on receipts, invoices and quotations: web app → *My Profile* → "
        "*Business logo* → *Upload logo* (owner only). A square PNG or JPG works best.\n\n"
        "It prints at the top of every receipt and invoice you view, print or download. WhatsApp "
        "text receipts can't carry a picture, so they stay as text."
    ),
    "settings": (
        "Web app → Menu → More → *Settings*.\n\n"
        "*My display* (just for you, on every device):\n"
        "• *Text size* — Small, Normal, Large, Extra large\n"
        "• *Theme* — Light, Dark, or Follow my phone\n"
        "• *List style* — Compact (more rows) or Comfortable (bigger rows)\n"
        "• *Phone camera scanning* — Tap to scan (one barcode, then the camera closes), Keep "
        "scanning, or *From a photo* (your phone's own Camera app takes the picture — safest for "
        "phones that switch off when scanning)\n\n"
        "*Stock* (owner and authorised staff, for the whole business):\n"
        "• *Group stock by category* — products shown in groups (Drinks, Provisions…) on "
        "Inventory, and on *{till}* if you choose\n"
        "• *New categories come from* — you type them, or tiTi suggests from the product name\n"
        "• *Low-stock alert for new products*\n"
        "• *Allow selling below zero stock* — Yes or No\n"
        "• *Show \"Not all goods delivered now\" when selling*\n\n"
        "*Manage categories* — rename, reorder, put many products into a category at once, or "
        "let tiTi suggest categories for products that have none.\n\n"
        "*WhatsApp* — a *daily summary* of the day's sales at the time you pick."
    ),
    "already_in_stock": (
        "Not sure a product is already in your stock? Don't add it again — check first:\n\n"
        "*Ask me* on WhatsApp: *do I have paracetamol?* (or *is groundnut oil in my stock?*)\n"
        "I check every product, allowing for spelling, spacing and plurals — 'paracetemol', "
        "'g/nut oil' and 'indomie noodle 70 g' still find them — and tell you:\n"
        "• *Yes* — the name it's under and how many are left\n"
        "• *Close* — products that look like it, so you can pick the right one\n"
        "• *No* — nothing like it in all your products, so it's safe to add\n\n"
        "*On the web app* → Inventory:\n"
        "• *Search* shows \"did you mean…\" close matches when nothing is spelt the same.\n"
        "• *Add Product* warns \"You may already have this\" while you type the name, with "
        "*Use this one*. The exact same product can't be saved twice.\n"
        "• *Check duplicates* lists products that look entered twice, so you can keep one.\n\n"
        "Or send me: *check duplicates*"
    ),
    "part_delivery": (
        "When a customer buys goods but takes only part now (e.g. 100 bags sold, 60 delivered):\n\n"
        "*1. Record the sale* — web app → *{till}*\n"
        "• Add the items and pick the customer (needed — the rest is kept for them).\n"
        "• Tick *Not all goods delivered now* and enter how many went out (e.g. 60 of 100).\n"
        "• Only those leave stock. The rest stays in your store, *kept aside* for the customer "
        "(Settings → *Keep goods aside for customers who have not collected*).\n\n"
        "*2. Your stock* — *Inventory* shows *In store / Kept aside for customers / Can sell / "
        "Customers still waiting*.\n"
        "Can sell = in store − kept aside, and nobody can sell kept-aside goods by mistake.\n\n"
        "*3. Deliver the rest later* — *Deliveries* → *Goods to deliver* → *Waybill* "
        "(also on the customer's page).\n"
        "• Tick how many go on this trip, and add the driver, vehicle and loaders.\n"
        "• Stock goes down then, and the customer gets a WhatsApp note: "
        "what is on its way · still to deliver.\n\n"
        "More sales to the same customer add to what they're waiting for. Their receipt and "
        "statement show it too.\n\n"
        "Customer cancels the rest? Ask me: *how do I refund undelivered goods*"
    ),
    "pay_link": (
        "💳 *Pay links — customers pay by transfer and tell you*\n\n"
        "*1. Add your bank account* — web app → *My Profile* → Bank account for payments.\n"
        "*2. The link goes out by itself* in invoices, receipts with a balance, and balance messages: "
        "_Paid? Tell us here: creditvoiceai.com/app/pay/…_\n"
        "*3. The customer taps it* — no app or account needed. They see your business, the amount and "
        "your bank account (with a Copy button), transfer, then tap *I've paid* (a photo of the transfer "
        "is optional). They can also just reply *PAID* to your message on WhatsApp.\n"
        "*4. You're alerted* — check your bank, then open *Payments to confirm* and tap *Confirm — money "
        "is in* (change the amount if less arrived). It's recorded and the customer gets a receipt. If it "
        "didn't arrive, tap *Not received* and say why — they're told.\n\n"
        "Nothing is recorded until you confirm, and the money goes straight to your bank — the app never "
        "holds it. Only the owner or authorised staff can confirm.\n"
        "On an invoice, *Copy pay link* gives you the link to send yourself."
    ),
    "expiry": (
        "⏳ *Expiry dates — sell first, don't sell expired*\n\n"
        "*1. Add the date when stock arrives* — *{record}* → Stock tab, or Inventory → a product → "
        "Adjust → add: fill *Expiry date* (and batch / NAFDAC no. if you like). Each delivery keeps its "
        "own date.\n"
        "*2. tiTi works out what's still on the shelf* — the oldest goods are taken as sold first, so "
        "it knows e.g. 12 of your 40 packs expire in March.\n"
        "*3. You're warned* — once a day I tell you what has expired or expires soon (30 days, or what "
        "you set in Settings → Stock → *Warn me before goods expire*). Inventory marks them too: "
        "☠ expired, ⏳ expiring.\n"
        "*4. At the till* — selling a product with expired stock shows a warning (it never blocks you).\n"
        "*5. Throw away expired goods* — Inventory → *Expiry* → *Write off expired*. They leave stock "
        "and show as a loss in Stock count → Last 30 days.\n\n"
        "On WhatsApp you can still set one date for a product from its stock menu (MM/YYYY)."
    ),
    "sell_out_of_stock": (
        "📦 *Selling something that shows Out of stock*\n\n"
        "*Best:* if the goods are really on your shelf, your stock record is behind — add the stock "
        "first (*{record}* → Stock tab, or Inventory → the product → Adjust → add), then sell as usual.\n\n"
        "*Selling it anyway* — Settings → Stock → *Allow selling more than you have in store*:\n"
        "• *Yes* (switch it on yourself): on *{till}* you can still tap it.\n"
        "   – To a *named customer*: the sale is recorded, and what isn't in store is kept as *still to "
        "deliver* for them — make a waybill from Deliveries when new stock arrives.\n"
        "   – To a *walk-in*: it just sells; stock stays at 0.\n"
        "• *No* (the default): the till won't let you sell it until you add stock.\n\n"
        "Ask me _how do I add stock_ or _what is a waybill_ for more."
    ),
    "vat": (
        "🧾 *VAT — only if you charge it*\n\n"
        "VAT is *off* until you turn it on: Settings → *VAT* → *I charge VAT* → Yes. Then choose:\n"
        "• *Add VAT on top* — your prices are before VAT: ₦10,000 + VAT 7.5% (₦750) = ₦10,750.\n"
        "• *Already include VAT* — a ₦10,750 price stays ₦10,750; the receipt shows the VAT inside it.\n\n"
        "Set the rate (7.5% in Nigeria) and your TIN / VAT number — it's printed on receipts, invoices "
        "and quotations.\n\n"
        "*Products with no VAT* (basic food, medicines, school fees…): Inventory → the product → edit → "
        "tick *No VAT on this product*.\n\n"
        "Sales on *{till}* and invoices then show Subtotal · VAT · Total, and Settings → VAT shows *VAT "
        "collected* this month and last — what you'll file. An invoice keeps the VAT it was written "
        "with, even if you change the setting later."
    ),
    "loyalty": (
        "⭐ *Loyalty — reward customers who come back*\n\n"
        "*1. Switch it on* — *Settings → Loyalty* and pick one: "
        "*Stamp card* (buy 10, get the next one free — you choose the number) or *Points* (₦1 back for every ₦100 spent — you choose how much).\n"
        "You can also choose which products count, and whether rewards expire.\n"
        "*2. Sell as usual* — choose the customer's name when you sell. Every paid sale earns; a credit sale "
        "earns once the debt is cleared. Customers see their stamps or points on their WhatsApp receipt.\n"
        "*3. Use the reward* — at {till}, choose the customer: it shows their stamps or points. Tick "
        "*Use reward* (the cheapest item that counts comes off) or *Use points* (they come off the total)."
        "\n\n"
        "A voided sale takes its reward back. Walk-in sales with no name earn nothing. "
        "*Customers → Best* shows who spends most, and their rewards."
    ),
    "repeat_invoice": (
        "🔁 *Repeat invoices — bill the same customer again on a schedule*\n\n"
        "For rent, service charges, a weekly supply — anything you bill the same way again and again."
        "\n\n"
        "*1. Set it up* — open the invoice (Invoices → the invoice) → *Make it repeat*: how often (every week, "
        "month, 3 months or year), the first date, and when to stop (never, after a number, or on a date).\n"
        "*2. Choose how it goes out* — *Send it for me*: on each date a new invoice (new INV number, same items "
        "and prices) goes to the customer's WhatsApp with the pay link, and you get a note. *Let me check first*: "
        "it's made but not sent — you get a note to check it and tap *Send to customer*.\n"
        "*3. Manage them* — Invoices → *Repeating*: see the next date and how many were made; *Change* (new "
        "price, new date), *Pause*, *Resume* or *Stop*. Invoices already made stay as they are.\n\n"
        "Each one is an ordinary invoice: nothing is owed until it's paid or delivered, same as always. "
        "Schools don't need it — opening a term already bills every pupil."
    ),
    "appointment": (
        "📅 *Appointments — book customers for a time*\n\n"
        "*1. Book* — web app → *Appointments* → *Book*: the customer, the service(s) from your price "
        "list, the date and time, how long it takes, who will do it, and a note.\n"
        "If the same staff already has someone at that time, tiTi warns you (it still saves).\n"
        "*2. On the day* — the list shows today's bookings; ← → for other days. Tap *Arrived* when "
        "they come, *Change* to move it, *No-show* or *Cancel*. No-shows are counted per customer.\n"
        "*3. Done* — tap *Done*: check the services and price, enter what they paid. It's recorded as a "
        "sale with a receipt sent on WhatsApp; anything unpaid becomes their debt.\n\n"
        "*Reminders* — the customer gets a WhatsApp reminder the evening before, and you get the day's "
        "list each morning.\n"
        "*Booking link* — customers can book themselves: *Settings → Appointments* → switch on "
        "*Customers can book from a link* and set your opening hours. Then *Appointments → Booking link* "
        "→ copy it or send on WhatsApp. They pick a service, a day and a free time; it waits under "
        "*Asking to book* until you tap *Confirm* or *Decline* (or choose *Book straight away*).\n"
        "Shown in the menu for service businesses. Anyone else: *Settings → Appointments → Show*."
    ),
    "purchase_order": (
        "📦 *Purchase orders — order from your supplier before goods come*\n\n"
        "*1. Write it* — web app → *Purchase orders* (or Suppliers → Purchase orders) → *New order*: "
        "the supplier, the products, how many and the cost of each, and a deliver-by date. It gets a "
        "number (PO-0001). *Running low* lists products to reorder by supplier — tap *Order from …* "
        "and it's filled in.\n"
        "*2. Send it* — *Send to supplier* sends it on WhatsApp, or *Download / Print*.\n"
        "Nothing is owed and no stock moves yet.\n"
        "*3. When goods arrive* — open the order → *Goods arrived*: enter how many of each came (and an "
        "expiry date / batch if you like) and what you paid. They go into stock and onto the supplier's "
        "account, owed or paid.\n"
        "*4. Part deliveries* — what hasn't come shows as *still expected*. If the rest won't come, "
        "*Close order* — what never arrived stays on record.\n\n"
        "Owner and authorised staff only, like other stock changes."
    ),
    "stock_count": (
        "📋 *Stock count — when your stock in the app doesn't match the shelf*\n\n"
        "*1. Start* — web app → *Inventory* → *Count stock* → *Start a count* "
        "(all products, or one category).\n"
        "*2. Count* — walk the shelves and type what is really there. The app's numbers are hidden "
        "(a *blind count*), so you count instead of copying. Leave a box empty to skip a product. "
        "It saves as you go.\n"
        "*3. Send for approval* — staff counts go to the owner. Nothing in stock changes yet.\n"
        "*4. Approve* (owner or authorised staff) — you see app vs counted, the difference and what "
        "it's worth at cost. Pick why for each one: *counted wrong before · damaged · expired · "
        "stolen/missing · found extra*. Tap *Approve* and stock is fixed.\n\n"
        "Sales made while the count waited are kept — stock moves by the difference only.\n"
        "Each count gets a number (SC-0001) you can print and sign. *Stock count* shows what you lost "
        "in the last 30 days, by reason.\n\n"
        "Want counters to see the app's numbers? Settings → Stock → *hide the app's numbers while "
        "counting* → Show.\n\n"
        "On WhatsApp, to fix one product: _set stock rice 50 bags_"
    ),
    "waybill": (
        "A *waybill* (loading order) is the paper the loaders and driver take with the goods — "
        "no prices, signed on arrival.\n\n"
        "*Make one* — web app:\n"
        "• From a receipt or an invoice → *Waybill*, or\n"
        "• *Deliveries* → *Goods to deliver* → *Waybill* (everything a customer is still waiting for).\n"
        "Tick each item and how many go on this trip, add the driver, phone, vehicle no., loaders and "
        "address → *Make waybill*. Then *Download / Print* or *Share*.\n\n"
        "*Stock*: goods still to deliver leave stock when the waybill is made — only what is in the "
        "store for that customer. Printing it again never takes them twice. Goods already handed over "
        "at the sale are just listed.\n\n"
        "*Selling more than you have in store*: with Settings → *Allow selling more than you have in "
        "store* = Yes, a sale to a named customer goes through and the rest is kept as *still to deliver* "
        "for them; a walk-in sale just sells (stock stops at 0). Customer took it all because your stock "
        "count was low? Add the missing stock first. With No, the sale is refused.\n\n"
        "*New stock arrives*: after adding stock I show the customers still waiting — tick to *keep goods "
        "aside* for them, or leave it free to sell. Deliveries → *Keep aside* does the same any time.\n\n"
        "*Cancel a waybill* (owner or authorised staff): the goods go back into the store and back on "
        "the customer's still-to-deliver list."
    ),
    "cancel_refund": (
        "When goods a customer bought were *not delivered* and are called off or refunded:\n\n"
        "Web app → *Deliveries* → *Goods to deliver* → *Cancel / refund* "
        "(or the customer's page → *To deliver*).\n\n"
        "1. Enter how many to cancel.\n"
        "2. Choose the money:\n"
        "   • *Take it off what they owe* — they hadn't paid for them\n"
        "   • *Give the money back* — they had paid; this records the cash you hand back\n"
        "3. Write the reason (kept in case of a dispute) → *Issue credit note*.\n\n"
        "What happens:\n"
        "• The goods never left your store, so they become *available to sell again* at once.\n"
        "• A numbered *credit note* (CN-0001) is made. The original sale is never changed — its "
        "receipt shows what was sold, what was delivered and the credit note after it.\n"
        "• The customer gets the credit note on WhatsApp: bought · delivered · cancelled · refunded.\n"
        "• Sales and profit count only what was really sold.\n\n"
        "Only the owner or authorised staff can do this, and the owner is alerted when staff do.\n"
        "Goods that were delivered and came back? Ask me: *how do I take back returned goods*"
    ),
    "return_goods": (
        "When delivered goods are brought back:\n\n"
        "Web app → *Receipts* → open the sale → *Return goods*.\n\n"
        "1. Enter how many of each item came back.\n"
        "2. Say whether they *can be sold again* (they go back into stock) or are *damaged* "
        "(they stay out of stock).\n"
        "3. Choose the money: *take it off what they owe* or *give the money back*.\n"
        "4. Write the reason → *Issue credit note*.\n\n"
        "A numbered credit note (CN-0001) records it; the sale itself is not changed. The customer "
        "gets a copy on WhatsApp, and it shows on the sale's receipt and their statement. A refund "
        "follows any discount given, so you never give back more than was paid.\n\n"
        "Only the owner or authorised staff can do this. Recorded it by mistake? Void the credit "
        "note (Transactions → Void) and everything goes back as it was."
    ),
    "delivery_date": (
        "To set when a job/order will be ready and be reminded:\n\n"
        "1. Record the sale on the web app → *{till}*.\n"
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
    # add_stock, record_sale → merged into build_app_guide_message (single source).
    "record_payment": (
        "💵 *Recording a payment or part payment*\n\n"
        "*1. Customer pays part now, the rest later* — web app → *{till}*\n"
        "• Tap what they're buying, then pick or add the customer.\n"
        "• In *Payment Received*, type what they paid now (e.g. 5,000 of 20,000).\n"
        "• Tap *Save Sale*. The rest becomes their debt; you can set a due date.\n\n"
        "*2. Customer pays some of what they already owe*\n"
        "• *Customers* → tap *Pay* beside their name, enter the amount, or\n"
        "• *{record}* → *Payment* tab, pick the customer, enter the amount.\n\n"
        "*3. On WhatsApp* — just type it:\n"
        "• _Ade paid 5000_ — part of his debt\n"
        "• _Ade bought rice 20000 paid 5000_ — a sale with part payment\n\n"
        "tiTi updates the balance automatically and sends the customer a receipt."
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
    # add_supplier → merged into build_app_guide_message (single source).
    "check_stock": (
        "To see your current stock:\n\n"
        "stock\n\n"
        "To check a specific product:\n"
        "stock honey\n"
        "stock rice"
    ),
    # add_customer, dashboard → merged into build_app_guide_message (single source).
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
        "To upgrade, send  upgrade  here, or on the web app: Menu → More → Upgrade Plan.\n\n"
        "Plans:\n"
        "- GO: unlimited stock, exports, multi-item sales, voice, automatic reminders\n"
        "- PRO: GO + staff accounts, branches, 1 partner and 1 investor\n"
        "- PREMIUM: PRO with unlimited branches, partners and investors\n\n"
        "Pay by card (your plan switches on at once) or bank transfer (switches on "
        "once we confirm it). Have a plan code? Enter it on the Upgrade page.\n\n"
        "Send  my plan  to see your current plan."
    ),
    "discount": (
        "Giving a discount:\n\n"
        "*Web app — the till (Select product), New Receipt or an invoice:*\n"
        "Under the items there's a *Discount* box. Tap *₦* to take off an amount, "
        "or *%* for a percentage. The total, payment and any debt use the discounted "
        "total, and the receipt shows Subtotal and Discount so it adds up.\n\n"
        "*WhatsApp:* while selling with  select product , send\n"
        "discount 500   or   discount 10%\n\n"
        "Selling one item below its price also counts as a discount.\n\n"
        "To see how much you've given away: Dashboard → *Discounts given*."
    ),
    "supplier_owed": (
        "What you owe your suppliers:\n\n"
        "*Dashboard* — the red *You owe suppliers* card shows the total (owner and "
        "authorised staff).\n"
        "*Menu → More → Suppliers* — each supplier's balance in red, and each "
        "purchase's *Remaining* until it's paid.\n\n"
        "To pay: open the supplier → *Pay*. Payments clear the oldest purchases first.\n"
        "When you receive stock, leave *Amount paid now* empty if you bought on credit — "
        "it's then owed, in red, until you pay."
    ),
    "expenses": (
        "Recording expenses (rent, salaries, transport, fuel, electricity…):\n\n"
        "Web app → Menu → More → *Expenses* → *Add expense* — amount, type, the date you "
        "spent it and a note.\n\n"
        "Staff share what they spent as a *Note* (category Expense, with the amount). It "
        "waits in Expenses → *To review* until you approve it.\n\n"
        "Approved expenses come off your gross profit: the Dashboard shows your *net profit*.\n"
        "Buying stock is not an expense — record it with Add or Adjust stock."
    ),
    "pin_help": (
        "Your PIN:\n\n"
        "*Forgot it?* On the login page tap *Forgot PIN*, enter your phone number, then "
        "the code we send you, and choose a new PIN.\n"
        "*Change it:* web app → Menu → More → *My Profile* → change PIN.\n\n"
        "Never share your PIN — CreditVoice staff will never ask for it."
    ),
    "school_fees": (
        "School fees (schools only): web app → Menu → *School fees*.\n\n"
        "Set up classes and terms, add fee items per class, then *raise the term's fees* — "
        "each pupil is charged and owes until they pay. Excuse any pupil from an item.\n\n"
        "Record a payment: *Record fee payment*, or on WhatsApp: _Ade paid school fees 50000_.\n"
        "Add a pupil: *My students* → *Add Student*."
    ),
    "poultry": (
        "Egg & Feed (poultry farms): web app → Menu → *Egg & Feed*.\n\n"
        "*Eggs:* log each day's collection by grade (sorted, medium, small, cracked…) — "
        "each grade is a product you can sell by crate or loose (30 = 1 crate).\n"
        "*Feed:* log feed used each day (it isn't a sale), so feed stock stays right.\n"
        "The *Report* shows crates collected vs sold, egg income and feed cost."
    ),
    "fuel_station": (
        "Fuel sales (filling stations): web app → Menu → More → *Fuel Station*.\n\n"
        "Set up your pumps and prices, record opening and closing meter readings each "
        "shift, and CreditVoice works out litres sold and the money expected."
    ),
    "fake_product": (
        "Suspect a product is fake?\n\n"
        "*Report it:* web app → your stock list → tap the product → "
        "*🚩 Report suspected fake* → say what looked wrong and who supplied it.\n\n"
        "Our team reviews every report. If it's confirmed, every other shop with the "
        "same product (barcode) or the same supplier is warned, and the barcode is "
        "flagged at every till. Your shop's name is never shown to them. You'll be "
        "told what we find.\n\n"
        "CreditVoice also warns you when a barcode doesn't add up or is known as a "
        "different product. A barcode can't prove a packet is genuine, so also check "
        "the NAFDAC number, the seal and the price, and buy from trusted suppliers."
    ),
    "barcode_scan": (
        "Scanning barcodes — your phone camera works as the scanner:\n\n"
        "*To sell:* Select product (the till) → tap *📷 Scan* → point at the barcode. "
        "It beeps and adds the item. Tick *Keep scanning* to scan item after item.\n\n"
        "*To save a product's barcode:* Add stock → the product → *Edit* → "
        "*Barcode* → tap *📷 Scan*, then Save. New products: the same box is on Add.\n\n"
        "*On an invoice:* New invoice → *Scan items*.\n\n"
        "A code the till doesn't know? It asks which product to attach it to — "
        "that's how you build your barcode list while selling.\n\n"
        "*Spotting bad packets:* CreditVoice warns you when a barcode doesn't add up "
        "(made-up or misprinted packaging) or is known as a different product. It "
        "can't prove a packet is genuine — fakers copy real barcodes — so check the "
        "packet and buy from trusted suppliers.\n\n"
        "Have a USB or Bluetooth scanner? Click the search box and scan; it works too.\n"
        "If the camera won't open, allow camera access for this site in your browser settings."
    ),
    "site_review": (
        "Get a free advert on the CreditVoice homepage:\n\n"
        "Web app → Menu → More → *My Profile* → *Your review — free advert* → "
        "write what CreditVoice does for you, tick *Yes, show my business publicly*, "
        "and send.\n\n"
        "Our team checks it, and you'll be told when it's approved or on the homepage. "
        "Your business name, town and the contact you choose go with it, so customers "
        "can find you. You can change or remove it any time."
    ),
    "supplier_directory": (
        "The Verified Supplier directory (web app → Menu → More → *Suppliers*):\n\n"
        "*Find a supplier:* browse verified suppliers and tap *Connect*. The supplier "
        "accepts or declines; their contact is shared once they accept. After that you "
        "can rate them.\n\n"
        "*Be listed as a supplier (Pro or Premium):* Suppliers → *Apply* → your products, "
        "states you cover and CAC number. We review it within 48 hours and tell you the "
        "result. Then buyers can find you and send connection requests — answer them on "
        "your Supplier Profile.\n\n"
        "Your own suppliers (who you buy from and owe) are on the same page."
    ),
    "finance_scorecard": (
        "Financing and your Business Score (web app → Menu → More → *Business Score*):\n\n"
        "Your score is built from what you record — steady sales, customers paying back, "
        "stock. The more you record, the stronger it is.\n\n"
        "*Finance offers* you qualify for show on the same page (e.g. a motorcycle or "
        "freezer paid for in installments). Fill in your identity details once, then "
        "*Apply*. We send your request to the financier and tell you each step: sent, "
        "in review, approved or declined (with the reason), delivered.\n\n"
        "*Repayments:* after delivery, record each one on the Business Score page as you "
        "pay; the financier confirms it.\n\n"
        "Grants and other offers are under Menu → More → *Opportunities*."
    ),
    # receipt → merged into build_app_guide_message ("pdf" topic, single source).
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
    # void_transaction → merged into build_app_guide_message ("void", single source).
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
        "To update your profile — business name, business type, or address:\n\n"
        "*On the web app:*\n"
        "1. Open the menu and tap *My Profile*\n"
        "2. Edit your name, business type, or address\n"
        "3. Tap *Save changes*\n\n"
        "Your business name and address are what show on your receipts and invoices.\n\n"
        "*On WhatsApp:* send  change name  and tiTi will walk you through it.\n\n"
        "Your customers, records, and transactions are not affected."
    ),
    "redeem_code": (
        "If you have a plan/token code (e.g. GO-A1B2C3D4 or PRO-XY123456):\n\n"
        "*On the web app:* open the dashboard → *Have a plan code?* → enter the "
        "code → your plan activates instantly.\n\n"
        "*On WhatsApp:* send  redeem YOUR-CODE  (e.g. redeem GO-A1B2C3D4).\n\n"
        "Each code is single-use and may have an expiry date."
    ),
    "referral": (
        "Invite other business owners and earn — here's how:\n\n"
        "1. Create your code: open the web app → Dashboard → *Invite a Friend*, "
        "then pick your referral code (e.g. DANSHOP).\n"
        "2. Share it: tap *Share* to send your sign-up link, or ask your friend to "
        "send  join YOURCODE  to tiTi on WhatsApp.\n"
        "3. Your friend gets 14 days free on GO when they join.\n\n"
        "On any paid plan (GO, PRO or PREMIUM) you earn plan credit every month for "
        "each friend who is on an active paid plan — it reduces your next "
        "subscription payment. On Basic you can invite up to 2 friends."
    ),
    "opportunities": (
        "Opportunities are offers — loans, grants, equipment, trade deals — posted "
        "by the CreditVoice team.\n\n"
        "Open *Opportunities* in the web app menu to browse them. Some ask a few "
        "questions when you apply — answer them and submit. A red badge shows when "
        "there's a new opportunity you haven't opened yet."
    ),
    # send_reminders → merged into build_app_guide_message ("reminder", single source).
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
        "Thrift / Ajo / Esusu savings:\n\n"
        "• Your OWN savings (here on WhatsApp):\n"
        "  I saved 5000\n"
        "  personal savings 10000\n\n"
        "• Savings GROUPS are on the web app (Thrift / Ajo → Group). One person can run many groups, each with its own amount, members and invite link. Three kinds:\n"
        "  1. Rotating ajo — fixed amount each round, pot rotates to one member per round.\n"
        "  2. Daily collection (alajo) — collect a daily amount from each customer; each keeps their own savings and you cash them out (keeping a commission).\n"
        "  3. Target — everyone saves toward one goal, e.g. Eid (Pro plan).\n\n"
        "Every group is capped, joins via a link, and the admin can add an approver. Open the web app to set one up."
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
        "An invoice asks a customer to pay. It is *not* a debt and takes nothing "
        "out of stock until something actually happens. Invoices are on the web "
        "app only.\n\n"
        "To write one:\n"
        "1. Open the web dashboard → Invoices → New invoice\n"
        "2. Pick the customer, add the items and a pay-by date — it gets a number "
        "automatically (INV-0001)\n"
        "3. Send it to their WhatsApp, or print / save it as PDF\n\n"
        "Then, on the invoice:\n"
        "- *Mark delivered* when the goods go out — that is when they leave stock\n"
        "- *Record payment* when the customer pays — it becomes a sale with a "
        "receipt. If they pay part, the rest becomes their debt; enter 0 to put "
        "it all on credit\n"
        "- *Cancel* an invoice nothing has happened to yet\n\n"
        "The Invoices page shows each one as Waiting, Overdue, Part paid, Paid or "
        "Cancelled, and how much is awaiting payment."
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
    # staff_accounts → merged into build_app_guide_message ("staff", single source).
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
    # business_partners → merged into build_app_guide_message ("partner", single source).
    # business_notes → merged into build_app_guide_message ("notes", single source).
}


# Single source of truth: these topics also have a richer app guide that carries
# BOTH the WhatsApp and web-app steps (build_app_guide_message). The FAQ defers
# to it so the same question never yields two different answers.
_FAQ_KEY_TO_GUIDE_TOPIC = {
    "record_sale":       "record_sale",
    "void_transaction":  "void",
    "add_stock":         "inventory",
    "add_customer":      "customers",
    "add_supplier":      "supplier",
    "send_reminders":    "reminder",
    "staff_accounts":    "staff",
    "business_partners": "partner",
    "business_notes":    "notes",
    "receipt":           "pdf",
    "dashboard":         "summary",
}


def _where_answer(route):
    from nav_guide import NAV_GUIDE
    e = NAV_GUIDE.get(route)
    if not e:
        return FAQ_ANSWERS["formats"]
    under_more = "More" in (e.get("where") or "")
    path = "Menu → More → " if under_more else "Menu → "
    also = f"\n(Your menu may call it: {e['also']}.)" if e.get("also") else ""
    return (f"*{e['name']}*: {path}{e['name']}{also}\n\n{e['what']}\n\n"
            "On a phone, tap ☰ at the top left to open the menu. Items you use often "
            "rise to the top; the rest are under *More* at the bottom.")


def get_faq_answer(key, user=None):
    """The answer, in this business's menu words ({till} → "Select product")."""
    from biz_language import in_menu_words
    if key and key.startswith("where:"):
        return in_menu_words(_where_answer(key[len("where:"):]), user)
    topic = _FAQ_KEY_TO_GUIDE_TOPIC.get(key)
    if topic:
        from messages import build_app_guide_message
        return build_app_guide_message(topic, user)
    return in_menu_words(FAQ_ANSWERS.get(key, FAQ_ANSWERS["formats"]), user)
