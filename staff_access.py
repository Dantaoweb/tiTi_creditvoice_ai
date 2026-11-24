"""
What a staff admin may see — the owner's choice on the Staff page.

An admin (a staff member with can_view_all_transactions) sees the WHOLE
business by default — every branch, customers, sales, debts, stock, the
dashboard and profit — like the owner, except the owner-only settings. The
owner can still keep some things from them (User.staff_limits):

  own_branch   only their own branch's records (needs a branch)
  dashboard    the Dashboard and Insights (business totals and charts)
  profit       profit, margins and cost prices
  expenses     Expenses
  suppliers    what the business owes its suppliers (My supply chain)
  stock        adding, adjusting or removing stock

Ordinary staff (not admins) are unchanged: they record sales; they see their
branch's records (or their own, with no branch).
"""
import json

LIMITS = {
    "own_branch": "Other branches (only their own branch)",
    "dashboard": "Dashboard & Insights",
    "profit": "Profit & cost prices",
    "expenses": "Expenses",
    "suppliers": "What we owe suppliers",
    "stock": "Changing stock (add, adjust, remove)",
}


def limits_of(user):
    if not user or not getattr(user, "parent_id", None) or not getattr(user, "can_view_all_transactions", False):
        return []
    try:
        raw = json.loads(getattr(user, "staff_limits", None) or "[]")
    except (TypeError, ValueError):
        raw = []
    return [k for k in raw if k in LIMITS]


def is_admin(user):
    return bool(user and getattr(user, "parent_id", None) and getattr(user, "can_view_all_transactions", False))


def kept_from(user, key):
    """True when this staff admin is kept from `key`. The owner, and ordinary
    staff (whose rules are elsewhere), are never limited here."""
    return key in limits_of(user)


def set_limits(user, keys):
    clean = sorted({k for k in (keys or []) if k in LIMITS})
    user.staff_limits = json.dumps(clean)
    return clean
