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

Ordinary staff (not admins) record sales and see their own records. To serve
customers they see the business's customers too (their branch's and the
business-wide ones) — on by default; the owner can set "only their own"
(User.staff_sees_customers False). They never see cost prices or profit.
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


def sees_business_customers(user):
    """An ordinary staff member sees the business's customers (to serve them)
    unless the owner chose "only their own" (User.staff_sees_customers False)."""
    if not user or not getattr(user, "parent_id", None) or getattr(user, "can_view_all_transactions", False):
        return False
    return getattr(user, "staff_sees_customers", None) is not False


# ── What an ORDINARY staff member may do — the owner's tick-boxes on Staff ────
# All allowed by default (how the app always worked). The owner unticks one to
# switch it off for that person; the till and WhatsApp then refuse it plainly.
STAFF_RULES = {
    "discount": "Give a discount",
    "below_price": "Sell below the set price",
    "credit": "Sell on credit (customer owes)",
    "void": "Void a sale they recorded",
    "customers_edit": "Add or change customers",
    "see_stock": "See how much stock is left",
}
REFUSAL = {
    "discount": "Discounts are switched off for you — ask the owner.",
    "below_price": "Selling below the set price is switched off for you — ask the owner.",
    "credit": "Selling on credit is switched off for you — the customer must pay in full, or ask the owner.",
    "void": "Voiding sales is switched off for you — ask the owner.",
    "customers_edit": "Adding or changing customers is switched off for you — ask the owner.",
    "see_stock": "Stock levels are for the owner — ask them.",
}


def blocked_of(user):
    """What the owner switched off for this ordinary staff member. The owner and
    admins (who have their own limits above) are never blocked here."""
    if not user or not getattr(user, "parent_id", None) or getattr(user, "can_view_all_transactions", False):
        return []
    try:
        raw = json.loads(getattr(user, "staff_blocked", None) or "[]")
    except (TypeError, ValueError):
        raw = []
    return [k for k in raw if k in STAFF_RULES]


def may(user, key):
    """True unless the owner switched `key` off for this staff member."""
    return key not in blocked_of(user)


def _lowest_allowed_price(item, qty, sold_unit=None):
    """The price this line may be sold at without going below the set price:
    the sub-unit price for a sub-unit sale, the wholesale price once the
    quantity reaches its threshold, else the selling price. None = no price set."""
    if item is None:
        return None
    if sold_unit and item.retail_unit and str(sold_unit).lower() == str(item.retail_unit).lower():
        return item.retail_price or None
    if item.wholesale_price and item.wholesale_min_qty and float(qty or 0) >= float(item.wholesale_min_qty):
        return item.wholesale_price
    return item.selling_price or None


def below_price_line(db, owner_phone, product, unit_price, qty=1, unit=None, sold_unit=None, item_id=None):
    """The product name if this line is priced below what it may be sold at, else None."""
    from inventory_suppliers import find_matching_inventory_item
    from models import InventoryItem
    item = None
    if item_id:
        item = db.query(InventoryItem).filter(InventoryItem.id == item_id, InventoryItem.owner_phone == owner_phone).first()
    if item is None and product:
        item = find_matching_inventory_item(db, owner_phone, product, unit)
    floor = _lowest_allowed_price(item, qty, sold_unit)
    if floor and unit_price is not None and int(unit_price) < int(floor):
        return (item.name or product or "").title()
    return None


def sale_problem(db, user, owner_phone, lines, discount=0, paid=None, total=None):
    """Why this staff member may not record this sale, or None. `lines` =
    [{product, unit_price, qty, unit, sold_unit, item_id}]. `paid` None = not known."""
    blocked = blocked_of(user)
    if not blocked:
        return None
    if "discount" in blocked and int(discount or 0) > 0:
        return REFUSAL["discount"]
    if "below_price" in blocked:
        for ln in lines or []:
            name = below_price_line(db, owner_phone, ln.get("product"), ln.get("unit_price"), ln.get("qty") or 1,
                                    ln.get("unit"), ln.get("sold_unit"), ln.get("item_id"))
            if name:
                return f"{name}: {REFUSAL['below_price']}"
    if "credit" in blocked and paid is not None and total is not None and int(paid) < int(total):
        return REFUSAL["credit"]
    return None


def set_blocked(user, keys):
    clean = sorted({k for k in (keys or []) if k in STAFF_RULES})
    user.staff_blocked = json.dumps(clean)
    return clean


def set_limits(user, keys):
    clean = sorted({k for k in (keys or []) if k in LIMITS})
    user.staff_limits = json.dumps(clean)
    return clean
