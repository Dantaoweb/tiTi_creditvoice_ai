import json

from messages import apply_voice_confirmation_options
from models import Customer, CustomerMemory, PendingAction, Transaction
from parser import format_invoice_items
from reports import get_balance, get_owner_transaction_query
from subscriptions import check_customer_limit, ensure_feature_allowed, get_month_start


def check_monthly_transaction_limit(db, owner_phone, subscription, planned_rows=1):
    limit = subscription["limits"].get("monthly_transactions")
    if limit is None:
        return True, None

    current_count = get_owner_transaction_query(
        db,
        owner_phone
    ).filter(
        Transaction.created_at >= get_month_start()
    ).count()
    if current_count + planned_rows <= limit:
        return True, None

    return False, (
        f"Basic plan monthly transaction limit reached ({limit}).\n\n"
        "Send UPGRADE to move to Go for unlimited transactions."
    )


def build_projected_balance_line(db, customer_id, parsed, recorded_by_id=None):
    current_balance = get_balance(db, customer_id, recorded_by_id)
    projected_balance = (
        current_balance
        + (parsed.get("buy_amount") or 0)
        - (parsed.get("paid_amount") or 0)
    )
    if projected_balance < 0:
        return f"Projected credit: N{abs(projected_balance):,}"
    return f"Projected balance: N{projected_balance:,}"


def direct_sale_item_line(parsed):
    if parsed.get("invoice_items"):
        return f"{format_invoice_items(parsed['invoice_items'])}\n\nTotal: N{parsed['total']:,}"
    if parsed.get("quantity") and parsed.get("unit"):
        return (
            f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} "
            f"at N{parsed['unit_price']:,}, total: N{parsed['total']:,}"
        )
    if parsed.get("quantity") and parsed["quantity"] > 1:
        return (
            f"{parsed['quantity']} {parsed['product']} "
            f"at N{parsed['unit_price']:,}, total: N{parsed['total']:,}"
        )
    return f"{parsed['product']} - N{parsed['total']:,}"


