PLAN_BASIC   = "BASIC"
PLAN_GO      = "GO"
PLAN_PRO     = "PRO"
PLAN_PREMIUM = "PREMIUM"

PLAN_ORDER = {
    PLAN_BASIC:   1,
    PLAN_GO:      2,
    PLAN_PRO:     3,
    PLAN_PREMIUM: 4,
}

# Every paid tier. Use this (not a hard-coded ["GO","PRO"]) wherever "is this a
# paying customer?" is asked — so new tiers like PREMIUM are always included.
PAID_PLANS = (PLAN_GO, PLAN_PRO, PLAN_PREMIUM)

# ── Billing period ───────────────────────────────────────────────────────────
# Plans bill monthly (30-day window) or yearly (365-day window). Yearly is
# priced at YEARLY_MONTHS × the monthly price — i.e. 2 months free.
PERIOD_MONTHLY = "MONTHLY"
PERIOD_YEARLY  = "YEARLY"
YEARLY_MONTHS  = 10


def normalize_period(period):
    p = (period or PERIOD_MONTHLY).upper().strip()
    return p if p in (PERIOD_MONTHLY, PERIOD_YEARLY) else PERIOD_MONTHLY


def period_days(period):
    """Activation window in days for a billing period."""
    return 365 if normalize_period(period) == PERIOD_YEARLY else 30

# Numeric caps: None = unlimited, 0 = feature not available on the plan.
# Pro unlocks staff/branches/partners but caps branches/partners/investors at 1
# each; Premium removes those caps (everything unlimited).
PLAN_LIMITS = {
    PLAN_BASIC: {
        "customers":              50,
        "monthly_transactions":   100,
        "monthly_invoice_uses":   5,    # multi-item invoice sessions per month
        "thrift_participants":    10,
        "active_inventory_items": 5,    # items with selling_price set
        "active_suppliers":       5,    # suppliers with cost-price items
        "staff":                  0,    # no app-access staff on Basic
        "school_teachers":        3,    # school-only: teacher roster records
        "branches":               0,    # single location
        "partners":               0,
        "investors":              0,
    },
    PLAN_GO: {
        "customers":              None,
        "monthly_transactions":   None,
        "monthly_invoice_uses":   None,
        "thrift_participants":    None,
        "active_inventory_items": None,
        "active_suppliers":       None,
        "staff":                  0,    # Go = sole proprietor, no staff
        "school_teachers":        None,
        "branches":               0,    # single location
        "partners":               0,
        "investors":              0,
    },
    PLAN_PRO: {
        "customers":              None,
        "monthly_transactions":   None,
        "monthly_invoice_uses":   None,
        "thrift_participants":    None,
        "active_inventory_items": None,
        "active_suppliers":       None,
        "staff":                  None, # unlimited app-access staff
        "school_teachers":        None,
        "branches":               1,    # one branch (the owner's location)
        "partners":               1,    # one partner
        "investors":              1,    # one investor
    },
    PLAN_PREMIUM: {
        "customers":              None,
        "monthly_transactions":   None,
        "monthly_invoice_uses":   None,
        "thrift_participants":    None,
        "active_inventory_items": None,
        "active_suppliers":       None,
        "staff":                  None, # unlimited app-access staff
        "school_teachers":        None,
        "branches":               None, # unlimited branches
        "partners":               None, # unlimited partners
        "investors":              None, # unlimited investors
    },
}

