"""
Service job confirm flow — handles "John brought 10 shirts, 5 trousers" etc.

After the parser detects the SERVICE_JOB pattern, this module:
  1. Looks up each item's price from the owner's service price list
  2. Builds an itemized breakdown
  3. Creates a SERVICE_JOB_CONFIRM pending action
  4. Handles YES / discount / paid / EDIT replies

Saving records a BUY transaction (customer owes the business the total).
"""

import json
import re

from constants import ACTION_SERVICE_JOB_CONFIRM
from models import Customer, InventoryItem, PendingAction, Transaction

try:
    from sqlalchemy import func as _func
except ImportError:
    _func = None


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Entry: called from webhook_command_router after SERVICE_JOB parse ─────────

def start_service_job_confirm(db, phone, owner_phone, user, parsed, send_message):
    """
    parsed dict from parser.parse_message (type=SERVICE_JOB):
      customer  : str
      raw_items : list of {"qty": int, "name": str}
      paid      : int (0 if none)
    """
    customer_name = (parsed.get("customer") or "").strip().lower()
    raw_items = parsed.get("raw_items") or []
    paid = int(parsed.get("paid") or 0)

    if not customer_name or not raw_items:
        send_message(phone, "Could not understand the job. Try:\nJohn brought 10 shirts, 5 trousers")
        return {"status": "service_job_parse_failed"}

    # Look up prices for each item
    resolved = []
    missing = []
    for ri in raw_items:
        item_name = ri["name"].strip().lower()
        qty = ri["qty"]
        inv = _find_service_item(db, owner_phone, item_name)
        if inv and inv.selling_price:
            unit_price = inv.selling_price
            resolved.append({
                "name": inv.name,
                "unit": inv.unit,
                "qty": qty,
                "unit_price": unit_price,
                "subtotal": qty * unit_price,
            })
        else:
            missing.append({"name": item_name, "qty": qty})

    total = sum(r["subtotal"] for r in resolved)

    # Delete existing pending before creating new one
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    pending = PendingAction(
        phone=phone,
        action=ACTION_SERVICE_JOB_CONFIRM,
        customer_name=customer_name,
    )
    payload = {
        "customer": customer_name,
        "items": resolved,
        "missing": missing,
        "total": total,
        "paid": paid,
        "discount": 0,
    }
    pending.payload_json = json.dumps(payload)
    db.add(pending)
    db.commit()

    msg = _build_job_message(payload)

    if missing:
        names = ", ".join(m["name"].title() for m in missing)
        msg += (
            f"\n\n⚠ *No price set for:* {names}\n"
            f"Set prices: *price [item] [amount]*\n"
            f"Example: price socks 200\n"
            f"Then try again, or reply YES to save without those items."
        )

    send_message(phone, msg)
    return {"status": "service_job_confirm_shown"}


# ── Pending handler ────────────────────────────────────────────────────────────

