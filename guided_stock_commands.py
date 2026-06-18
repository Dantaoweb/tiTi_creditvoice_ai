"""
Guided stock add — catalog Q&A flow.

States (in order):
  GUIDED_STOCK_CATALOG   → show industry product list, user picks a number or types ADD
  GUIDED_STOCK_VARIANT   → one type or multiple sizes?  (or capture free-text product)
  GUIDED_STOCK_QTY       → how many?
  GUIDED_STOCK_COST      → cost price per unit?
  GUIDED_STOCK_SELL      → selling price per unit?
  GUIDED_STOCK_SUPPLIER  → who supplied this? (optional, SKIP allowed)
  GUIDED_STOCK_CONFIRM   → show summary, user says YES or EDIT
  GUIDED_STOCK_ANOTHER   → add another size of same product? YES / DONE

Available on BASIC (no plan gate).
"""

import json

from business_templates import INDUSTRY_PRODUCT_CATALOG, template_key_for_user
from constants import (
    ACTION_GUIDED_STOCK_ANOTHER,
    ACTION_GUIDED_STOCK_BREAKDOWN,
    ACTION_GUIDED_STOCK_CATALOG,
    ACTION_GUIDED_STOCK_CONFIRM,
    ACTION_GUIDED_STOCK_COST,
    ACTION_GUIDED_STOCK_QTY,
    ACTION_GUIDED_STOCK_SELL,
    ACTION_GUIDED_STOCK_SUPPLIER,
    ACTION_GUIDED_STOCK_VARIANT,
)
from inventory_suppliers import find_inventory_item, find_or_create_supplier, manual_stock_add, set_retail_breakdown, upsert_stock_with_prices
from models import PendingAction, SupplierPurchase

# Maximum products shown per catalog page
_CATALOG_PAGE = 10


# ── Payload helpers ───────────────────────────────────────────────────────────

def _load(pending):
    try:
        return json.loads(pending.payload_json or "{}")
    except Exception:
        return {}


def _save(pending, data):
    pending.payload_json = json.dumps(data)


# ── Catalog builder ───────────────────────────────────────────────────────────

def _get_catalog(user):
    """Return a list of product name strings for the user's industry (up to _CATALOG_PAGE)."""
    key = template_key_for_user(user) if user else None
    btype = getattr(user, "business_type", None) if user else None
    entries = (
        INDUSTRY_PRODUCT_CATALOG.get(btype)
        or (INDUSTRY_PRODUCT_CATALOG.get(key, []) if key else [])
    )
    if not entries:
        entries = INDUSTRY_PRODUCT_CATALOG.get("retail_trading", [])
    return [name for name, _cat in entries[:_CATALOG_PAGE]]


def build_catalog_message(catalog, added):
    """Build the numbered product list with checkmarks for already-added items."""
    lines = ["*Choose a product to add to your stock:*\n"]
    for i, name in enumerate(catalog, 1):
        mark = "✓" if name in added else " "
        lines.append(f"{i}. [{mark}] {name.title()}")
    lines.append("")
    lines.append("Reply a *number* to select.")
    lines.append("Reply *ADD* to type a product not on this list.")
    lines.append("Reply *DONE* to finish.")
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def start_guided_stock_flow(db, phone, user, send_message):
    """Kick off the guided flow. Replaces any existing pending."""
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    catalog = _get_catalog(user)
    payload = {"catalog": catalog, "added": [], "current_product": None, "current_unit": None}
    pending = PendingAction(
        phone=phone,
        action=ACTION_GUIDED_STOCK_CATALOG,
        customer_name="",
        last_customer="",
        payload_json=json.dumps(payload),
    )
    db.add(pending)
    db.commit()
    send_message(phone, build_catalog_message(catalog, []))
    return {"status": "guided_stock_started"}


# ── State machine ─────────────────────────────────────────────────────────────

