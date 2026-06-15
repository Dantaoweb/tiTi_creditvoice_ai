import json
import re

from models import PendingAction, ReminderMemory
from reports import get_product_buyers


def _build_restock_message(customer_name, product_name, business_name):
    biz = f" at {business_name.title()}" if business_name else ""
    return (
        f"Hello {customer_name.title()},\n\n"
        f"Good news! {product_name.title()} is back in stock{biz}.\n\n"
        "Come get yours or reach out to reserve."
    )


def _save_restock_queue(db, phone, buyers):
    db.query(ReminderMemory).filter(
        ReminderMemory.phone == phone,
        ReminderMemory.reminder_type == "RESTOCK_ALERT",
    ).delete()
    for b in buyers:
        db.add(ReminderMemory(
            phone=phone,
            customer_id=b["customer_id"],
            customer_name=b["name"],
            customer_phone=b.get("customer_phone") or b.get("phone"),
            balance=0,
            due_date=None,
            reminder_type="RESTOCK_ALERT",
        ))


def _next_in_queue(db, phone):
    return (
        db.query(ReminderMemory)
        .filter(
            ReminderMemory.phone == phone,
            ReminderMemory.reminder_type == "RESTOCK_ALERT",
        )
        .order_by(ReminderMemory.id)
        .first()
    )


def _queue_count(db, phone):
    return (
        db.query(ReminderMemory)
        .filter(
            ReminderMemory.phone == phone,
            ReminderMemory.reminder_type == "RESTOCK_ALERT",
        )
        .count()
    )


def _show_next_preview(db, phone, pending, send_message):
    nxt = _next_in_queue(db, phone)
    if not nxt:
        db.delete(pending)
        db.commit()
        send_message(phone, "All restock alerts sent.")
        return {"status": "restock_queue_done"}

    remaining = _queue_count(db, phone)
    product = pending.product or "this item"
    # business_name stored in pending.customer_phone (reusing the field as scratch space)
    business_name = pending.customer_phone or ""
    preview = _build_restock_message(nxt.customer_name, product, business_name)

    send_message(
        phone,
        f"Preview ({remaining} remaining):\n\n"
        f"To: {nxt.customer_name.title()} ({nxt.customer_phone})\n\n"
        f"{preview}\n\n"
        "YES to send  •  SKIP to skip  •  STOP to cancel all"
    )
    return {"status": "restock_preview"}


def _supplier_hint(db, business_owner_phone, product_name):
    """Short one-line supplier summary for the restock opening menu."""
    try:
        from inventory_suppliers import get_product_suppliers
        suppliers = get_product_suppliers(db, business_owner_phone, product_name)
        if not suppliers:
            return ""
        lines = []
        for s in suppliers[:3]:
            price_part = ""
            if s["last_unit_price"]:
                unit_label = f"/{s['last_unit']}" if s["last_unit"] else ""
                price_part = f" N{s['last_unit_price']:,}{unit_label}"
            date_part = f" {s['last_date'].strftime('%d/%m')}" if s["last_date"] else ""
            lines.append(f"• {s['name'].title()}{price_part}{date_part}")
        return "Usual suppliers:\n" + "\n".join(lines) + "\n\n"
    except Exception:
        return ""


def handle_restock_command(db, phone, product_name, user, business_owner_phone, visible_recorded_by_id, send_message):
    buyers = get_product_buyers(db, business_owner_phone, product_name, visible_recorded_by_id)

    with_phone = [b for b in buyers if b["customer_phone"]]
    without_phone = [b for b in buyers if not b["customer_phone"]]
    supplier_hint = _supplier_hint(db, business_owner_phone, product_name)

    if not buyers and not supplier_hint:
        send_message(
            phone,
            f"No recorded buyers or supplier history for {product_name.title()} yet.\n\n"
            "Buyers appear when customers purchase this product.\n"
            "Supplier history appears when you record a supplier delivery."
        )
        return {"status": "no_buyers"}

    msg = f"{product_name.title()} — Restock\n\n"
    if supplier_hint:
        msg += supplier_hint
    if buyers:
        msg += (
            f"Buyers: {len(buyers)} customer(s)\n"
            f"Can notify: {len(with_phone)} (have WhatsApp number)\n"
            f"No number saved: {len(without_phone)}\n\n"
        )
    else:
        msg += "No buyers recorded yet.\n\n"

    if with_phone:
        msg += (
            "Send a restock alert to your buyers?\n\n"
            f"1. Notify all {len(with_phone)} customers\n"
            "2. Pick specific customers\n"
            "3. Show full buyer list\n"
            "4. Cancel"
        )
    else:
        msg += (
            "None of your buyers have a WhatsApp number saved.\n"
            "Add a number with: [name] phone 08012345678\n\n"
            "3. Show full buyer list\n"
            "4. Cancel"
        )

    business_name = getattr(user, "name", "") or ""

    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    db.add(PendingAction(
        phone=phone,
        action="PRODUCT_BUYERS_MENU",
        customer_name="",
        last_customer="",
        product=product_name.lower().strip(),
        # Reuse customer_phone field to carry business name for the message template
        customer_phone=business_name,
    ))
    db.commit()
    send_message(phone, msg)
    return {"status": "product_buyers_menu"}