def handle_service_job_confirm(db, phone, text, pending, user, owner_phone, send_message):
    normalized = text.strip().lower()
    try:
        payload = json.loads(pending.payload_json or "{}")
    except Exception:
        payload = {}

    customer = payload.get("customer", "")
    items = payload.get("items", [])
    total = payload.get("total", 0)
    paid = payload.get("paid", 0)
    discount = payload.get("discount", 0)

    # YES — save
    if normalized in ["yes", "1", "save", "ok", "confirm"]:
        if not items:
            db.delete(pending)
            db.commit()
            send_message(phone, "No items with prices to save. Set prices first.")
            return {"status": "service_job_no_items"}

        final_total = total - discount
        _save_job(db, owner_phone, customer, items, final_total, paid, discount)
        db.delete(pending)
        db.commit()

        balance = final_total - paid
        discount_line = f"  Discount: N{discount:,}\n" if discount else ""
        paid_line = f"  Paid: N{paid:,}\n" if paid else ""
        balance_line = f"  Balance: N{balance:,}" if balance > 0 else "  Fully paid ✓"

        send_message(
            phone,
            f"Saved ✓ — {customer.title()} owes job N{final_total:,}\n"
            f"{discount_line}{paid_line}{balance_line}\n\n"
            f"Send *customer summary {customer}* to see their account."
        )
        return {"status": "service_job_saved"}

    # EDIT — delete and let user retype
    if normalized in ["edit", "2", "change", "redo"]:
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            "Ok. Retype the job:\n"
            "*[name] brought [items]*\n\n"
            "Example: John brought 10 shirts wash and iron, 5 trousers iron only"
        )
        return {"status": "service_job_edit"}

    # CANCEL
    if normalized in ["cancel", "no", "stop", "exit"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Job cancelled.")
        return {"status": "service_job_cancelled"}

    # "discount 500" or "discount: 500"
    disc_m = re.match(r"^discount\s*:?\s*([Nn]?[\d,]+)$", normalized)
    if disc_m:
        disc_val = int(disc_m.group(1).replace(",", "").replace("n", ""))
        if disc_val >= total:
            send_message(phone, f"Discount cannot be equal to or more than the total (N{total:,}).")
            return {"status": "service_job_discount_too_large"}
        payload["discount"] = disc_val
        pending.payload_json = json.dumps(payload)
        db.commit()
        send_message(phone, _build_job_message(payload))
        return {"status": "service_job_discount_applied"}

    # "paid 3000"
    paid_m = re.match(r"^(?:paid|deposit|advance)\s*:?\s*([Nn]?[\d,]+)$", normalized)
    if paid_m:
        paid_val = int(paid_m.group(1).replace(",", "").replace("n", ""))
        payload["paid"] = paid_val
        pending.payload_json = json.dumps(payload)
        db.commit()
        send_message(phone, _build_job_message(payload))
        return {"status": "service_job_paid_updated"}

    # Re-show breakdown
    send_message(phone, _build_job_message(payload))
    return {"status": "service_job_reprompt"}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_job_message(payload):
    customer = payload.get("customer", "")
    items = payload.get("items", [])
    total = payload.get("total", 0)
    paid = payload.get("paid", 0)
    discount = payload.get("discount", 0)
    final_total = total - discount

    lines = [f"Job for *{customer.title()}*:\n"]
    for item in items:
        name = item["name"]
        unit = item.get("unit")
        qty = item["qty"]
        unit_price = item["unit_price"]
        subtotal = item["subtotal"]
        label = f"{name.title()} ({unit})" if unit else name.title()
        lines.append(f"  {qty}× {label}  N{unit_price:,} = N{subtotal:,}")

    lines.append("─" * 28)
    if discount:
        lines.append(f"  Subtotal:  N{total:,}")
        lines.append(f"  Discount:  -N{discount:,}")
        lines.append(f"  *Total:    N{final_total:,}*")
    else:
        lines.append(f"  *Total:    N{final_total:,}*")

    if paid:
        balance = final_total - paid
        lines.append(f"  Paid:      N{paid:,}")
        lines.append(f"  Balance:   N{balance:,}")

    lines.append("\nReply *YES* to save")
    lines.append("*discount [amount]* to apply discount | *paid [amount]* to record deposit")
    lines.append("*EDIT* to retype")
    return "\n".join(lines)


def _find_service_item(db, owner_phone, name_query):
    """Find a service-type InventoryItem by fuzzy name match."""
    nq = _normalize_name(name_query)

    # Fetch all service items for this owner (quantity is None)
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.quantity == None,
        InventoryItem.is_available == True,
    ).all()

    # Step 1: exact match on concatenated name + unit
    for item in items:
        full = _normalize_name(item.name + (" " + item.unit if item.unit else ""))
        if full == nq:
            return item

    # Step 2: query words are a superset of item's words (e.g. "shirt wash iron" contains "shirt" "iron")
    q_words = set(nq.split())
    single_matches = []
    for item in items:
        full = _normalize_name(item.name + (" " + item.unit if item.unit else ""))
        item_words = set(full.split())
        if item_words and item_words <= q_words:
            single_matches.append((len(item_words), item))

    if single_matches:
        # Return the one with the most matching words (most specific)
        single_matches.sort(key=lambda x: -x[0])
        return single_matches[0][1]

    # Step 3: item name alone matches query name
    for item in items:
        if _normalize_name(item.name) == nq:
            return item

    # Step 4: item name is contained in query
    for item in items:
        if _normalize_name(item.name) in nq:
            return item

    return None


def _normalize_name(text):
    """Lowercase, remove &/and ambiguity, collapse spaces."""
    t = (text or "").lower().strip()
    t = re.sub(r"\s*&\s*", " and ", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _save_job(db, owner_phone, customer_name, items, total, paid, discount):
    """Save a service job as a BUY (credit) transaction."""
    # Find or create customer
    customer_name_clean = customer_name.strip().lower()
    customer = db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name == customer_name_clean,
    ).first()
    if not customer:
        customer = Customer(owner_phone=owner_phone, name=customer_name_clean)
        db.add(customer)
        db.flush()

    # Build note with item breakdown
    item_parts = []
    for item in items:
        name = item["name"]
        unit = item.get("unit")
        label = f"{name} ({unit})" if unit else name
        item_parts.append(f"{item['qty']}x {label}")
    note = "Laundry job: " + ", ".join(item_parts)
    if discount:
        note += f" (discount N{discount:,})"

    balance = total - paid
    transaction = Transaction(
        owner_phone=owner_phone,
        customer_name=customer_name_clean,
        action="BUY",
        amount=total,
        paid_amount=paid,
        balance=balance,
        product=note[:200],
        recorded_by_id=None,
    )
    db.add(transaction)
    db.commit()
    return transaction
