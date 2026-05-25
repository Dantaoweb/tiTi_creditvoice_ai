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
        "thrift_participants": 10,
        "staff": 0,
    },
    PLAN_GO: {
        "customers": None,
        "monthly_transactions": None,
        "thrift_participants": None,
        "staff": 0,
    },
    PLAN_PRO: {
        "customers": None,
        "monthly_transactions": None,
        "thrift_participants": None,
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
    "THRIFT_AMOUNT_TRACKING": PLAN_BASIC,
    "THRIFT_PARTICIPANTS": PLAN_GO,
    "THRIFT_REMINDERS": PLAN_GO,
    "THRIFT_HISTORY": PLAN_GO,
}

FEATURE_VALUE_BY_TEMPLATE = {
    "retail_trading": {
        "INVENTORY": "For shops, inventory helps you know what is left and what stock is worth.",
        "SUPPLIERS": "For shops, supplier records help you track what you bought and what you still owe.",
        "ADVANCED_REPORTS": "For shops, product reports show what is selling and where money is tied down.",
        "DUE_REMINDERS": "For shops, reminders help you follow customers who bought on credit.",
        "STAFF": "For shops, PRO lets attendants record sales while the owner keeps control.",
        "VOICE_TEXT": "For shops, voice notes make it faster to record sales while serving customers.",
    },
    "pharmacy": {
        "INVENTORY": "For pharmacies, stock tracking helps you follow medicine quantity and fast-moving items.",
        "SUPPLIERS": "For pharmacies, supplier records help track medicine purchases and balances.",
        "ADVANCED_REPORTS": "For pharmacies, reports help you see medicine sales, debtors, and stock movement.",
        "DUE_REMINDERS": "For pharmacies, reminders help follow customers or organizations buying on credit.",
        "STAFF": "For pharmacies, PRO lets attendants record sales while the owner sees everything.",
        "VOICE_TEXT": "For pharmacies, voice notes help record sales quickly at the counter.",
    },
    "school": {
        "ADVANCED_REPORTS": "For schools, reports help you see paid fees, balances, and unpaid students by period.",
        "DUE_REMINDERS": "For schools, reminders help follow parents or students with unpaid fees.",
        "TRANSACTION_NOTES": "For schools, notes help attach context to fees, uniforms, books, or special payments.",
        "STAFF": "For schools, PRO lets a bursar or admin staff record payments with owner oversight.",
        "VOICE_TEXT": "For schools, voice notes make fee recording faster during busy payment periods.",
    },
    "salon_beauty": {
        "INVENTORY": "For salons, inventory helps track beauty products, attachments, creams, or retail items.",
        "ADVANCED_REPORTS": "For salons, reports show daily services, top customers, and unpaid balances.",
        "DUE_REMINDERS": "For salons, reminders help follow customers who part-paid for services.",
        "TRANSACTION_NOTES": "For salons, notes help remember service details like style, product, or appointment context.",
        "STAFF": "For salons, PRO lets stylists or attendants record their work while the owner sees records.",
        "VOICE_TEXT": "For salons, voice notes help record service income hands-free.",
    },
    "artisan_services": {
        "SUPPLIERS": "For service businesses, supplier records help track materials bought for jobs.",
        "ADVANCED_REPORTS": "For service businesses, reports show jobs, payments, and customers still owing.",
        "DUE_REMINDERS": "For service businesses, reminders help follow unpaid job balances.",
        "TRANSACTION_NOTES": "For service businesses, notes help remember job details, measurements, faults, or materials.",
        "STAFF": "For service businesses, PRO lets workers record jobs while the owner keeps control.",
        "VOICE_TEXT": "For service businesses, voice notes help record jobs while working.",
    },
    "food_hospitality": {
        "INVENTORY": "For food businesses, stock helps track drinks, frozen food, ingredients, and products.",
        "SUPPLIERS": "For food businesses, supplier records help track purchases and balances.",
        "ADVANCED_REPORTS": "For food businesses, reports show daily sales, products, and unpaid balances.",
        "DUE_REMINDERS": "For food businesses, reminders help follow customers who part-paid or bought on credit.",
        "STAFF": "For food businesses, PRO lets attendants or cashiers record sales with owner control.",
        "VOICE_TEXT": "For food businesses, voice notes help record sales quickly during busy hours.",
    },
    "agriculture": {
        "INVENTORY": "For agriculture, stock helps track feed, produce, livestock, and farm inputs.",
        "SUPPLIERS": "For agriculture, supplier records help track purchases from suppliers or farmers.",
        "ADVANCED_REPORTS": "For agriculture, reports show products sold, balances, and stock movement.",
        "DUE_REMINDERS": "For agriculture, reminders help follow customers or members with unpaid balances.",
        "STAFF": "For agriculture, PRO lets workers or sales attendants record for the owner.",
        "VOICE_TEXT": "For agriculture, voice notes help record sales while working in the field or shop.",
    },
    "transport_logistics": {
        "ADVANCED_REPORTS": "For transport, reports show delivery income, trip income, and unpaid balances.",
        "DUE_REMINDERS": "For transport, reminders help follow unpaid delivery, hire, or trip balances.",
        "TRANSACTION_NOTES": "For transport, notes help keep trip, rider, vehicle, or delivery details.",
        "STAFF": "For transport, PRO lets drivers or riders record work while the owner sees records.",
        "VOICE_TEXT": "For transport, voice notes help record trips and deliveries quickly.",
    },
    "real_estate_rentals": {
        "ADVANCED_REPORTS": "For rentals, reports show rent, bookings, commissions, and unpaid balances.",
        "DUE_REMINDERS": "For rentals, reminders help follow rent, booking, or equipment rental balances.",
        "TRANSACTION_NOTES": "For rentals, notes help keep property, tenant, unit, or rental details.",
        "STAFF": "For rentals, PRO lets agents or staff record payments with owner oversight.",
        "VOICE_TEXT": "For rentals, voice notes help record payments and balances quickly.",
    },
    "professional_services": {
        "ADVANCED_REPORTS": "For service offices, reports show jobs, payments, and customers still owing.",
        "DUE_REMINDERS": "For service offices, reminders help follow unpaid service balances.",
        "TRANSACTION_NOTES": "For service offices, notes help keep job, client, or service details.",
        "STAFF": "For service offices, PRO lets staff record jobs or payments with owner control.",
        "VOICE_TEXT": "For service offices, voice notes help record jobs and payments faster.",
    },
    "thrift_contribution": {
        "THRIFT_AMOUNT_TRACKING": "For thrift, BASIC lets you record contribution amounts for a small group.",
        "THRIFT_PARTICIPANTS": "For thrift, GO removes the BASIC 10-participant limit.",
        "THRIFT_REMINDERS": "For thrift, GO reminders help you follow participants who have not contributed.",
        "THRIFT_HISTORY": "For thrift, GO history helps you see each participant's contribution record.",
        "DUE_REMINDERS": "For thrift, reminders help you follow missed or due contributions.",
        "ADVANCED_REPORTS": "For thrift, reports help you review participants, totals, and balances.",
        "STAFF": "For thrift, PRO lets collectors record contributions while the owner keeps control.",
        "VOICE_TEXT": "For thrift, voice notes help record contributions quickly in the field.",
    },
}


def normalize_plan(plan):
    plan = (plan or PLAN_BASIC).upper().strip()
    if plan in PLAN_ORDER:
        return plan
    return PLAN_BASIC


def plan_allows_feature(plan, feature):
    required_plan = FEATURE_MIN_PLAN.get(feature, PLAN_BASIC)
    return PLAN_ORDER[normalize_plan(plan)] >= PLAN_ORDER[required_plan]


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
