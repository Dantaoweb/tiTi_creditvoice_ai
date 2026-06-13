"""
Guided service price list setup.

States:
  GUIDED_SERVICE_SETUP      → show price list with defaults; user confirms or edits
  GUIDED_SERVICE_EDIT_PRICE → edit a specific item's price
  GUIDED_SERVICE_ADD_NAME   → add a new custom service (enter name)
  GUIDED_SERVICE_ADD_PRICE  → add price (and optional further tiers) for new service

Available on BASIC (no plan gate).
"""

import json
import re

from business_templates import service_price_catalog_for_user
from constants import (
    ACTION_GUIDED_SERVICE_ADD_NAME,
    ACTION_GUIDED_SERVICE_ADD_PRICE,
    ACTION_GUIDED_SERVICE_EDIT_PRICE,
    ACTION_GUIDED_SERVICE_SETUP,
)
from models import InventoryItem, PendingAction

try:
    from sqlalchemy import func
except ImportError:
    func = None


_PAGE_SIZE = 12


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _save(pending, payload):
    pending.payload_json = json.dumps(payload)


def _load(pending):
    try:
        return json.loads(pending.payload_json or "{}")
    except Exception:
        return {}


# ── Entry point ───────────────────────────────────────────────────────────────

def start_guided_service_setup(db, phone, user, send_message):
    """Begin the service price list setup flow."""
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()

    raw_catalog = service_price_catalog_for_user(user)
    items = [
        {"name": n, "unit": u, "price": p, "skip": False}
        for n, u, p in raw_catalog
    ]

    pending = PendingAction(phone=phone, action=ACTION_GUIDED_SERVICE_SETUP)
    payload = {"items": items, "page": 0}
    db.add(pending)
    db.flush()
    _save(pending, payload)
    db.commit()

    if not items:
        send_message(
            phone,
            "No default price list for your business type.\n\n"
            "Reply ADD to add your first service price.\n"
            "Example: haircut 500"
        )
        return {"status": "guided_service_empty_catalog"}

    send_message(phone, _build_page_message(items, page=0))
    return {"status": "guided_service_started"}


# ── Main handler ──────────────────────────────────────────────────────────────

