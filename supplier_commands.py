from inventory_suppliers import (
    build_inventory_list_message,
    build_supplier_due_message,
    build_supplier_list_message,
)
from messages import apply_voice_confirmation_options
from models import PendingAction
from subscriptions import ensure_feature_allowed


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
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "inventory_plan_blocked"}

        msg = build_inventory_list_message(
            db,
            business_owner_phone,
            parsed.get("product"),
        )
        send_message(phone, msg)
        return {"status": "inventory_list"}

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
            source_text=voice_transcript_text,
            due_date=parsed.get("due_date"),
        )
        db.add(pending)
        db.commit()

        if parsed["action"] == "SUPPLIER_PURCHASE":
            unit_label = f" {parsed['unit']}" if parsed.get("unit") else ""
            balance = max((parsed.get("buy_amount") or 0) - (parsed.get("paid_amount") or 0), 0)
            due_line = ""
            if parsed.get("due_date"):
                due_line = f"\nDue: {parsed['due_date'].strftime('%d/%m/%Y')}"
            confirm_msg = (
                "Confirm stock from supplier:\n"
                f"Supplier: {parsed['name'].title()}\n"
                f"Item: {parsed['product'].title()}\n"
                f"Qty: {parsed['quantity']:,}{unit_label}\n"
                f"Cost each: N{parsed['unit_price']:,}\n"
                f"Total: N{parsed['buy_amount']:,}\n"
                f"Paid: N{parsed['paid_amount']:,}\n"
                f"You owe: N{balance:,}"
                f"{due_line}\n\n"
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
