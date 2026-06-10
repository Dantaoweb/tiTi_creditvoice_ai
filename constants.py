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
ACTION_AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"

# ── Select Product cart flow ─────────────────────────────────────────────────
ACTION_SELECT_PRODUCT_LIST = "SELECT_PRODUCT_LIST"
ACTION_SELECT_PRODUCT_QTY = "SELECT_PRODUCT_QTY"
ACTION_SELECT_PRODUCT_CART = "SELECT_PRODUCT_CART"
ACTION_SELECT_PRODUCT_CUSTOMER = "SELECT_PRODUCT_CUSTOMER"
ACTION_SELECT_PRODUCT_PAYMENT = "SELECT_PRODUCT_PAYMENT"
ACTION_SELECT_PRODUCT_DUE = "SELECT_PRODUCT_DUE"
ACTION_SELECT_PRODUCT_CONFIRM = "SELECT_PRODUCT_CONFIRM"

SELECT_PRODUCT_ACTIONS = {
    ACTION_SELECT_PRODUCT_LIST,
    ACTION_SELECT_PRODUCT_QTY,
    ACTION_SELECT_PRODUCT_CART,
    ACTION_SELECT_PRODUCT_CUSTOMER,
    ACTION_SELECT_PRODUCT_PAYMENT,
    ACTION_SELECT_PRODUCT_DUE,
    ACTION_SELECT_PRODUCT_CONFIRM,
}

# ── Add stock with prices confirm ────────────────────────────────────────────
ACTION_STOCK_ADD_CONFIRM = "STOCK_ADD_CONFIRM"

# ── Guided stock add (catalog Q&A flow) ──────────────────────────────────────
ACTION_GUIDED_STOCK_CATALOG  = "GUIDED_STOCK_CATALOG"
ACTION_GUIDED_STOCK_VARIANT  = "GUIDED_STOCK_VARIANT"
ACTION_GUIDED_STOCK_QTY      = "GUIDED_STOCK_QTY"
ACTION_GUIDED_STOCK_COST     = "GUIDED_STOCK_COST"
ACTION_GUIDED_STOCK_SELL     = "GUIDED_STOCK_SELL"
ACTION_GUIDED_STOCK_SUPPLIER = "GUIDED_STOCK_SUPPLIER"
ACTION_GUIDED_STOCK_CONFIRM  = "GUIDED_STOCK_CONFIRM"
ACTION_GUIDED_STOCK_ANOTHER  = "GUIDED_STOCK_ANOTHER"

GUIDED_STOCK_ACTIONS = {
    ACTION_GUIDED_STOCK_CATALOG,
    ACTION_GUIDED_STOCK_VARIANT,
    ACTION_GUIDED_STOCK_QTY,
    ACTION_GUIDED_STOCK_COST,
    ACTION_GUIDED_STOCK_SELL,
    ACTION_GUIDED_STOCK_SUPPLIER,
    ACTION_GUIDED_STOCK_CONFIRM,
    ACTION_GUIDED_STOCK_ANOTHER,
}

# ── Stock menu (after viewing inventory list) ─────────────────────────────────
ACTION_STOCK_MENU            = "STOCK_MENU"
ACTION_STOCK_ITEM_MENU       = "STOCK_ITEM_MENU"
ACTION_STOCK_ITEM_ADD_QTY    = "STOCK_ITEM_ADD_QTY"
ACTION_STOCK_ITEM_UPDATE_PRICE = "STOCK_ITEM_UPDATE_PRICE"

STOCK_MENU_ACTIONS = {
    ACTION_STOCK_MENU,
    ACTION_STOCK_ITEM_MENU,
    ACTION_STOCK_ITEM_ADD_QTY,
    ACTION_STOCK_ITEM_UPDATE_PRICE,
}

# ── Guided service price setup ──────────────────────────────────────────────
ACTION_GUIDED_SERVICE_SETUP      = "GUIDED_SERVICE_SETUP"
ACTION_GUIDED_SERVICE_EDIT_PRICE = "GUIDED_SERVICE_EDIT_PRICE"
ACTION_GUIDED_SERVICE_ADD_NAME   = "GUIDED_SERVICE_ADD_NAME"
ACTION_GUIDED_SERVICE_ADD_PRICE  = "GUIDED_SERVICE_ADD_PRICE"

GUIDED_SERVICE_SETUP_ACTIONS = {
    ACTION_GUIDED_SERVICE_SETUP,
    ACTION_GUIDED_SERVICE_EDIT_PRICE,
    ACTION_GUIDED_SERVICE_ADD_NAME,
    ACTION_GUIDED_SERVICE_ADD_PRICE,
}

# ── Service job (customer brought items) ─────────────────────────────────────
ACTION_SERVICE_JOB_CONFIRM = "SERVICE_JOB_CONFIRM"

# ── Fast Capture Mode ────────────────────────────────────────────────────────
ACTION_FAST_CAPTURE_REVIEW = "FAST_CAPTURE_REVIEW"

FAST_CAPTURE_REVIEW_ACTIONS = {ACTION_FAST_CAPTURE_REVIEW}

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
