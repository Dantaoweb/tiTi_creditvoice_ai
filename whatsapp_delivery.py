"""
Part delivery on WhatsApp — the same rules as the web (deliveries.py): stock
leaves when goods are handed over; what's left waits for the customer, kept
aside in the store (if the owner keeps goods aside) or just owed.

1. A sale with part delivered: "sold 100 cement to Ade 500000 delivered 60".
   The "delivered 60" is read out before the sale is parsed (it used to be
   taken as the amount: a ₦60 sale). The sale is saved; 60 leave stock and the
   other 40 wait for Ade.
2. The next trip: "delivered 25 cement to Ade", "Ade collected 25 cement" —
   taken from what Ade is still owed (oldest sale first, like a waybill). If Ade
   isn't waiting for cement, tiTi says so — it never records a new sale.
3. "Who am I owing goods" / "who is waiting for goods" — the list.
4. The stock reply shows what's kept aside and what's free to sell.
5. A sale can't sell goods kept aside for someone else (the web till's rule).
"""
import json
import re

from deliveries import (
    DeliveryError, _num, _qty, deliver_goods, delivery_note_text, free_in_store,
    goods_to_deliver, reserved_for_item,
)

_N = r"(?P<n>\d+(?:\.\d+)?)"
_SALE_WORD = re.compile(r"\b(?:sold|sell|sells|selling|bought|buy|buys|took on credit|collected .+ for)\b")

# "… delivered 60", "… delivered 60 bags", "… he took 60", "… collected 60 today"
_DELIVERED_TAIL = re.compile(
    r"[,;.]?\s*(?:and\s+|but\s+|only\s+)?(?:i\s+|we\s+|he\s+|she\s+|they\s+)?(?:have\s+|has\s+)?"
    r"(?:delivered|collected|took|taken|carried|picked(?:\s+up)?|gave\s+(?:him|her|them)|sent)\s+"
    r"(?:only\s+)?" + _N + r"(?:\s+(?:bags?|cartons?|pieces?|pcs|units?|crates?|bundles?|tons?|blocks?))?"
    r"(?:\s+(?:today|now|so\s+far|first))?\s*(?=$|[,;.]|\s+(?:remaining|left|balance|rest|and|pay|paid|due)\b)")


def split_delivered(text):
    """A sale message saying part of it went out → (text without that part,
    how many went out). Anything else → (text, None)."""
    low = (text or "").lower()
    if not _SALE_WORD.search(low):
        return text, None
    m = _DELIVERED_TAIL.search(low)
    if not m or m.start() == 0:
        return text, None
    rest = (low[:m.start()] + low[m.end():]).strip(" ,;.")
    return rest, float(m.group("n"))


# The next trip. Two word orders:
#   "delivered 25 (bags of) cement to Ade" / "sent 25 cement to Ade"
#   "Ade collected / took / picked 25 (bags of) cement"
_UNIT_WORDS = r"(?:(?:bags?|cartons?|pieces?|pcs|units?|crates?|bundles?|tons?|blocks?|packs?)\s+(?:of\s+)?)?"
_TRIP_TO = re.compile(
    r"^(?:i\s+|we\s+)?(?:have\s+)?(?:delivered|sent|supplied|dispatched|loaded)\s+" + _N + r"\s+"
    + _UNIT_WORDS + r"(?P<product>[a-z][a-z' \-]{1,40}?)\s+(?:to|for)\s+(?P<name>[a-z][a-z' \-]{1,40}?)"
    r"(?:\s+today)?$")
_TRIP_BY = re.compile(
    r"^(?P<name>[a-z][a-z' \-]{1,40}?)\s+(?:has\s+)?(?:collected|took|picked(?:\s+up)?|carried|received|came\s+for)\s+"
    + _N + r"\s+" + _UNIT_WORDS + r"(?P<product>[a-z][a-z' \-]{1,40}?)(?:\s+today)?$")


def parse_trip(text):
    """{"type": "DELIVER_GOODS", name, product, quantity} — or None. A price
    in the message makes it a sale, not a trip."""
    low = re.sub(r"\s+", " ", (text or "").lower().replace(",", "")).strip(" .!")
    if not low or "?" in low:
        return None
    for rx in (_TRIP_TO, _TRIP_BY):
        m = rx.match(low)
        if m:
            name = m.group("name").strip()
            if re.search(r"\d", name) or name in ("i", "we", "you", "he", "she", "they", "me"):
                return None
            return {"type": "DELIVER_GOODS", "name": name, "product": m.group("product").strip(),
                    "quantity": float(m.group("n"))}
    return None


_OWED_GOODS = re.compile(
    r"\b(?:who\s+(?:am\s+i|i\s+dey|do\s+i)\s+(?:owing|owe)\s+goods|(?:who|which\s+customers?)\s+(?:is|are)\s+"
    r"(?:still\s+)?waiting\s+for\s+(?:goods|delivery|their\s+goods)|goods\s+(?:i\s+)?(?:still\s+)?(?:owe|owing)|"
    r"goods\s+(?:still\s+)?to\s+deliver|who\s+(?:has|have)\s+not\s+collected|who\s+hasn'?t\s+collected|"
    r"(?:undelivered|uncollected)\s+goods|what\s+goods\s+do\s+i\s+owe|owing\s+goods)\b")