FEATURE_MIN_PLAN = {
    # ── Available on Basic ───────────────────────────────────────────────────
    "DIRECT_SALE":            PLAN_BASIC,
    "THRIFT_AMOUNT_TRACKING": PLAN_BASIC,
    "INVENTORY":              PLAN_BASIC,   # Basic: up to 5 active items
    "SUPPLIERS":              PLAN_BASIC,   # Basic: up to 5 products with cost
    "POS":                    PLAN_BASIC,   # Basic: up to 5 products in POS
    "DUE_REMINDERS":          PLAN_BASIC,
    "REMINDER_AUTOMATION":    PLAN_BASIC,
    "WALLET":                 PLAN_BASIC,
    "SCHOOL_TEACHER_ROSTER":  PLAN_BASIC,   # school-only; 3 on Basic, unlimited on Pro
    "INVOICE":                PLAN_BASIC,   # Basic: 5 multi-item invoice uses/month

    # ── Available on Go ──────────────────────────────────────────────────────
    "EXPORT":                 PLAN_GO,
    "TRANSACTION_NOTES":      PLAN_GO,
    "ADVANCED_REPORTS":       PLAN_GO,
    "THRIFT_PARTICIPANTS":    PLAN_GO,
    "THRIFT_REMINDERS":       PLAN_GO,
    "THRIFT_HISTORY":         PLAN_GO,
    "VOICE_TEXT":             PLAN_GO,
    "CUSTOMER_SALES_BOT":     PLAN_GO,
    "CUSTOMER_BOT_HANDOFF":   PLAN_GO,
    "CUSTOMER_BOT_PART_PAYMENT": PLAN_GO,
    "REMINDER_AUTO_SEND":     PLAN_GO,

    # ── Available on Pro ─────────────────────────────────────────────────────
    "STAFF":                  PLAN_PRO,
    "SCHOOL_APP_STAFF":       PLAN_PRO,   # bursar / accountant with app login
    "STAFF_PERMISSION":       PLAN_PRO,
    "BRANCHES":               PLAN_PRO,
    "MULTILINGUAL_VOICE":     PLAN_PRO,
    "VOICE_REPLY":            PLAN_PRO,
    "DELIVERY_AUTOMATION":    PLAN_PRO,
    "PARTNERS":               PLAN_PRO,
}