def handle_guided_stock_pending(db, phone, text, pending, user, business_owner_phone, send_message):
    normalized = text.strip().lower()
    action = pending.action
    payload = _load(pending)

    # ── CATALOG: pick a product ───────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_CATALOG:
        catalog = payload.get("catalog", [])
        added = payload.get("added", [])

        if normalized in ["done", "finish", "stop", "exit"]:
            db.delete(pending)
            db.commit()
            count = len(added)
            if count:
                names = ", ".join(n.title() for n in added)
                send_message(phone, f"Done! Added {count} product(s): {names}.\n\nSend *stock* anytime to see your inventory.")
            else:
                send_message(phone, "No products added. Send *add stock* anytime to continue.")
            return {"status": "guided_stock_done"}

        if normalized == "add":
            # Free-text entry: jump straight to variant step with no preset product
            payload["current_product"] = None
            payload["current_unit"] = None
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_VARIANT
            db.commit()
            send_message(
                phone,
                "What is the product name?\n\nExample: Dangote Salt, Coca-Cola, Engine Oil"
            )
            return {"status": "guided_stock_free_name"}

        if normalized.isdigit():
            index = int(normalized) - 1
            if index < 0 or index >= len(catalog):
                send_message(phone, f"Send a number between 1 and {len(catalog)}, or DONE to finish.")
                return {"status": "guided_stock_catalog_out_of_range"}

            product = catalog[index]
            # Check if it already exists in inventory
            existing = find_inventory_item(db, business_owner_phone, product, None)
            payload["current_product"] = product
            payload["current_unit"] = None
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_VARIANT
            db.commit()

            if existing:
                unit_label = f" {existing.unit}" if existing.unit else ""
                sell_label = f"Sell N{existing.selling_price:,}" if existing.selling_price else ""
                send_message(
                    phone,
                    f"*{product.title()}* is already in your stock "
                    f"({existing.quantity:,}{unit_label}{', ' + sell_label if sell_label else ''}).\n\n"
                    "Do you sell a *different size or variant*?\n"
                    "1. Yes — add a different size (e.g. 500g, 1kg)\n"
                    "2. No — update qty/price for existing\n"
                    "3. Skip — go back to list"
                )
            else:
                send_message(
                    phone,
                    f"*{product.title()}* selected.\n\n"
                    "Do you sell *different sizes or packs*?\n"
                    "1. No — just one type\n"
                    "2. Yes — multiple sizes (e.g. sachet, carton, 500g, 1kg)\n\n"
                    "Reply 1 or 2."
                )
            return {"status": "guided_stock_variant_prompt"}

        # Not a number, not ADD, not DONE — re-show list
        send_message(phone, build_catalog_message(catalog, added))
        return {"status": "guided_stock_catalog_reprompt"}

    # ── VARIANT: one type or multiple / free-text product entry ──────────────
    if action == ACTION_GUIDED_STOCK_VARIANT:
        catalog = payload.get("catalog", [])
        current_product = payload.get("current_product")

        # Free-text product name entry (came from ADD)
        if current_product is None:
            if len(normalized) < 2:
                send_message(phone, "Please enter the product name (at least 2 characters).")
                return {"status": "guided_stock_name_too_short"}
            # Treat the reply as the product name
            product = text.strip()
            payload["current_product"] = product.lower()
            payload["current_unit"] = None
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_VARIANT
            db.commit()
            send_message(
                phone,
                f"*{product.title()}* — do you sell different sizes or packs?\n"
                "1. No — just one type\n"
                "2. Yes — multiple sizes (e.g. sachet, carton, 500g, 1kg)\n\n"
                "Reply 1 or 2."
            )
            return {"status": "guided_stock_variant_choice_sent"}

        current_product_title = current_product.title()

        # Existing product: 1=new variant, 2=update existing, 3=skip
        existing = find_inventory_item(db, business_owner_phone, current_product, None)
        if existing and normalized in ["2", "no", "update"]:
            # Update path: skip to qty for the existing item
            payload["current_unit"] = existing.unit
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_QTY
            db.commit()
            unit_label = f" {existing.unit}" if existing.unit else ""
            send_message(phone, f"How many{unit_label} of *{current_product_title}* are you adding to stock now?")
            return {"status": "guided_stock_qty_prompt"}

        if normalized in ["3", "skip", "back"] and existing:
            payload["current_product"] = None
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_CATALOG
            db.commit()
            added = payload.get("added", [])
            send_message(phone, build_catalog_message(catalog, added))
            return {"status": "guided_stock_skip_back"}

        if normalized in ["1", "no", "one", "single", "none"]:
            # One type — no unit
            payload["current_unit"] = None
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_QTY
            db.commit()
            send_message(phone, f"How many *{current_product_title}* do you have in stock right now?")
            return {"status": "guided_stock_qty_prompt"}

        if normalized in ["2", "yes", "multiple", "variants", "sizes"]:
            # Multiple sizes — ask for the first variant name
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_VARIANT
            # Signal that we are now collecting the unit name by setting current_product
            # but clearing current_unit so we know we need unit input next
            payload["_awaiting_unit_name"] = True
            _save(pending, payload)
            db.commit()
            send_message(
                phone,
                f"What is the first size or pack type for *{current_product_title}*?\n\n"
                "Examples: sachet, carton, 500g, 1kg, small, large\n\n"
                "Type the size name:"
            )
            return {"status": "guided_stock_unit_name_prompt"}

        if payload.get("_awaiting_unit_name"):
            # This reply IS the unit/size name
            unit_name = text.strip().lower()
            if len(unit_name) < 1:
                send_message(phone, "Please enter a size or pack name. Example: sachet, carton, 500g")
                return {"status": "guided_stock_unit_name_invalid"}
            payload["current_unit"] = unit_name
            payload["_awaiting_unit_name"] = False
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_QTY
            db.commit()
            send_message(
                phone,
                f"How many *{unit_name}* of *{current_product_title}* do you have in stock right now?\n"
                "Send 0 if none yet."
            )
            return {"status": "guided_stock_qty_prompt"}

        # Unrecognised reply — re-prompt
        send_message(
            phone,
            f"*{current_product_title}* — reply 1 (one type) or 2 (multiple sizes)."
        )
        return {"status": "guided_stock_variant_reprompt"}

    # ── QTY ───────────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_QTY:
        if normalized in ("cancel", "back", "exit", "stop", "skip"):
            payload["current_product"] = None
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_CATALOG
            db.commit()
            added = payload.get("added", [])
            send_message(phone, build_catalog_message(catalog, added))
            return {"status": "guided_stock_skip_back"}
        qty_str = normalized.replace(",", "").split()[0] if normalized.strip() else ""
        if not qty_str.isdigit():
            send_message(phone, "Please send a number. Example: 50\nSend 0 if you have none right now.")
            return {"status": "guided_stock_qty_invalid"}

        payload["qty"] = int(qty_str)
        _save(pending, payload)
        pending.action = ACTION_GUIDED_STOCK_COST
        db.commit()

        product = payload.get("current_product", "")
        unit = payload.get("current_unit")
        unit_label = f" per {unit}" if unit else ""
        send_message(
            phone,
            f"Cost price{unit_label} for *{product.title()}*?\n"
            "(What you paid when buying it)\n\n"
            "Send 0 or SKIP if you don't track cost."
        )
        return {"status": "guided_stock_cost_prompt"}

    # ── COST ──────────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_COST:
        if normalized in ["skip", "0", "no", "none"]:
            payload["cost"] = 0
        else:
            cost_str = normalized.replace(",", "").replace("n", "").strip()
            if not cost_str.replace(".", "").isdigit():
                send_message(phone, "Please send an amount. Example: 500\nOr send SKIP to skip.")
                return {"status": "guided_stock_cost_invalid"}
            payload["cost"] = int(float(cost_str))

        _save(pending, payload)
        pending.action = ACTION_GUIDED_STOCK_SELL
        db.commit()

        product = payload.get("current_product", "")
        unit = payload.get("current_unit")
        unit_label = f" per {unit}" if unit else ""
        send_message(
            phone,
            f"Selling price{unit_label} for *{product.title()}*?\n"
            "(What you charge your customers)"
        )
        return {"status": "guided_stock_sell_prompt"}

    # ── SELL ──────────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_SELL:
        sell_str = normalized.replace(",", "").replace("n", "").strip()
        if not sell_str.replace(".", "").isdigit():
            send_message(phone, "Please send an amount. Example: 700")
            return {"status": "guided_stock_sell_invalid"}

        sell = int(float(sell_str))
        payload["sell"] = sell
        payload["warn_margin"] = sell < payload.get("cost", 0) and payload.get("cost", 0) > 0
        _save(pending, payload)
        pending.action = ACTION_GUIDED_STOCK_BREAKDOWN
        db.commit()

        product = payload.get("current_product", "")
        unit = payload.get("current_unit") or "unit"
        send_message(
            phone,
            f"Does *{product.title()}* also sell in smaller pieces?\n\n"
            f"*Examples:*\n"
            f"• 30 eggs in a crate at N70 each → *egg 30 70*\n"
            f"• 32 congos in a bag at N1400 each → *congo 32 1400*\n"
            f"• 9 cups in a congo at N160 each → *cup 9 160*\n\n"
            f"Reply with: *unit  how-many  price*\n"
            f"Or send *SKIP* if you only sell by the whole {unit or 'unit'}."
        )
        return {"status": "guided_stock_breakdown_prompt"}

    # ── BREAKDOWN ─────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_BREAKDOWN:
        product = payload.get("current_product", "")
        unit = payload.get("current_unit")

        if normalized in ["skip", "no", "none", "0", "-", "n"]:
            payload["retail_unit"] = None
            payload["retail_per_base"] = None
            payload["retail_price"] = None
        else:
            # Parse "egg 30 70" or "congo 32" (price optional)
            parts = normalized.replace(",", "").split()
            if len(parts) < 2 or not parts[1].isdigit():
                send_message(
                    phone,
                    "Please reply with: *unit  how-many  price*\n"
                    "Example: *egg 30 70* (30 eggs per unit at ₦70 each)\n"
                    "Or send *SKIP*."
                )
                return {"status": "guided_stock_breakdown_invalid"}
            ret_unit = parts[0].strip()
            ret_per = int(parts[1])
            ret_price = int(parts[2].replace("n", "").strip()) if len(parts) >= 3 and parts[2].replace("n", "").strip().isdigit() else None
            payload["retail_unit"] = ret_unit
            payload["retail_per_base"] = ret_per
            payload["retail_price"] = ret_price

        _save(pending, payload)
        pending.action = ACTION_GUIDED_STOCK_SUPPLIER
        db.commit()

        send_message(
            phone,
            f"Who supplied *{product.title()}*?\n\n"
            "Send the supplier name (e.g. *Dangote Distributor*)\n"
            "or send *SKIP* if you don't track this."
        )
        return {"status": "guided_stock_supplier_prompt"}

    # ── SUPPLIER ─────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_SUPPLIER:
        if normalized in ["skip", "no", "none", "0", "-"]:
            payload["supplier"] = None
        else:
            supplier_name = text.strip()
            if len(supplier_name) < 2:
                product = payload.get("current_product", "")
                send_message(
                    phone,
                    f"Who supplied *{product.title()}*?\n"
                    "Send supplier name or *SKIP*."
                )
                return {"status": "guided_stock_supplier_invalid"}
            payload["supplier"] = supplier_name

        warn = payload.pop("warn_margin", False)
        _save(pending, payload)
        pending.action = ACTION_GUIDED_STOCK_CONFIRM
        db.commit()
        _send_confirm(phone, payload, send_message, warn_margin=warn)
        return {"status": "guided_stock_confirm_prompt"}

    # ── CONFIRM ───────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_CONFIRM:
        if normalized in ["yes", "1", "save", "ok", "confirm"]:
            _do_save(db, business_owner_phone, payload)
            db.commit()

            product = payload.get("current_product", "")
            unit = payload.get("current_unit")
            qty = payload.get("qty", 0)
            sell = payload.get("sell", 0)
            unit_label = f" {unit}" if unit else ""

            added = payload.get("added", [])
            if product not in added:
                added.append(product)
            payload["added"] = added

            pending.action = ACTION_GUIDED_STOCK_ANOTHER
            _save(pending, payload)
            db.commit()

            send_message(
                phone,
                f"Saved ✓ *{product.title()}{(' ' + unit) if unit else ''}*\n"
                f"Qty: {qty:,}{unit_label}  |  Sell: N{sell:,}\n\n"
                f"Add another size of *{product.title()}*?\n"
                "Reply *YES* to add another size.\n"
                "Reply *DONE* to go back to the product list."
            )
            return {"status": "guided_stock_saved"}

        if normalized in ["edit", "2", "change"]:
            pending.action = ACTION_GUIDED_STOCK_QTY
            db.commit()
            product = payload.get("current_product", "")
            unit = payload.get("current_unit")
            unit_label = f" per {unit}" if unit else ""
            send_message(
                phone,
                f"How many *{product.title()}* do you have in stock right now?"
            )
            return {"status": "guided_stock_edit"}

        _send_confirm(phone, payload, send_message)
        return {"status": "guided_stock_confirm_reprompt"}

    # ── ANOTHER VARIANT ───────────────────────────────────────────────────────
    if action == ACTION_GUIDED_STOCK_ANOTHER:
        product = payload.get("current_product", "")
        catalog = payload.get("catalog", [])
        added = payload.get("added", [])

        if normalized in ["yes", "1", "y", "add"]:
            # Add another size of the same product
            payload["current_unit"] = None
            payload["_awaiting_unit_name"] = True
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_VARIANT
            db.commit()
            send_message(
                phone,
                f"Next size for *{product.title()}*?\n\n"
                "Examples: carton, 1kg, large, 50cl\n\nType the size name:"
            )
            return {"status": "guided_stock_another_variant"}

        if normalized in ["done", "no", "2", "next", "finish", "back"]:
            # Return to catalog
            payload["current_product"] = None
            payload["current_unit"] = None
            _save(pending, payload)
            pending.action = ACTION_GUIDED_STOCK_CATALOG
            db.commit()
            send_message(phone, build_catalog_message(catalog, added))
            return {"status": "guided_stock_back_to_catalog"}

        send_message(
            phone,
            f"Add another size of *{product.title()}*?\n"
            "Reply *YES* or *DONE* to go back to the list."
        )
        return {"status": "guided_stock_another_reprompt"}

    return None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _send_confirm(phone, payload, send_message, warn_margin=False):
    product = payload.get("current_product", "")
    unit = payload.get("current_unit")
    qty = payload.get("qty", 0)
    cost = payload.get("cost", 0)
    sell = payload.get("sell", 0)
    supplier = payload.get("supplier")
    ret_unit = payload.get("retail_unit")
    ret_per = payload.get("retail_per_base")
    ret_price = payload.get("retail_price")

    unit_label = f" {unit}" if unit else ""
    cost_line = f"Cost: N{cost:,}" if cost else "Cost: not set"
    supplier_line = f"\nSupplier: {supplier.title()}" if supplier else ""
    margin_warn = "\n\n⚠ Selling price is below cost price." if warn_margin else ""
    breakdown_line = ""
    if ret_unit and ret_per:
        bp = f" at N{ret_price:,} each" if ret_price else ""
        breakdown_line = f"\nRetail: {ret_per} {ret_unit} per {unit or 'unit'}{bp}"

    msg = (
        f"Confirm stock item:\n\n"
        f"Product: *{product.title()}{unit_label}*\n"
        f"Qty: {qty:,}\n"
        f"{cost_line}\n"
        f"Sell: N{sell:,}"
        f"{breakdown_line}"
        f"{supplier_line}"
        f"{margin_warn}\n\n"
        "Reply *YES* to save or *EDIT* to change."
    )
    send_message(phone, msg)