def is_goods_owed_question(text):
    return bool(_OWED_GOODS.search((text or "").lower()))


def _scope(visible_recorded_by_id):
    return (None, visible_recorded_by_id) if visible_recorded_by_id else None


def goods_owed_message(db, owner_phone, visible_recorded_by_id=None):
    rows = goods_to_deliver(db, owner_phone, scope=_scope(visible_recorded_by_id))
    if not rows:
        return "🚚 Nobody is waiting for goods — everything sold has been handed over."
    by_cust = {}
    for r in rows:
        by_cust.setdefault(r["customer"], []).append(r)
    out = ["🚚 *Goods still to deliver*", ""]
    for name, rs in by_cust.items():
        out.append(f"*{name}*")
        for r in rs:
            kept = "" if not r["kept"] else (" — kept aside" if r["kept"] >= r["remaining"]
                                             else f" — {_qty(r['kept'], r['unit'])} kept aside")
            out.append(f"• {r['product']}: {_qty(r['remaining'], r['unit'])} of {_qty(r['bought'], r['unit'])}{kept}")
    out += ["", "When some go out, send e.g.: _delivered 25 cement to Ade_"]
    return "\n".join(out)


def _match_row(rows, product):
    want = re.sub(r"[^a-z0-9]", "", (product or "").lower())
    if not want:
        return None
    exact = [r for r in rows if re.sub(r"[^a-z0-9]", "", r["product"].lower()) == want]
    if exact:
        return exact[0]
    near = [r for r in rows if want in re.sub(r"[^a-z0-9]", "", r["product"].lower())
            or re.sub(r"[^a-z0-9]", "", r["product"].lower()) in want]
    return near[0] if len(near) == 1 else None


def handle_trip(db, phone, parsed, user, owner_phone, business_name, visible_recorded_by_id, send_message):
    """Hand over goods a customer is waiting for. Never records a sale."""
    from customer_merge import find_customer_named
    name, product, qty = parsed["name"], parsed["product"], parsed["quantity"]
    customer = find_customer_named(db, owner_phone, name)
    rows = goods_to_deliver(db, owner_phone, customer.id, scope=_scope(visible_recorded_by_id)) if customer else []
    if not customer or not rows:
        who = customer.name.title() if customer else name.title()
        send_message(phone, (
            f"{who} isn't waiting for any goods, so nothing was recorded.\n\n"
            f"Was it a new sale? Send it with the price, e.g. _{who} bought {_num(qty)} {product} 50000_."))
        return {"status": "deliver_nothing_waiting"}
    row = _match_row(rows, product)
    if not row:
        waiting = ", ".join(f"{_qty(r['remaining'], r['unit'])} {r['product']}" for r in rows)
        send_message(phone, f"{customer.name.title()} isn't waiting for {product}. They are waiting for: {waiting}.")
        return {"status": "deliver_product_not_waiting"}
    try:
        d = deliver_goods(db, owner_phone, user.id if user else None, customer.id, row["key"], qty,
                          scope=_scope(visible_recorded_by_id))
        db.commit()
    except DeliveryError as e:
        db.rollback()
        send_message(phone, f"{e} ({customer.name.title()} is waiting for {_qty(row['remaining'], row['unit'])} "
                            f"{row['product']}.)")
        return {"status": "deliver_refused"}
    unit = d["unit"]
    msg = [f"🚚 *{_qty(d['delivered_now'], unit)} {d['product']}* handed over to {customer.name.title()} "
           f"({d['waybill_number']}).", "",
           f"Bought: {_qty(d['bought'], unit)} · Delivered: {_qty(d['delivered'], unit)}",
           (f"*Still to deliver: {_qty(d['remaining'], unit)}*" if d["remaining"] else "*All delivered* ✓")]
    if customer.customer_phone:
        send_message(customer.customer_phone, delivery_note_text(business_name, customer.name.title(), d))
        msg += ["", f"Delivery note sent to {customer.name.title()}."]
    send_message(phone, "\n".join(msg))
    return {"status": "delivered", "remaining": d["remaining"]}


# ── At the sale ─────────────────────────────────────────────────────────────

def kept_aside_problem(db, owner_phone, items):
    """The web till's rule: goods kept aside for customers waiting for delivery
    can't be sold again. `items` = [{product, quantity, unit, delivered_qty?}].
    Returns the refusal text, or None."""
    from inventory_suppliers import _resolve_deduction, normalize_item
    used = {}
    for it in items or []:
        product, unit = normalize_item((it.get("product") or "").strip().lower(), it.get("unit"))
        if not product:
            continue
        inv, whole = _resolve_deduction(db, owner_phone, product, it.get("quantity") or 1, unit)
        if not inv or inv.quantity is None:
            continue
        kept = reserved_for_item(db, owner_phone, inv.id)
        if kept <= 0:
            continue
        now = float(it["delivered_qty"]) if it.get("delivered_qty") is not None else float(whole or 0)
        free = float(inv.quantity or 0) - kept - used.get(inv.id, 0.0)
        if now > free + 1e-9:
            unit = f" {inv.unit}" if inv.unit else ""
            return (f"Only {_num(max(free, 0))}{unit} of {inv.name.title()} can be sold — "
                    f"{_num(kept)} are kept aside for customers waiting for delivery.\n\n"
                    "Send *who am I owing goods* to see who.")
        used[inv.id] = used.get(inv.id, 0.0) + now
    return None