def build_customer_confirm_message(customer, parsed):
    action = parsed["action"]
    if action == "BUY":
        if parsed.get("invoice_items"):
            item_line = f"{format_invoice_items(parsed['invoice_items'])}\n\nTotal: N{parsed['total']:,}"
            if parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                return (
                    f"Confirm invoice for {customer.name}:\n{item_line}\n"
                    f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                )
            return (
                f"Confirm invoice for {customer.name}:\n{item_line}\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )

        if parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
            item_line = (
                f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} "
                f"at N{parsed['unit_price']:,} each, total: N{parsed['total']:,}"
            )
            if parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                return (
                    f"Confirm:\n{customer.name} bought {item_line}\n"
                    f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                )
            return (
                f"Confirm:\n{customer.name} bought {item_line}\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )

        if parsed["due_date"]:
            due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
            return (
                f"Confirm:\n{customer.name} bought N{parsed['buy_amount']:,}\n"
                f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
            )
        return (
            f"Confirm:\n{customer.name} bought N{parsed['buy_amount']:,}?\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )

    if action == "PAY":
        return (
            f"Confirm:\n{customer.name} paid N{parsed['paid_amount']:,}?\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )

    if action == "COMBINED":
        if parsed.get("invoice_items"):
            item_line = (
                f"\n{format_invoice_items(parsed['invoice_items'])}\n\n"
                f"Total bought: N{parsed['buy_amount']:,}"
            )
        elif parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
            item_line = (
                f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} "
                f"at N{parsed['unit_price']:,} each, total: N{parsed['total']:,}"
            )
        else:
            item_line = f"N{parsed['buy_amount']:,}"

        if parsed["due_date"]:
            due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
            return (
                f"Confirm:\n{customer.name} bought {item_line}\n"
                f"and paid N{parsed['paid_amount']:,}\n"
                f"Balance due on: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
            )
        return (
            f"Confirm:\n{customer.name} bought {item_line}\n"
            f"and paid N{parsed['paid_amount']:,}?\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )

    return None


def handle_transaction_setup(
    db,
    phone,
    parsed,
    user,
    business_owner_phone,
    subscription,
    visible_recorded_by_id,
    voice_transcript_text,
    send_message,
):
    if not parsed or "action" not in parsed:
        return None

    if parsed["action"] == "SALE":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "DIRECT_SALE", "Direct sales")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "direct_sale_plan_blocked"}

        transaction_allowed, transaction_limit_msg = check_monthly_transaction_limit(
            db,
            business_owner_phone,
            subscription,
            planned_rows=1,
        )
        if not transaction_allowed:
            send_message(phone, transaction_limit_msg)
            return {"status": "transaction_limit_reached"}

        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name="",
                last_customer="",
                action="SALE",
                buy_amount=parsed["buy_amount"],
                product=parsed.get("product"),
                quantity=parsed.get("quantity"),
                unit=parsed.get("unit"),
                unit_price=parsed.get("unit_price"),
                items_json=json.dumps(parsed.get("invoice_items") or []),
                source_text=voice_transcript_text,
            )
        )
        db.commit()

        confirm_msg = (
            f"Confirm service/direct income:\n{direct_sale_item_line(parsed)}\n"
            "No customer debt will be recorded.\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )
        confirm_msg = apply_voice_confirmation_options(confirm_msg, voice_transcript_text)
        send_message(phone, confirm_msg)
        return {"status": "confirm_direct_sale"}

    customer_name = parsed["name"].lower()
    if customer_name in ["he", "she"]:
        memory = db.query(CustomerMemory).filter(CustomerMemory.phone == phone).first()
        if memory and memory.last_customer:
            customer_name = memory.last_customer.lower()
        else:
            send_message(phone, "No previous customer found.")
            return {"status": "no_memory"}

    if parsed.get("invoice_items"):
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVOICE", "Invoice-style multi-item sales")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "invoice_plan_blocked"}

    customer = db.query(Customer).filter(
        Customer.name == customer_name,
        Customer.owner_phone == business_owner_phone,
    ).first()
    customer_was_created = False

    if not customer:
        customer_allowed, customer_limit_msg = check_customer_limit(
            db,
            business_owner_phone,
            subscription,
        )
        if not customer_allowed:
            send_message(phone, customer_limit_msg)
            return {"status": "customer_limit_reached"}

        customer = Customer(name=customer_name, owner_phone=business_owner_phone)
        db.add(customer)
        db.commit()
        customer_was_created = True

    planned_rows = 2 if parsed["action"] == "COMBINED" else 1
    transaction_allowed, transaction_limit_msg = check_monthly_transaction_limit(
        db,
        business_owner_phone,
        subscription,
        planned_rows=planned_rows,
    )
    if not transaction_allowed:
        send_message(phone, transaction_limit_msg)
        return {"status": "transaction_limit_reached"}

    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    db.add(
        PendingAction(
            phone=phone,
            customer_name=customer.name,
            last_customer=customer.name,
            action=parsed["action"],
            buy_amount=parsed["buy_amount"],
            paid_amount=parsed["paid_amount"],
            product=parsed.get("product"),
            quantity=parsed.get("quantity"),
            unit=parsed.get("unit"),
            unit_price=parsed.get("unit_price"),
            items_json=json.dumps(parsed.get("invoice_items") or []),
            source_text=voice_transcript_text,
            due_date=parsed["due_date"],
        )
    )
    db.commit()

    balance_after_line = build_projected_balance_line(
        db,
        customer.id,
        parsed,
        visible_recorded_by_id,
    )
    confirm_msg = build_customer_confirm_message(customer, parsed)

    phone_warning = ""
    if not customer.customer_phone:
        setup_hint = f"{customer.name} phone 08012345678"
        if customer_was_created:
            phone_warning = (
                f"\nNew customer created: {customer.name.title()} with no phone number.\n"
                "This transaction will still save. For reminders later, send:\n"
                f"{setup_hint}"
            )
        else:
            phone_warning = (
                f"\nCustomer phone is not set for {customer.name.title()}.\n"
                "This transaction will still save. For reminders later, send:\n"
                f"{setup_hint}"
            )

    confirm_msg = f"{confirm_msg}\n{balance_after_line}{phone_warning}"
    if parsed.get("artisan_note"):
        confirm_msg = (
            f"{confirm_msg}\n"
            "This will record customer debt and payment.\n"
            f"{parsed['artisan_note']}"
        )
    confirm_msg = apply_voice_confirmation_options(confirm_msg, voice_transcript_text)

    send_message(phone, confirm_msg)
    return {"status": "pending"}
