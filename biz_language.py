"""
Business Language Layer — thin translation between the core engine and user-facing text.

The engine logic never changes. Only the words presented to the user change per business type.
Keyed by menu_group (returned by business_templates.menu_group_for_user).

Groups:
  stock   — retail, trade, food, pharmacy (default)
  school  — private school, lesson center, daycare, driving school
  service — artisan, beauty/personal care (tailoring, salon, barber, mechanic, etc.)
  fee     — associations, gym, church, cooperative memberships (members, dues)
  professional / tenancy / rental / transport — the businesses that share the
            fee menu layout but have clients, tenants or customers, not members
  thrift  — ajo, thrift, savings group, cooperative contributions
"""

BIZ_LANG = {
    # ── Retail / Trade / Food / Pharmacy (default) ─────────────────────────────
    "stock": {
        "action_word":      "bought",
        "confirm_style":    "verb",       # "NAME bought ITEM"
        "total_label":      "Total bought",
        "credit_sales":     "Credit sales",
        "direct_sales":     "Direct sales",
        "total_sales":      "Total sales",
        "outstanding":      "Outstanding balance",
        "payments":         "Payments received",
        "total_customers":  "Total customers",
        "new_customers":    "New customers",
        "paid_customers":   "Paid customers",
        "show_product_tip": True,
        "example_credit":   "Ade bought rice 5000",
        "example_pay":      "Ade paid 3000",
    },

    # ── Education ───────────────────────────────────────────────────────────────
    "school": {
        "action_word":      "fee",
        "confirm_style":    "label",      # "NAME fee: ITEM"
        "total_label":      "Total",
        "credit_sales":     "Fees invoiced",
        "direct_sales":     "Direct income",
        "total_sales":      "Total fees",
        "outstanding":      "Unpaid fees",
        "payments":         "Fees received",
        "total_customers":  "Total students",
        "new_customers":    "New students",
        "paid_customers":   "Students who paid",
        "show_product_tip": False,
        "example_credit":   "Emeka paid school fees 15000",
        "example_pay":      "Ngozi cleared fees balance 8000",
    },

    # ── Artisan / Beauty / Personal Care ────────────────────────────────────────
    "service": {
        "action_word":      "job",
        "confirm_style":    "label",      # "NAME job: ITEM"
        "total_label":      "Total",
        "credit_sales":     "Jobs on credit",
        "direct_sales":     "Cash jobs",
        "total_sales":      "Total income",
        "outstanding":      "Outstanding balance",
        "payments":         "Payments received",
        "total_customers":  "Total clients",
        "new_customers":    "New clients",
        "paid_customers":   "Clients who paid",
        "show_product_tip": False,
        "example_credit":   "Bola repair 12000 paid 5000",
        "example_pay":      "Ade paid balance 7000",
    },

    # ── Membership / Association / Gym / Church ─────────────────────────────────
    "fee": {
        "action_word":      "dues",
        "confirm_style":    "label",      # "NAME dues: ITEM"
        "total_label":      "Total",
        "credit_sales":     "Fees owed",
        "direct_sales":     "Direct payments",
        "total_sales":      "Total collected",
        "outstanding":      "Outstanding dues",
        "payments":         "Payments received",
        "total_customers":  "Total members",
        "new_customers":    "New members",
        "paid_customers":   "Members who paid",
        "show_product_tip": False,
        "example_credit":   "Amina dues 5000 balance due Friday",
        "example_pay":      "Tunde paid dues 3000",
    },

    # ── Professional services (consulting, law, bookkeeping, printing) ─────────
    "professional": {
        "action_word":      "fee",
        "confirm_style":    "label",      # "NAME fee: ITEM"
        "total_label":      "Total billed",
        "credit_sales":     "Fees owed",
        "direct_sales":     "Fees paid at once",
        "total_sales":      "Total billed",
        "outstanding":      "Fees outstanding",
        "payments":         "Payments received",
        "total_customers":  "Total clients",
        "new_customers":    "New clients",
        "paid_customers":   "Clients who paid",
        "show_product_tip": False,
        "example_credit":   "Bayo consulting fee 80000 paid 30000",
        "example_pay":      "Bayo paid 50000",
    },

    # ── Property managers, stall rent: tenants paying rent ─────────────────────
    "tenancy": {
        "action_word":      "rent",
        "confirm_style":    "label",      # "NAME rent: ITEM"
        "total_label":      "Total rent",
        "credit_sales":     "Rent owed",
        "direct_sales":     "Rent paid at once",
        "total_sales":      "Total rent",
        "outstanding":      "Rent outstanding",
        "payments":         "Rent received",
        "total_customers":  "Total tenants",
        "new_customers":    "New tenants",
        "paid_customers":   "Tenants who paid",
        "show_product_tip": False,
        "example_credit":   "Ade rent 150000 paid 100000",
        "example_pay":      "Ade paid rent 50000",
    },

    # ── Shortlets, equipment and event rental, estate agents ───────────────────
    "rental": {
        "action_word":      "hired",
        "confirm_style":    "verb",       # "NAME hired ITEM"
        "total_label":      "Total",
        "credit_sales":     "Hire owed",
        "direct_sales":     "Paid at once",
        "total_sales":      "Total earned",
        "outstanding":      "Outstanding balance",
        "payments":         "Payments received",
        "total_customers":  "Total clients",
        "new_customers":    "New clients",
        "paid_customers":   "Clients who paid",
        "show_product_tip": False,
        "example_credit":   "Chika hired canopy 40000 paid 20000",
        "example_pay":      "Chika paid 20000",
    },

    # ── Transport and logistics: trips and deliveries ──────────────────────────
    "transport": {
        "action_word":      "delivery",
        "confirm_style":    "label",      # "NAME delivery: ITEM"
        "total_label":      "Total",
        "credit_sales":     "Trips on credit",
        "direct_sales":     "Trips paid at once",
        "total_sales":      "Total earned",
        "outstanding":      "Outstanding balance",
        "payments":         "Payments received",
        "total_customers":  "Total customers",
        "new_customers":    "New customers",
        "paid_customers":   "Customers who paid",
        "show_product_tip": False,
        "example_credit":   "Kunle delivery 15000 paid 5000",
        "example_pay":      "Kunle paid 10000",
    },

    # ── Clinic / Health ─────────────────────────────────────────────────────────
    "clinic": {
        "action_word":      "visit",
        "confirm_style":    "label",      # "NAME visit: ITEM"
        "total_label":      "Total",
        "credit_sales":     "Consultations on credit",
        "direct_sales":     "Cash consultations",
        "total_sales":      "Total income",
        "outstanding":      "Outstanding balance",
        "payments":         "Payments received",
        "total_customers":  "Total patients",
        "new_customers":    "New patients",
        "paid_customers":   "Patients who paid",
        "show_product_tip": False,
        "example_credit":   "Emeka consultation 5000 paid 2000",
        "example_pay":      "Ngozi paid balance 3000",
    },

    # ── Food / Hospitality ───────────────────────────────────────────────────────
    "food": {
        "action_word":      "order",
        "confirm_style":    "label",      # "NAME order: ITEM"
        "total_label":      "Total",
        "credit_sales":     "Orders on credit",
        "direct_sales":     "Cash orders",
        "total_sales":      "Total sales",
        "outstanding":      "Outstanding balance",
        "payments":         "Payments received",
        "total_customers":  "Total customers",
        "new_customers":    "New customers",
        "paid_customers":   "Customers who paid",
        "show_product_tip": True,
        "example_credit":   "Ade ordered jollof rice 3000 paid 1500",
        "example_pay":      "Tunde paid balance 1500",
    },

    # ── Thrift / Ajo / Cooperative ──────────────────────────────────────────────
    "thrift": {
        "action_word":      "contributed",
        "confirm_style":    "verb",       # "NAME contributed ITEM"
        "total_label":      "Total",
        "credit_sales":     "Contributions owed",
        "direct_sales":     "Direct contributions",
        "total_sales":      "Total contributions",
        "outstanding":      "Missed contributions",
        "payments":         "Contributions received",
        "total_customers":  "Total members",
        "new_customers":    "New members",
        "paid_customers":   "Members who contributed",
        "show_product_tip": False,
        "example_credit":   "Amina contributed 5000",
        "example_pay":      "Tunde contributed 10000 paid 5000",
    },
}

_DEFAULT = BIZ_LANG["stock"]


def get_lang(user=None) -> dict:
    """Return the language config for the given user's business group."""
    if not user:
        return _DEFAULT
    from business_templates import label_group_for_user, menu_group_for_user
    group = label_group_for_user(user)
    return BIZ_LANG.get(group) or BIZ_LANG.get(menu_group_for_user(user), _DEFAULT)


def lang(user, key: str, default=None):
    """Shorthand: lang(user, 'credit_sales') → 'Fees invoiced' for school users."""
    return get_lang(user).get(key, _DEFAULT.get(key, default))


def confirm_prefix(customer_name: str, user=None) -> str:
    """
    Return the opening line of a transaction confirmation.
    verb  style: 'Confirm:\\nAde bought'
    label style: 'Confirm:\\nAde fee:'
    """
    cfg = get_lang(user)
    word = cfg["action_word"]
    if cfg["confirm_style"] == "label":
        return f"Confirm:\n{customer_name} {word}:"
    return f"Confirm:\n{customer_name} {word}"
