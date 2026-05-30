# ─────────────────────────────────────────────
# PendingAction.action values — single source of truth.
# Every file that sets or checks pending.action must import from here.
# ─────────────────────────────────────────────

ACTION_BUY = "BUY"
ACTION_PAY = "PAY"
ACTION_COMBINED = "COMBINED"
ACTION_SALE = "SALE"
ACTION_SUPPLIER_PURCHASE = "SUPPLIER_PURCHASE"
ACTION_SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
ACTION_ARTISAN_PAYMENT_CHOICE = "ARTISAN_PAYMENT_CHOICE"
ACTION_DUE_MENU = "DUE_MENU"
ACTION_REMINDER_SELECTION = "REMINDER_SELECTION"
ACTION_REMINDER_CONFIRM = "REMINDER_CONFIRM"
ACTION_DASHBOARD_MENU = "DASHBOARD_MENU"
ACTION_UPGRADE_MENU = "UPGRADE_MENU"
ACTION_OWNER_HOME_MENU = "OWNER_HOME_MENU"
ACTION_STAFF_HOME_MENU = "STAFF_HOME_MENU"
ACTION_ONBOARD_CUSTOMER = "ONBOARD_CUSTOMER"
ACTION_RESIGN_CONFIRM = "RESIGN_CONFIRM"
ACTION_POST_ONBOARDING = "POST_ONBOARDING"
ACTION_ONBOARD_USER = "ONBOARD_USER"
ACTION_ONBOARD_USER_CONFIRM = "ONBOARD_USER_CONFIRM"
ACTION_ONBOARD_USER_CATEGORY = "ONBOARD_USER_CATEGORY"
ACTION_ONBOARD_USER_BUSINESS_TYPE = "ONBOARD_USER_BUSINESS_TYPE"
ACTION_ONBOARD_USER_CUSTOM_TYPE = "ONBOARD_USER_CUSTOM_TYPE"

# ─────────────────────────────────────────────
# Transaction parsing keyword lists.
# Defined once here, imported by parser.py and any other file that needs them.
# ─────────────────────────────────────────────

BUY_KEYWORDS = [
    "bought", "buy", "purchase", "purchased", "collect", "collected",
    "took", "take", "carry", "carried", "owes", "owe", "owing",
]

PAY_KEYWORDS = [
    "paid", "pay", "settle", "settled", "clear", "cleared",
    "gave", "give", "send", "sent", "transfer", "transferred",
    "transfered", "deposit", "deposited", "contribute", "contributed",
    "contribution", "contributions", "save", "saved", "thrift", "ajo", "esusu",
]

SALE_KEYWORDS = ["sold", "sell", "supply", "supplied", "deliver", "delivered"]

# Used when splitting customer name from action verb in a message.
# Direct-sale keywords excluded because SALE transactions have no customer name.
NAME_SPLIT_KEYWORDS = set(BUY_KEYWORDS + PAY_KEYWORDS)

# ─────────────────────────────────────────────
# Due-date natural language phrases.
# Previously duplicated in extract_due_date_from_text() AND inline in parse_message().
# ─────────────────────────────────────────────

DUE_TODAY_PHRASES = [
    "due today", "pay today", "balance today",
    "will pay today", "will balance today",
]

DUE_TOMORROW_PHRASES = [
    "due tomorrow", "due tommorrow", "pay tomorrow", "pay tommorrow",
    "balance tomorrow", "balance tommorrow",
    "will pay tomorrow", "will pay tommorrow",
    "will balance tomorrow", "will balance tommorrow",
]
