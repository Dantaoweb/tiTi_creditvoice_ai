PLAN_BASIC = "BASIC"
PLAN_GO = "GO"
PLAN_PRO = "PRO"

PLAN_ORDER = {
    PLAN_BASIC: 1,
    PLAN_GO: 2,
    PLAN_PRO: 3,
}

PLAN_LIMITS = {
    PLAN_BASIC: {
        "customers": 50,
        "monthly_transactions": 100,
        "staff": 0,
    },
    PLAN_GO: {
        "customers": None,
        "monthly_transactions": None,
        "staff": 0,
    },
    PLAN_PRO: {
        "customers": None,
        "monthly_transactions": None,
        "staff": 10,
    },
}

FEATURE_MIN_PLAN = {
    "DIRECT_SALE": PLAN_BASIC,
    "INVOICE": PLAN_GO,
    "TRANSACTION_NOTES": PLAN_GO,
    "ADVANCED_REPORTS": PLAN_GO,
    "DUE_REMINDERS": PLAN_GO,
    "INVENTORY": PLAN_GO,
    "SUPPLIERS": PLAN_GO,
    "STAFF": PLAN_PRO,
    "STAFF_PERMISSION": PLAN_PRO,
    "VOICE_TEXT": PLAN_GO,
    "MULTILINGUAL_VOICE": PLAN_PRO,
    "VOICE_REPLY": PLAN_PRO,
}


def normalize_plan(plan):
    plan = (plan or PLAN_BASIC).upper().strip()
    if plan in PLAN_ORDER:
        return plan
    return PLAN_BASIC


def plan_allows_feature(plan, feature):
    required_plan = FEATURE_MIN_PLAN.get(feature, PLAN_BASIC)
    return PLAN_ORDER[normalize_plan(plan)] >= PLAN_ORDER[required_plan]


def format_upgrade_message(current_plan, required_plan, feature_label):
    return (
        f"{feature_label} is available on {required_plan}.\n\n"
        f"Your current plan: {normalize_plan(current_plan)}\n\n"
        "Send UPGRADE to see plans."
    )