FEATURE_VALUE_BY_TEMPLATE = {
    "retail_trading": {
        "INVENTORY":        "Inventory tracks your stock levels, cost, and selling price so you always know what you have.",
        "SUPPLIERS":        "Supplier records show what you bought, what you paid, and what you still owe.",
        "ADVANCED_REPORTS": "Reports show your best sellers, profit margin, and daily/weekly/monthly performance.",
        "DUE_REMINDERS":    "Reminders help you follow customers who bought on credit.",
        "STAFF":            "PRO lets shop attendants record sales while you keep full control.",
        "VOICE_TEXT":       "Voice notes make it faster to record sales while serving customers.",
        "CUSTOMER_SALES_BOT": "The customer bot answers price and stock questions from your saved inventory.",
        "EXPORT":           "Export lets you download your sales and stock as Excel or PDF.",
        "BRANCHES":         "Branches lets you run multiple shop locations from one account.",
        "PARTNERS":         "Partners lets you track investors, co-founders, or silent partners.",
    },
    "pharmacy": {
        "INVENTORY":        "Stock tracking helps you follow medicine quantity and fast-moving items.",
        "SUPPLIERS":        "Supplier records help track medicine purchases and balances.",
        "ADVANCED_REPORTS": "Reports help you see medicine sales, debtors, and stock movement.",
        "DUE_REMINDERS":    "Reminders help follow customers or organisations buying on credit.",
        "STAFF":            "PRO lets attendants record sales while the owner sees everything.",
        "VOICE_TEXT":       "Voice notes help record sales quickly at the counter.",
        "EXPORT":           "Export downloads your stock and sales as Excel or PDF.",
        "BRANCHES":         "Branches lets you manage multiple pharmacy locations from one account.",
    },
    "school": {
        "ADVANCED_REPORTS":     "Reports show paid fees, balances, and unpaid students by term or period.",
        "DUE_REMINDERS":        "Reminders help follow parents or students with unpaid fees.",
        "TRANSACTION_NOTES":    "Notes help attach context to fees, uniforms, books, or special payments.",
        "SCHOOL_APP_STAFF":     "PRO lets a bursar or admin staff record payments with your oversight.",
        "VOICE_TEXT":           "Voice notes make fee recording faster during busy payment periods.",
        "EXPORT":               "Export downloads your fee records and student balances as Excel or PDF.",
        "SCHOOL_TEACHER_ROSTER": "The teacher roster lets you record all your staff — name, subject, and class.",
    },
    "salon_beauty": {
        "INVENTORY":        "Inventory helps track beauty products, attachments, creams, or retail items.",
        "ADVANCED_REPORTS": "Reports show daily services, top customers, and unpaid balances.",
        "DUE_REMINDERS":    "Reminders help follow customers who part-paid for services.",
        "STAFF":            "PRO lets stylists or attendants record their work while you see all records.",
        "VOICE_TEXT":       "Voice notes help record service income hands-free.",
        "EXPORT":           "Export downloads your service records and customer balances.",
        "BRANCHES":         "Branches lets you manage multiple salon locations from one account.",
    },
    "artisan_services": {
        "SUPPLIERS":        "Supplier records help track materials bought for jobs.",
        "ADVANCED_REPORTS": "Reports show jobs, payments, and customers still owing.",
        "DUE_REMINDERS":    "Reminders help follow unpaid job balances.",
        "STAFF":            "PRO lets workers record jobs while you keep control.",
        "VOICE_TEXT":       "Voice notes help record jobs while working.",
        "EXPORT":           "Export downloads your job records and customer balances.",
    },
    "food_hospitality": {
        "INVENTORY":        "Stock helps track drinks, frozen food, ingredients, and products.",
        "SUPPLIERS":        "Supplier records help track purchases and balances.",
        "ADVANCED_REPORTS": "Reports show daily sales, products, and unpaid balances.",
        "DUE_REMINDERS":    "Reminders help follow customers who part-paid or bought on credit.",
        "STAFF":            "PRO lets attendants or cashiers record sales with your control.",
        "VOICE_TEXT":       "Voice notes help record sales quickly during busy hours.",
        "EXPORT":           "Export downloads your sales and stock records.",
        "BRANCHES":         "Branches lets you manage multiple outlets from one account.",
    },
    "agriculture": {
        "INVENTORY":        "Stock helps track feed, produce, livestock, and farm inputs.",
        "SUPPLIERS":        "Supplier records help track purchases from suppliers or farmers.",
        "ADVANCED_REPORTS": "Reports show products sold, balances, and stock movement.",
        "DUE_REMINDERS":    "Reminders help follow customers or members with unpaid balances.",
        "STAFF":            "PRO lets workers or sales attendants record for the owner.",
        "VOICE_TEXT":       "Voice notes help record sales while working in the field.",
        "EXPORT":           "Export downloads your farm sales and stock records.",
    },
    "transport_logistics": {
        "ADVANCED_REPORTS": "Reports show delivery income, trip income, and unpaid balances.",
        "DUE_REMINDERS":    "Reminders help follow unpaid delivery, hire, or trip balances.",
        "TRANSACTION_NOTES": "Notes help keep trip, rider, vehicle, or delivery details.",
        "STAFF":            "PRO lets drivers or riders record work while you see records.",
        "VOICE_TEXT":       "Voice notes help record trips and deliveries quickly.",
        "EXPORT":           "Export downloads your trip and payment records.",
    },
    "real_estate_rentals": {
        "ADVANCED_REPORTS": "Reports show rent, bookings, commissions, and unpaid balances.",
        "DUE_REMINDERS":    "Reminders help follow rent, booking, or rental balances.",
        "TRANSACTION_NOTES": "Notes help keep property, tenant, unit, or rental details.",
        "STAFF":            "PRO lets agents or staff record payments with your oversight.",
        "VOICE_TEXT":       "Voice notes help record payments and balances quickly.",
        "EXPORT":           "Export downloads your rent and income records.",
        "BRANCHES":         "Branches lets you manage multiple properties or estates from one account.",
    },
    "professional_services": {
        "ADVANCED_REPORTS": "Reports show jobs, payments, and customers still owing.",
        "DUE_REMINDERS":    "Reminders help follow unpaid service balances.",
        "TRANSACTION_NOTES": "Notes help keep job, client, or service details.",
        "STAFF":            "PRO lets staff record jobs or payments with your control.",
        "VOICE_TEXT":       "Voice notes help record jobs and payments faster.",
        "EXPORT":           "Export downloads your job and payment records.",
        "BRANCHES":         "Branches lets you manage multiple office locations.",
    },
    "energy_fuel": {
        "INVENTORY":        "Stock tracking helps you follow fuel, gas, or lubricant quantities and values.",
        "SUPPLIERS":        "Supplier records help track depot purchases, payments, and outstanding balances.",
        "ADVANCED_REPORTS": "Reports show daily sales, fuel income, and outstanding credit accounts.",
        "DUE_REMINDERS":    "Reminders help follow fleet companies and customers buying on credit.",
        "STAFF":            "PRO lets pump attendants or cashiers record sales while you keep full control.",
        "VOICE_TEXT":       "Voice notes help record sales quickly during busy hours.",
        "EXPORT":           "Export downloads your fuel sales and debtor records.",
        "BRANCHES":         "Branches lets you manage multiple stations or depots from one account.",
    },
    "quarry_raw_materials": {
        "INVENTORY":        "Stock tracking helps you follow materials by trip, tonne, or unit.",
        "SUPPLIERS":        "Supplier records help track purchases and haulage costs.",
        "ADVANCED_REPORTS": "Reports show site deliveries, income, and unpaid site balances.",
        "DUE_REMINDERS":    "Reminders help follow construction companies and sites buying on credit.",
        "STAFF":            "PRO lets drivers or weighbridge staff record deliveries while you see all records.",
        "VOICE_TEXT":       "Voice notes help record deliveries and payments quickly on site.",
        "EXPORT":           "Export downloads your delivery records and debtor list.",
        "TRANSACTION_NOTES": "Notes help record site, destination, and delivery details for each trip.",
    },
    "thrift_contribution": {
        "THRIFT_AMOUNT_TRACKING": "Basic lets you record contribution amounts for a small group.",
        "THRIFT_PARTICIPANTS":    "Go removes the Basic 10-participant limit.",
        "THRIFT_REMINDERS":       "Go reminders help you follow participants who have not contributed.",
        "THRIFT_HISTORY":         "Go history helps you see each participant's contribution record.",
        "DUE_REMINDERS":          "Reminders help you follow missed or due contributions.",
        "ADVANCED_REPORTS":       "Reports help you review participants, totals, and balances.",
        "STAFF":                  "PRO lets collectors record contributions while you keep control.",
        "VOICE_TEXT":             "Voice notes help record contributions quickly in the field.",
        "EXPORT":                 "Export downloads your contribution records.",
    },
}