def handle_guided_service_pending(db, phone, text, pending, user, owner_phone, send_message):
    action = pending.action
    normalized = text.strip().lower()
    payload = _load(pending)

    # ── SETUP — main list ─────────────────────────────────────────────────────
    if action == ACTION_GUIDED_SERVICE_SETUP:
        items = payload.get("items", [])
        page = payload.get("page", 0)

        if normalized in ["done", "yes", "save", "ok", "confirm", "finish"]:
            saved = _save_service_items(db, owner_phone, items)
            db.delete(pending)
            db.commit()
            if saved == 0:
                send_message(phone, "Nothing saved. Send ADD to add service prices.")
                return {"status": "guided_service_nothing_saved"}
            send_message(
                phone,
                f"Price list saved ✓ ({saved} item{'s' if saved != 1 else ''}).\n\n"
                "When a customer brings items, type:\n"
                "*[name] brought [items]*\n\n"
                "Example: John brought 10 shirts, 5 trousers\n\n"
                "Send *price list* anytime to view or update prices."
            )
            return {"status": "guided_service_saved"}

        if normalized in ["next", "more", "n"]:
            total_pages = _total_pages(len(items))
            new_page = (page + 1) % total_pages
            payload["page"] = new_page
            _save(pending, payload)
            db.commit()
            send_message(phone, _build_page_message(items, new_page))
            return {"status": "guided_service_next_page"}

        if normalized in ["back", "prev"]:
            new_page = max(0, page - 1)
            payload["page"] = new_page
            _save(pending, payload)
            db.commit()
            send_message(phone, _build_page_message(items, new_page))
            return {"status": "guided_service_prev_page"}

        if normalized in ["add", "new"]:
            _save(pending, payload)
            pending.action = ACTION_GUIDED_SERVICE_ADD_NAME
            db.commit()
            send_message(
                phone,
                "What service do you want to add?\n\n"
                "Type the full service name. If it has tiers, include the tier:\n"
                "Examples: *express ironing*, *shirt wash & dry*, *AC regas*"
            )
            return {"status": "guided_service_add_name_prompt"}

        if normalized in ["cancel", "exit", "skip setup"]:
            db.delete(pending)
            db.commit()
            send_message(phone, "Price list setup closed. Send *price list* to continue later.")
            return {"status": "guided_service_cancelled"}

        # Skip an item: "skip 3"
        skip_m = re.match(r"^skip\s+(\d+)$", normalized)
        if skip_m:
            idx = int(skip_m.group(1)) - 1
            if 0 <= idx < len(items):
                items[idx]["skip"] = not items[idx].get("skip", False)
                payload["items"] = items
                _save(pending, payload)
                db.commit()
                action_word = "Removed" if items[idx]["skip"] else "Restored"
                name = items[idx]["name"]
                unit = items[idx].get("unit")
                label = f"{name.title()} ({unit})" if unit else name.title()
                send_message(phone, f"{action_word} *{label}* from your list.\n\n" + _build_page_message(items, page))
            else:
                send_message(phone, f"No item {idx+1}. Send a valid number.")
            return {"status": "guided_service_skip_toggle"}

        # Edit an item by number
        if normalized.isdigit():
            idx = int(normalized) - 1
            if 0 <= idx < len(items):
                item = items[idx]
                payload["editing_index"] = idx
                _save(pending, payload)
                pending.action = ACTION_GUIDED_SERVICE_EDIT_PRICE
                db.commit()
                name = item["name"]
                unit = item.get("unit")
                price = item["price"]
                label = f"{name.title()} ({unit})" if unit else name.title()
                send_message(
                    phone,
                    f"*{label}*\nCurrent price: N{price:,}\n\n"
                    "Type new price, or *SKIP* to remove this item from your list."
                )
                return {"status": "guided_service_edit_prompt"}
            else:
                send_message(phone, f"No item {idx+1}. Send a number from the list.\n\n" + _build_page_message(items, page))
                return {"status": "guided_service_invalid_number"}

        send_message(phone, _build_page_message(items, page))
        return {"status": "guided_service_reprompt"}

    # ── EDIT PRICE ────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_SERVICE_EDIT_PRICE:
        items = payload.get("items", [])
        idx = payload.get("editing_index", 0)
        page = payload.get("page", 0)

        if normalized in ["skip", "remove", "delete"]:
            items[idx]["skip"] = True
            payload["items"] = items
            _save(pending, payload)
            pending.action = ACTION_GUIDED_SERVICE_SETUP
            db.commit()
            name = items[idx]["name"]
            unit = items[idx].get("unit")
            label = f"{name.title()} ({unit})" if unit else name.title()
            send_message(phone, f"*{label}* removed.\n\n" + _build_page_message(items, page))
            return {"status": "guided_service_item_skipped"}

        if normalized in ["back", "cancel", "done", "finish", "menu", "skip this"]:
            pending.action = ACTION_GUIDED_SERVICE_SETUP
            db.commit()
            send_message(phone, _build_page_message(items, page))
            return {"status": "guided_service_edit_back"}

        price_str = normalized.replace(",", "").replace("n", "").strip()
        if not price_str.isdigit():
            name = items[idx]["name"]
            unit = items[idx].get("unit")
            label = f"{name.title()} ({unit})" if unit else name.title()
            send_message(phone, f"Please send a number for *{label}* price, or SKIP to remove it.")
            return {"status": "guided_service_edit_invalid"}

        items[idx]["price"] = int(price_str)
        payload["items"] = items
        _save(pending, payload)
        pending.action = ACTION_GUIDED_SERVICE_SETUP
        db.commit()
        send_message(phone, _build_page_message(items, page))
        return {"status": "guided_service_price_updated"}

    # ── ADD NAME ──────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_SERVICE_ADD_NAME:
        name_raw = text.strip()
        if len(name_raw) < 2:
            send_message(phone, "Please type the service name. Example: *express ironing*")
            return {"status": "guided_service_add_name_invalid"}

        payload["new_item_name"] = name_raw.lower()
        payload["new_item_tiers"] = []
        _save(pending, payload)
        pending.action = ACTION_GUIDED_SERVICE_ADD_PRICE
        db.commit()
        send_message(
            phone,
            f"Price for *{name_raw.title()}*?\n\n"
            "Just type the amount. Or to add tiers, type:\n"
            "*tier name: price*\n"
            "Example: *iron only: 400*\n\n"
            "After the first price, you can add more tiers."
        )
        return {"status": "guided_service_add_price_prompt"}

    # ── ADD PRICE ─────────────────────────────────────────────────────────────
    if action == ACTION_GUIDED_SERVICE_ADD_PRICE:
        items = payload.get("items", [])
        new_name = payload.get("new_item_name", "")
        tiers_so_far = payload.get("new_item_tiers", [])

        if normalized in ["done", "finish", "no", "nope"]:
            if not tiers_so_far:
                send_message(phone, f"No price added for *{new_name.title()}*. Type a price or CANCEL.")
                return {"status": "guided_service_add_no_price"}
            payload["new_item_name"] = None
            payload["new_item_tiers"] = []
            payload["items"] = items
            _save(pending, payload)
            pending.action = ACTION_GUIDED_SERVICE_SETUP
            db.commit()
            send_message(phone, _build_page_message(items, payload.get("page", 0)))
            return {"status": "guided_service_add_done"}

        if normalized in ["cancel", "back"]:
            payload["new_item_name"] = None
            payload["new_item_tiers"] = []
            _save(pending, payload)
            pending.action = ACTION_GUIDED_SERVICE_SETUP
            db.commit()
            send_message(phone, _build_page_message(items, payload.get("page", 0)))
            return {"status": "guided_service_add_cancelled"}

        # Try "tier: price" or "tier price" format (e.g. "iron only: 500" or "iron only 500")
        tier_price_m = re.match(r"^(.+?):\s*([Nn]?[\d,]+)\s*$", text.strip())
        if not tier_price_m:
            # Also accept "words number" without colon — last token is the price
            tier_price_m = re.match(r"^([a-zA-Z][a-zA-Z\s&]+?)\s+([Nn]?[\d,]+)\s*$", text.strip())
        if tier_price_m:
            tier_label = tier_price_m.group(1).strip().lower()
            price_str = tier_price_m.group(2).replace(",", "").replace("n", "").replace("N", "")
            if price_str.isdigit():
                price = int(price_str)
                items.append({"name": new_name, "unit": tier_label, "price": price, "skip": False})
                tiers_so_far.append(tier_label)
                payload["items"] = items
                payload["new_item_tiers"] = tiers_so_far
                _save(pending, payload)
                db.commit()
                send_message(
                    phone,
                    f"Added *{new_name.title()} ({tier_label})* — N{price:,}\n\n"
                    "Add another tier? Type *tier: price* or *DONE*."
                )
                return {"status": "guided_service_tier_added"}

        # Plain number — single price, no tier
        price_str = normalized.replace(",", "").replace("n", "").strip()
        if price_str.isdigit():
            price = int(price_str)
            unit = None
            items.append({"name": new_name, "unit": unit, "price": price, "skip": False})
            tiers_so_far.append("_single")
            payload["items"] = items
            payload["new_item_tiers"] = tiers_so_far
            _save(pending, payload)
            db.commit()
            send_message(
                phone,
                f"Added *{new_name.title()}* — N{price:,}\n\n"
                "Add another tier? Example: *iron only: 400* or *DONE*."
            )
            return {"status": "guided_service_price_added"}

        send_message(
            phone,
            f"Type a price for *{new_name.title()}*.\n"
            "Plain number (e.g. 1500) or tier format (e.g. iron only: 400).\n"
            "Type DONE to finish."
        )
        return {"status": "guided_service_add_price_invalid"}

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _total_pages(item_count):
    return max(1, (item_count + _PAGE_SIZE - 1) // _PAGE_SIZE)


def _build_page_message(items, page=0):
    start = page * _PAGE_SIZE
    end = start + _PAGE_SIZE
    page_items = items[start:end]
    total_pages = _total_pages(len(items))

    lines = [f"Service price list (page {page + 1}/{total_pages}):\n"]
    for i, item in enumerate(page_items, start=start + 1):
        name = item["name"]
        unit = item.get("unit")
        price = item["price"]
        removed = item.get("skip", False)
        label = f"{name.title()} ({unit})" if unit else name.title()
        if removed:
            lines.append(f"✗{i}. {label} — removed")
        else:
            lines.append(f"{i}. {label}: N{price:,}")

    footer_parts = ["Reply *YES* to save all | *number* to edit"]
    footer_parts.append("*skip [number]* to remove an item")
    if total_pages > 1:
        footer_parts.append("*NEXT* for more")
    footer_parts.append("*ADD* to add your own")
    footer_parts.append("*DONE* to save & finish")

    lines.append("\n" + " | ".join(footer_parts[:2]))
    lines.append(" | ".join(footer_parts[2:]))
    return "\n".join(lines)


def _save_service_items(db, owner_phone, items):
    """Upsert InventoryItem records for service items. Returns count saved."""
    saved = 0
    for item in items:
        if item.get("skip"):
            continue
        name = item["name"].lower().strip()
        unit = item.get("unit")
        price = item.get("price", 0)
        if not name or not price:
            continue

        if func:
            existing = db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner_phone,
                func.lower(InventoryItem.name) == name,
                InventoryItem.unit == unit,
            ).first()
        else:
            existing = db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner_phone,
                InventoryItem.name == name,
                InventoryItem.unit == unit,
            ).first()

        if existing:
            existing.selling_price = price
            existing.is_available = True
        else:
            db.add(InventoryItem(
                owner_phone=owner_phone,
                name=name,
                unit=unit,
                quantity=None,
                selling_price=price,
                cost_price=None,
                is_available=True,
                category="service",
            ))
        saved += 1

    db.commit()
    return saved
