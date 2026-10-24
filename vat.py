"""
VAT — only for businesses that switch it on (Settings → VAT). Off by default.

The owner chooses how their prices work:
- "add":       prices are before VAT; VAT is added on top
               (₦10,000 + VAT 7.5% ₦750 = ₦10,750);
- "inclusive": prices already include VAT; the total doesn't change and the
               VAT inside it is shown (₦10,750 incl. VAT ₦750).

Products marked "No VAT" (basic food, medicines, school fees…) are left out.
A discount off the whole sale shrinks the VAT in proportion.

frontend/src/lib/vat.js does the same sum so the till shows the same total
the server records — keep them in step (same rounding: half up).
"""
import math

from app_settings import get_business_settings


def _round(x):
    return int(math.floor(x + 0.5))


def vat_settings(db, owner_phone):
    """{"rate", "mode"} when the business charges VAT, else None."""
    s = get_business_settings(db, owner_phone)
    if not s.get("vat_enabled"):
        return None
    try:
        rate = float(s.get("vat_rate") or 0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0:
        return None
    return {"rate": rate, "mode": s.get("vat_mode") or "add"}


def compute_vat(lines, discount, vat):
    """lines: [(line_total, exempt)]. Returns (vat_amount, grand_total, net)
    where net = lines − discount. No VAT setting → (0, net, net)."""
    lines_total = sum(t for t, _e in lines)
    net = lines_total - int(discount or 0)
    if not vat or lines_total <= 0:
        return 0, net, net
    taxable = sum(t for t, e in lines if not e)
    taxable_net = taxable * (net / lines_total)
    rate = float(vat["rate"])
    if vat["mode"] == "inclusive":
        return _round(taxable_net * rate / (100 + rate)), net, net
    amount = _round(taxable_net * rate / 100)
    return amount, net + amount, net


def item_exempt(db, owner_phone, item):
    """Is this sale / invoice line a "No VAT" product?"""
    from models import InventoryItem
    iid = item.get("inventory_item_id")
    inv = db.query(InventoryItem).filter(InventoryItem.id == iid).first() if iid else None
    if inv is None and (item.get("name") or "").strip():
        from inventory_suppliers import find_matching_inventory_item
        inv = find_matching_inventory_item(db, owner_phone, item["name"].strip(), item.get("unit"))
    return bool(inv is not None and getattr(inv, "vat_exempt", False))


def lines_for(db, owner_phone, items):
    return [(float(it.get("qty", 1)) * int(it.get("unit_price", 0)), item_exempt(db, owner_phone, it))
            for it in items]


def vat_label(rate, mode):
    r = f"{rate:g}%"
    return f"VAT {r} (included)" if mode == "inclusive" else f"VAT {r}"