def normalize_plan(plan):
    plan = (plan or PLAN_BASIC).upper().strip()
    return plan if plan in PLAN_ORDER else PLAN_BASIC


def is_paid_plan(plan):
    """True for any paying tier (GO/PRO/PREMIUM), False for BASIC/unknown."""
    return normalize_plan(plan) in PAID_PLANS


def plan_allows_feature(plan, feature):
    required = FEATURE_MIN_PLAN.get(feature, PLAN_BASIC)
    return PLAN_ORDER[normalize_plan(plan)] >= PLAN_ORDER[required]


def plan_limit(plan, key):
    """Return the numeric limit for a plan+key, or None if unlimited."""
    return PLAN_LIMITS.get(normalize_plan(plan), {}).get(key)


def within_limit(plan, key, current_count):
    """True if current_count is below the plan's limit (or no limit)."""
    limit = plan_limit(plan, key)
    return limit is None or current_count < limit


def feature_value_reason(user, feature):
    try:
        from business_templates import template_key_for_user
    except ImportError:
        return None
    template_key = template_key_for_user(user)
    if not template_key:
        return None
    return FEATURE_VALUE_BY_TEMPLATE.get(template_key, {}).get(feature)


def format_upgrade_message(current_plan, required_plan, feature_label, user=None, feature=None):
    reason = feature_value_reason(user, feature) if user and feature else None
    reason_line = f"{reason}\n\n" if reason else ""
    return (
        f"To use {feature_label}, upgrade to {required_plan}.\n\n"
        f"{reason_line}"
        f"Your current plan: {normalize_plan(current_plan)}\n\n"
        "Send UPGRADE to see plans."
    )


def format_limit_message(current_plan, limit_label, limit_value, upgrade_plan, feature_label, user=None, feature=None):
    """Used when a user has hit a count-based limit (e.g. 5 active items on Basic)."""
    reason = feature_value_reason(user, feature) if user and feature else None
    reason_line = f"{reason}\n\n" if reason else ""
    return (
        f"You have reached the {current_plan} limit of {limit_value} {limit_label}.\n\n"
        f"{reason_line}"
        f"Upgrade to {upgrade_plan} to add more.\n\n"
        "Send UPGRADE to see plans."
    )