def check_part_delivery(parsed):
    """Is the part delivery on this sale usable? → (delivered or None, problem text or None)."""
    d = parsed.get("delivered_qty")
    if d is None:
        return None, None
    lines = parsed.get("sale_items") or []
    if len(lines) > 1:
        return None, ("Part delivery works one product at a time on WhatsApp. Send the sale like:\n"
                      "_sold 100 cement to Ade 500000 delivered 60_")
    # A part-paid sale ("… 500000 paid 200000") carries its one product as a one-line list
    line = lines[0] if lines else parsed
    qty = line.get("quantity")
    if not line.get("product") or not qty:
        return None, ("Say what was sold and how many, then what went out, e.g.:\n"
                      "_sold 100 cement to Ade 500000 delivered 60_")
    if d >= float(qty):
        return None, None                     # it all went out — an ordinary sale
    if d != int(d) or float(qty) != int(float(qty)):
        return None, "Part delivery works on whole units only."
    return float(d), None


def confirm_line(delivered, quantity, unit, customer_name):
    left = float(quantity) - float(delivered)
    u = f" {unit}" if unit else ""
    return (f"\n🚚 Handed over now: {_num(delivered)}{u} · still to deliver to {customer_name.title()}: "
            f"{_num(left)}{u}")


def delivered_from_payload(pending):
    try:
        d = json.loads(getattr(pending, "payload_json", None) or "{}").get("delivered_qty")
    except (TypeError, ValueError):
        return None
    return float(d) if d is not None else None


def apply_sale_with_part_delivery(db, owner_phone, tx_id, user_id, item, delivered, source_type):
    """Save the sale line and take out only what went out now; the rest waits
    for the customer (kept aside if the owner keeps goods aside). Same result
    as inventory_suppliers.deduct_inventory_for_items: (updates, missing, alerts)."""
    from app_settings import business_setting
    from inventory_suppliers import (_format_stock_remaining, _resolve_deduction, add_inventory_movement,
                                     normalize_item)
    from models import TransactionItem
    product, unit = normalize_item((item.get("product") or "").strip().lower(), item.get("unit"))
    qty = float(item.get("quantity") or 1)
    inv, whole = _resolve_deduction(db, owner_phone, product, qty, unit)
    stocked = inv is not None and inv.quantity is not None and abs(float(whole or 0) - qty) < 1e-9
    held = None
    if stocked:
        free = free_in_store(db, owner_phone, inv) or 0.0
        keep = business_setting(db, owner_phone, "keep_aside")
        held = min(qty - delivered, max(0.0, free - delivered)) if keep else 0.0
    db.add(TransactionItem(
        transaction_id=tx_id, product=item.get("product"), quantity=qty,
        unit=item.get("unit") or (inv.unit if stocked else None),     # "40 bags still to deliver", not "40"
        unit_price=item.get("unit_price") or 0, total=item.get("total") or 0,
        inventory_item_id=inv.id if inv else None,
        delivered_qty=delivered if stocked or inv is None else None, held_qty=held))
    if not inv:
        return [], [product.title()], []
    out_qty = delivered if stocked else whole
    if out_qty > 0:
        add_inventory_movement(db, owner_phone, inv.name, out_qty, inv.unit, item.get("unit_price"),
                               "OUT", source_type, tx_id, user_id, "Sold")
    left = _format_stock_remaining(float(inv.quantity or 0), inv.unit, inv.retail_unit, inv.retail_per_base)
    update = f"{product.title()}: {left} left"
    if stocked:
        waiting = qty - delivered
        update += (f" · {_num(held)} kept aside for the customer" if held
                   else f" · {_num(waiting)} still owed to the customer")
    return [update], [], []


def receipt_goods_line(db, owner_phone, customer_id):
    rows = goods_to_deliver(db, owner_phone, customer_id)
    if not rows:
        return None
    return "Goods still to deliver:\n" + "\n".join(
        f"• {r['product']}: {_qty(r['remaining'], r['unit'])} (of {_qty(r['bought'], r['unit'])})" for r in rows)


def stock_note(db, owner_phone, item):
    """' · 40 kept aside · 20 free to sell' for the stock reply, or ''."""
    if item is None or item.quantity is None:
        return ""
    kept = reserved_for_item(db, owner_phone, item.id)
    if kept <= 0:
        return ""
    free = max(0.0, float(item.quantity or 0) - kept)
    return f" · {_num(kept)} kept aside for customers · {_num(free)} free to sell"