def handle_product_buyers_menu(db, phone, text, pending, business_owner_phone, visible_recorded_by_id, send_message):
    normalized = text.strip().lower()
    product = pending.product or ""

    if normalized in ["4", "cancel", "back", "stop", "exit"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Cancelled.")
        return {"status": "restock_cancelled"}

    buyers = get_product_buyers(db, business_owner_phone, product, visible_recorded_by_id)
    with_phone = [b for b in buyers if b["customer_phone"]]

    if normalized in ["1", "all", "notify all", "send all"]:
        if not with_phone:
            send_message(phone, "No buyers with phone numbers. Add numbers first: [name] phone 08012345678")
            return {"status": "restock_no_phones"}
        _save_restock_queue(db, phone, with_phone)
        db.commit()
        pending.action = "RESTOCK_ALERT_CONFIRM"
        db.commit()
        return _show_next_preview(db, phone, pending, send_message)

    if normalized in ["2", "pick", "select", "choose"]:
        if not with_phone:
            send_message(phone, "No buyers with phone numbers. Add numbers first: [name] phone 08012345678")
            return {"status": "restock_no_phones"}
        msg = f"{product.title()} — Select customers to notify\n\n"
        for i, b in enumerate(with_phone, start=1):
            count = b["buy_count"]
            times = "time" if count == 1 else "times"
            msg += f"{i}. {b['name'].title()} ({b['customer_phone']}) — {count} {times}\n"
        msg += "\nReply with numbers separated by comma.\nExample: 1,3,5\nOr ALL for everyone."
        pending.items_json = json.dumps([
            {"customer_id": b["customer_id"], "name": b["name"], "customer_phone": b["customer_phone"]}
            for b in with_phone
        ])
        pending.action = "RESTOCK_ALERT_SELECT"
        db.commit()
        send_message(phone, msg)
        return {"status": "restock_select_list"}

    if normalized in ["3", "list", "show", "show list"]:
        db.delete(pending)
        db.commit()
        msg = f"{product.title()} — All Buyers\n\n"
        for i, b in enumerate(buyers, start=1):
            phone_label = b["customer_phone"] or "no phone"
            count = b["buy_count"]
            times = "time" if count == 1 else "times"
            msg += f"{i}. {b['name'].title()} ({phone_label}) — {count} {times}\n"
        if not buyers:
            msg += "No buyers recorded yet."
        send_message(phone, msg)
        return {"status": "restock_list_shown"}

    send_message(phone, "Reply 1 to notify all, 2 to pick, 3 to see list, or 4 to cancel.")
    return {"status": "restock_menu_invalid"}


def handle_restock_alert_select(db, phone, text, pending, send_message):
    normalized = text.strip().lower()
    all_buyers = json.loads(pending.items_json or "[]")

    if normalized in ["all"]:
        selected = all_buyers
    else:
        parts = [p.strip() for p in re.split(r"[,\s]+", text.strip()) if p.strip()]
        selected = []
        for p in parts:
            if p.isdigit():
                idx = int(p) - 1
                if 0 <= idx < len(all_buyers):
                    selected.append(all_buyers[idx])

        if not selected:
            send_message(
                phone,
                "No valid selections. Reply with numbers like: 1,3,5\nOr ALL for everyone.\nOr BACK to cancel."
            )
            return {"status": "restock_select_invalid"}

    _save_restock_queue(db, phone, selected)
    db.commit()
    pending.action = "RESTOCK_ALERT_CONFIRM"
    db.commit()
    return _show_next_preview(db, phone, pending, send_message)


def handle_restock_alert_confirm(db, phone, text, pending, user, send_message):
    normalized = text.strip().lower()

    if normalized == "stop":
        remaining = _queue_count(db, phone)
        db.query(ReminderMemory).filter(
            ReminderMemory.phone == phone,
            ReminderMemory.reminder_type == "RESTOCK_ALERT",
        ).delete()
        db.delete(pending)
        db.commit()
        send_message(phone, f"Stopped. {remaining} customer(s) not notified.")
        return {"status": "restock_stopped"}

    nxt = _next_in_queue(db, phone)
    if not nxt:
        db.delete(pending)
        db.commit()
        send_message(phone, "All done.")
        return {"status": "restock_queue_done"}

    if normalized in ["yes", "1", "send"]:
        product = pending.product or "this item"
        business_name = pending.customer_phone or (getattr(user, "name", "") or "")
        msg = _build_restock_message(nxt.customer_name, product, business_name)
        send_message(nxt.customer_phone, msg)
        db.delete(nxt)
        db.commit()
        return _show_next_preview(db, phone, pending, send_message)

    if normalized in ["skip", "next", "no", "s"]:
        db.delete(nxt)
        db.commit()
        return _show_next_preview(db, phone, pending, send_message)

    send_message(phone, "Reply YES to send, SKIP to skip this customer, or STOP to cancel all.")
    return {"status": "restock_confirm_waiting"}