def _do_save(db, owner_phone, payload):
    product = payload.get("current_product", "")
    unit = payload.get("current_unit")
    qty = payload.get("qty", 0)
    cost = payload.get("cost", 0)
    sell = payload.get("sell", 0)
    supplier_name = payload.get("supplier")

    # Set/update prices
    item = upsert_stock_with_prices(db, owner_phone, product, unit, cost, sell)
    db.flush()

    # Save retail breakdown config if provided
    ret_unit = payload.get("retail_unit")
    ret_per = payload.get("retail_per_base")
    ret_price = payload.get("retail_price")
    if ret_unit and ret_per:
        item.retail_unit = ret_unit
        item.retail_per_base = int(ret_per)
        if ret_price is not None:
            item.retail_price = int(ret_price)
            if not item.selling_price:
                item.selling_price = int(ret_price)

    if qty > 0:
        if supplier_name:
            # Link to supplier — record as a supplier purchase
            supplier = find_or_create_supplier(db, owner_phone, supplier_name)
            db.flush()
            total = cost * qty if cost else 0
            purchase = SupplierPurchase(
                supplier_id=supplier.id,
                owner_phone=owner_phone,
                product=product,
                quantity=qty,
                unit=unit,
                unit_price=cost if cost else None,
                total=total,
                paid_amount=total,  # opening stock is already owned — no debt owed
            )
            db.add(purchase)
            db.flush()
            manual_stock_add(db, owner_phone, product, qty, unit, None, f"Opening stock via {supplier_name.title()}")
        else:
            manual_stock_add(db, owner_phone, product, qty, unit, None, "Opening stock")
