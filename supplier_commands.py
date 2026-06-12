import json
import re

from inventory_suppliers import (
    build_inventory_list_message,
    build_supplier_due_message,
    build_supplier_list_message,
    manual_stock_add,
    manual_stock_remove,
    manual_stock_set,
    set_low_stock_alert,
    upsert_stock_with_prices,
)
from business_templates import build_stock_add_guide
from constants import ACTION_STOCK_MENU
from guided_stock_commands import build_catalog_message, start_guided_stock_flow
from messages import apply_voice_confirmation_options
from models import InventoryItem, PendingAction
from parser import parse_stock_item_body
from subscriptions import ensure_feature_allowed

# Items shown to BASIC users in the limited stock preview
_BASIC_STOCK_LIMIT = 5


def _can_modify_stock(user):
    """
    Only the business owner or a staff member with full access may remove
    or adjust stock. Limited-access staff (own records only) are blocked.
    """
    if not user:
        return False
    if user.parent_id is None:
        return True  # owner
    return bool(user.can_view_all_transactions)  # full-access staff


def handle_supplier_command(
    db,
    phone,
    parsed,
    user,
    business_owner_phone,
    voice_transcript_text,
    send_message,
):
    command_type = parsed.get("type")

    if command_type in ["INVENTORY_LIST", "INVENTORY_ITEM"]:
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
        is_basic = not allowed  # BASIC users get limited preview, not a hard block

        product_filter = parsed.get("product")

        if is_basic and not product_filter:
            # BASIC: show first 5 items as a preview + guided add prompt
            from sqlalchemy import func as _func
            items = (
                db.query(InventoryItem)
                .filter(InventoryItem.owner_phone == business_owner_phone)
                .order_by(InventoryItem.name.asc())
                .limit(_BASIC_STOCK_LIMIT)
                .all()
            )
            total_count = (
                db.query(InventoryItem)
                .filter(InventoryItem.owner_phone == business_owner_phone)
                .count()
            )
            if not items:
                msg = (
                    "You have no stock yet.\n\n"
                    "Reply *ADD* to add your first product step by step."
                )
            else:
                lines = ["*Your Stock (preview)*\n"]
                for i, it in enumerate(items, 1):
                    unit_label = f" {it.unit}" if it.unit else ""
                    sell = f"  Sell N{it.selling_price:,}" if it.selling_price else ""
                    lines.append(f"{i}. {it.name.title()}: {it.quantity or 0:,}{unit_label}{sell}")
                if total_count > _BASIC_STOCK_LIMIT:
                    lines.append(f"\n...and {total_count - _BASIC_STOCK_LIMIT} more items.")
                    lines.append("Upgrade to *GO* to see your full inventory list.\n")
                else:
                    lines.append("")
                lines.append("Reply *ADD* to add a new product.")
                lines.append("Reply a *number* to manage that item.")
                msg = "\n".join(lines)
            # Set STOCK_MENU pending so number/ADD replies are intercepted
            db.query(PendingAction).filter(PendingAction.phone == phone).delete()
            item_ids = [it.id for it in items]
            db.add(PendingAction(
                phone=phone,
                action=ACTION_STOCK_MENU,
                customer_name="",
                last_customer="",
                payload_json=json.dumps({"item_ids": item_ids, "is_basic": True}),
            ))
            db.commit()
            send_message(phone, msg)
            return {"status": "inventory_list_basic"}

        if is_basic and product_filter:
            send_message(phone, upgrade_msg)
            return {"status": "inventory_plan_blocked"}

        # GO plan: full inventory list
        msg, item_ids = build_inventory_list_message(db, business_owner_phone, product_filter, return_ids=True)
        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        db.add(PendingAction(
            phone=phone,
            action=ACTION_STOCK_MENU,
            customer_name="",
            last_customer="",
            payload_json=json.dumps({"item_ids": item_ids, "is_basic": False, "page": 0, "product": product_filter}),
        ))
        db.commit()
        footer = "\n\n─────────────\nReply a *number* to manage that item.\nReply *ADD* to add a new product."
        send_message(phone, msg + footer)
        return {"status": "inventory_list"}

    # ── Add stock with cost + sell prices ────────────────────────────────────
    if command_type == "STOCK_ADD_WITH_PRICES":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "inventory_plan_blocked"}

        items = parsed.get("items", [])
        if not items:
            send_message(phone, "Not understood. Try:\nadd stock rice cost 3000 sell 4000")
            return {"status": "stock_add_prices_invalid"}

        # Show confirmation — flag items where sell < cost
        lines = ["Confirm stock:\n"]
        warnings = []
        for i, item in enumerate(items, start=1):
            unit_label = f" {item['unit']}" if item.get("unit") else ""
            qty = item.get("quantity")
            qty_label = f"{qty:,}{unit_label}" if qty else ""
            margin_note = ""
            if item["sell"] < item["cost"]:
                margin_note = " ⚠ sell below cost"
                warnings.append(item["product"].title())
            line = f"{i}. {item['product'].title()}"
            if qty_label:
                line += f" — {qty_label}"
            line += f"\n   Cost: N{item['cost']:,}  Sell: N{item['sell']:,}{margin_note}"
            lines.append(line)
        if warnings:
            lines.append(
                f"\nWarning: {', '.join(warnings)} — selling price is below cost price.\n\n"
                "Reply YES to save anyway or EDIT to change."
            )
        lines.append("\n\nReply YES to save or EDIT to change.")

        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        pending = PendingAction(
            phone=phone,
            action="STOCK_ADD_CONFIRM",
            customer_name="",
            last_customer="",
            items_json=json.dumps(items),
        )
        db.add(pending)
        db.commit()

        send_message(phone, "\n".join(lines))
        return {"status": "stock_add_prices_confirm"}

    # ── Manual stock add (quantity only) ─────────────────────────────────────
    if command_type == "STOCK_ADD":
        body = parsed.get("body", "").strip()
        if not body:
            # No body → launch the guided catalog flow (available on all plans)
            return start_guided_stock_flow(db, phone, user, send_message)

        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "inventory_plan_blocked"}

        item_data = parse_stock_item_body(body)
        if not item_data or not item_data.get("product"):
            send_message(phone, "Not understood. Try:\nadd stock 10 bags rice")
            return {"status": "stock_add_invalid"}

        item = manual_stock_add(
            db, business_owner_phone,
            item_data["product"], item_data["quantity"], item_data["unit"],
            user.id,
        )
        db.commit()
        unit_label = f" {item.unit}" if item.unit else ""
        price_hint = ""
        if not item.selling_price:
            price_hint = (
                f"\n\nNo price set. To add:\n"
                f"*price {item.name} [cost] [sell]*\n"
                f"e.g. price {item.name} 3000 4000"
            )
        send_message(
            phone,
            f"Stock added: {item.name.title()}\n"
            f"Added: {item_data['quantity']:,}{unit_label}\n"
            f"Total now: {item.quantity:,}{unit_label}"
            f"{price_hint}"
        )
        return {"status": "stock_added"}

    # ── Manual stock remove ──────────────────────────────────────────────────
    if command_type == "STOCK_REMOVE":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "inventory_plan_blocked"}

        if not _can_modify_stock(user):
            send_message(phone, "You do not have permission to remove stock.\nContact the business owner.")
            return {"status": "stock_remove_permission_denied"}

        body = parsed.get("body", "")
        note = None
        note_match = re.search(r"\((.+?)\)", body)
        if note_match:
            note = note_match.group(1).strip()
            body = body[:note_match.start()].strip()

        if not note:
            send_message(
                phone,
                "A reason is required to remove stock.\n\n"
                "Format:\nremove stock 5 bags rice (reason)\n\n"
                "Examples:\n"
                "remove stock 5 bags rice (spoilage)\n"
                "remove stock 2 carton malt (expired)\n"
                "remove stock 10 pieces soap (damaged)"
            )
            return {"status": "stock_remove_no_reason"}

        item_data = parse_stock_item_body(body)
        if not item_data or not item_data.get("product"):
            send_message(phone, "Not understood. Try:\nremove stock 5 bags rice (spoilage)")
            return {"status": "stock_remove_invalid"}

        item = manual_stock_remove(
            db, business_owner_phone,
            item_data["product"], item_data["quantity"], item_data["unit"],
            user.id, note,
        )
        if not item:
            send_message(phone, f"Stock item not found: {item_data['product'].title()}")
            return {"status": "stock_remove_not_found"}

        db.commit()
        unit_label = f" {item.unit}" if item.unit else ""
        send_message(
            phone,
            f"Stock removed: {item.name.title()}\n"
            f"Removed: {item_data['quantity']:,}{unit_label} — {note}\n"
            f"Total now: {item.quantity:,}{unit_label}"
        )
        return {"status": "stock_removed"}

    # ── Manual stock set (count correction) ──────────────────────────────────
    if command_type == "STOCK_SET":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "inventory_plan_blocked"}

        if not _can_modify_stock(user):
            send_message(phone, "You do not have permission to adjust stock counts.\nContact the business owner.")
            return {"status": "stock_set_permission_denied"}

        item_data = parse_stock_item_body(parsed.get("body", ""))
        if not item_data or not item_data.get("product") or not item_data.get("quantity"):
            send_message(phone, "Not understood. Try:\nset stock rice 50 bags")
            return {"status": "stock_set_invalid"}

        item = manual_stock_set(
            db, business_owner_phone,
            item_data["product"], item_data["quantity"], item_data["unit"],
            user.id,
        )
        db.commit()
        unit_label = f" {item.unit}" if item.unit else ""
        send_message(
            phone,
            f"Stock corrected: {item.name.title()}\n"
            f"New count: {item.quantity:,}{unit_label}"
        )
        return {"status": "stock_set"}

    # ── Low-stock alert threshold ─────────────────────────────────────────────
    if command_type == "STOCK_ALERT_SET":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "inventory_plan_blocked"}

        product = parsed.get("product", "")
        threshold = parsed.get("quantity", 0)
        item = set_low_stock_alert(db, business_owner_phone, product, None, threshold)
        if not item:
            send_message(phone, f"Stock item not found: {product.title()}\nSend STOCK to see your items.")
            return {"status": "stock_alert_not_found"}

        db.commit()
        unit_label = f" {item.unit}" if item.unit else ""
        send_message(
            phone,
            f"Alert set: {item.name.title()}\n"
            f"You will be notified when stock drops to {threshold:,}{unit_label} or below."
        )
        return {"status": "stock_alert_set"}

    if command_type == "SUPPLIER_LIST":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "SUPPLIERS", "Supplier records")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "supplier_plan_blocked"}

        send_message(phone, build_supplier_list_message(db, business_owner_phone))
        return {"status": "supplier_list"}

    if command_type == "SUPPLIER_DUE":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "SUPPLIERS", "Supplier reminders")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "supplier_due_plan_blocked"}

        send_message(phone, build_supplier_due_message(db, business_owner_phone))
        return {"status": "supplier_due"}

    if command_type == "SUPPLIER_DUE_WEEK":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "SUPPLIERS", "Supplier reminders")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "supplier_due_week_plan_blocked"}

        send_message(phone, build_supplier_due_message(db, business_owner_phone, days=7))
        return {"status": "supplier_due_week"}

    if command_type == "SELF_PURCHASE_NEEDS_SUPPLIER":
        send_message(
            phone,
            "I understand this as stock you bought for your business, not a customer debt.\n\n"
            "Please include the supplier name, like:\n"
            "I buy 1 pack of coke from Ayo at 2400"
        )
        return {"status": "self_purchase_needs_supplier"}

    if command_type == "SUPPLIER_TRANSACTION":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "SUPPLIERS", "Supplier and inventory records")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "supplier_transaction_plan_blocked"}

        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        pending = PendingAction(
            phone=phone,
            customer_name=parsed["name"].lower(),
            last_customer=parsed["name"].lower(),
            action=parsed["action"],
            buy_amount=parsed.get("buy_amount") or 0,
            paid_amount=parsed.get("paid_amount") or 0,
            product=parsed.get("product"),
            quantity=parsed.get("quantity"),
            unit=parsed.get("unit"),
            unit_price=parsed.get("unit_price"),
            items_json=json.dumps([parsed["stock_item"]] if parsed.get("stock_item") else []),
            source_text=voice_transcript_text,
            due_date=parsed.get("due_date"),
            payload_json=json.dumps({"selling_price": parsed.get("selling_price")}),
        )
        db.add(pending)
        db.commit()

        if parsed["action"] == "SUPPLIER_PURCHASE":
            unit_label = f" {parsed['unit']}" if parsed.get("unit") else ""
            balance = max((parsed.get("buy_amount") or 0) - (parsed.get("paid_amount") or 0), 0)
            due_line = ""
            if parsed.get("due_date"):
                due_line = f"\nDue: {parsed['due_date'].strftime('%d/%m/%Y')}"
            selling_line = ""
            if parsed.get("selling_price"):
                selling_line = f"\nSelling price: N{parsed['selling_price']:,}"
            confirm_msg = (
                "Confirm stock from supplier:\n"
                f"Supplier: {parsed['name'].title()}\n"
                f"Item: {parsed['product'].title()}\n"
                f"Qty: {parsed['quantity']:,}{unit_label}\n"
                f"Cost each: N{parsed['unit_price']:,}{selling_line}\n"
                f"Total: N{parsed['buy_amount']:,}\n"
                f"Paid: N{parsed['paid_amount']:,}\n"
                f"You owe: N{balance:,}"
                f"{due_line}\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            if parsed.get("stock_item"):
                stock_item = parsed["stock_item"]
                stock_unit = f" {stock_item['unit']}" if stock_item.get("unit") else ""
                confirm_msg = (
                    "Confirm stock from supplier:\n"
                    f"Supplier: {parsed['name'].title()}\n"
                    f"Bought: {parsed['quantity']:,}{unit_label} of {parsed['product'].title()}\n"
                    f"Bulk cost: N{parsed['unit_price']:,} each\n"
                    f"Total: N{parsed['buy_amount']:,}\n"
                    f"Paid: N{parsed['paid_amount']:,}\n"
                    f"You owe: N{balance:,}"
                    f"{due_line}\n"
                    f"Stock will be added as: {stock_item['quantity']:,}{stock_unit} "
                    f"of {stock_item['product'].title()} at N{stock_item['unit_price']:,} each\n\n"
                    "Reply YES or 1 to save, EDIT or 2 to change."
                )
        else:
            product_line = f"\nFor: {parsed['product'].title()}" if parsed.get("product") else ""
            confirm_msg = (
                "Confirm supplier payment:\n"
                f"Supplier: {parsed['name'].title()}\n"
                f"Paid: N{parsed['paid_amount']:,}"
                f"{product_line}\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )

        confirm_msg = apply_voice_confirmation_options(confirm_msg, voice_transcript_text)
        send_message(phone, confirm_msg)
        return {"status": "confirm_supplier_transaction"}

    return None
