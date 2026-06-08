import json

from messages import apply_voice_confirmation_options
from models import Customer, CustomerMemory, InventoryItem, ParseLog, PendingAction, Transaction
from parser import format_invoice_items
from reports import get_balance, get_owner_transaction_query
from subscriptions import check_customer_limit, ensure_feature_allowed, get_month_start


def log_parse(db, phone, owner_phone, raw_input, parsed, source="text", user=None):
    """Write one ParseLog row. Errors are silently swallowed — logging must never break the flow."""
    try:
        db.add(ParseLog(
            phone=phone,
            owner_phone=owner_phone,
            business_type=getattr(user, "business_type", None),
            business_category=getattr(user, "business_category", None),
            raw_input=raw_input,
            parsed_type=parsed.get("type") if parsed else None,
            parsed_data=json.dumps(parsed) if parsed else None,
            source=source,
        ))
        db.flush()
    except Exception:
        pass


def update_parse_log_outcome(db, phone, was_confirmed, correction_input=None):
    """Mark the most recent ParseLog for this phone as confirmed or corrected."""
    try:
        from sqlalchemy import desc
        log = db.query(ParseLog).filter(
            ParseLog.phone == phone,
            ParseLog.was_confirmed.is_(None),
        ).order_by(desc(ParseLog.created_at)).first()
        if log:
            log.was_confirmed = was_confirmed
            if correction_input:
                log.correction_input = correction_input
            db.flush()
    except Exception:
        pass


def _price_deviation_alert(db, owner_phone, product, unit_price):
    """
    Return an internal alert string for the owner/staff confirmation screen.
    Shows if unit_price deviates from selling_price (discount or premium),
    and adds a separate ⚠ line if the price is also below cost price.
    Never shown to the customer.
    """
    if not product or not unit_price:
        return ""
    try:
        from sqlalchemy import func
        item = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone,
            func.lower(InventoryItem.name) == product.lower().strip(),
        ).first()
        if not item:
            return ""

        lines = []

        if item.selling_price:
            diff = unit_price - item.selling_price
            if diff < 0:
                lines.append(
                    f"↓ Standard price for {product.title()} is N{item.selling_price:,}. "
                    f"You are giving a N{abs(diff):,} discount."
                )
            # Above standard: silent on screen — recorded as internal note only

        if item.cost_price and unit_price < item.cost_price:
            loss = item.cost_price - unit_price
            lines.append(
                f"⚠ Also below your cost price (N{item.cost_price:,}). "
                f"You are selling at a N{loss:,} loss per unit."
            )

        return ("\n\n" + "\n".join(lines)) if lines else ""
    except Exception:
        pass
    return ""


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


def _calc_line(qty, unit, product, unit_price, total):
    """Show multiplication explicitly: '10 dozen of paper bags\n10 × N6,500 = N65,000'"""
    label = f"{qty} {unit} of {product}" if unit else f"{qty} {product}"
    return f"{label}\n{qty} × N{unit_price:,} = N{total:,}"


def _at_hint(qty, unit_price):
    """
    When 'at [price]' was used without 'each', the price is ambiguous.
    Fire a hint when: price divisible by qty (both interpretations give round numbers)
    and unit price is above trivial threshold.
    """
    if qty <= 1 or not unit_price or unit_price <= 100:
        return ""
    if unit_price % qty != 0:
        return ""
    alt_unit = unit_price // qty
    return (
        f"\n↩️ If N{unit_price:,} was the *total* price: that's N{alt_unit:,} each.\n"
        "Reply EDIT and resend using 'for' instead of 'at' to record as total."
    )


def direct_sale_item_line(parsed):
    if parsed.get("invoice_items"):
        return f"{format_invoice_items(parsed['invoice_items'])}\n\nTotal: N{parsed['total']:,}"
    qty = parsed.get("quantity")
    unit_price = parsed.get("unit_price")
    total = parsed.get("total")
    if qty and parsed.get("unit"):
        return _calc_line(qty, parsed["unit"], parsed["product"], unit_price, total)
    if qty and qty > 1:
        return _calc_line(qty, None, parsed["product"], unit_price, total)
    return f"{parsed['product']} - N{total:,}"


def build_customer_confirm_message(customer, parsed):
    action = parsed["action"]
    if action == "BUY":
        if parsed.get("invoice_items"):
            item_line = f"{format_invoice_items(parsed['invoice_items'])}\n\nTotal: N{parsed['total']:,}"
            if parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                return (
                    f"Confirm invoice for {customer.name}:\n{item_line}\n"
                    f"Due: {due_date_text}\n\nReply YES or 1 to save, EDIT or 2 to change."
                )
            return (
                f"Confirm invoice for {customer.name}:\n{item_line}\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )

        if parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
            qty = parsed["quantity"]
            item_line = _calc_line(qty, parsed["unit"], parsed["product"], parsed["unit_price"], parsed["total"])
            hint = _at_hint(qty, parsed["unit_price"])
            if parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                return (
                    f"Confirm:\n{customer.name} bought {item_line}\n"
                    f"Due: {due_date_text}{hint}\n\nReply YES or 1 to save, EDIT or 2 to change."
                )
            return (
                f"Confirm:\n{customer.name} bought {item_line}{hint}\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )

        if parsed["due_date"]:
            due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
            return (
                f"Confirm:\n{customer.name} bought N{parsed['buy_amount']:,}\n"
                f"Due: {due_date_text}\n\nReply YES or 1 to save, EDIT or 2 to change."
            )
        return (
            f"Confirm:\n{customer.name} bought N{parsed['buy_amount']:,}?\n\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )

    if action == "PAY":
        return (
            f"Confirm:\n{customer.name} paid N{parsed['paid_amount']:,}?\n\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )

    if action == "COMBINED":
        hint = ""
        if parsed.get("invoice_items"):
            item_line = (
                f"\n{format_invoice_items(parsed['invoice_items'])}\n\n"
                f"Total bought: N{parsed['buy_amount']:,}"
            )
        elif parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
            qty = parsed["quantity"]
            item_line = _calc_line(qty, parsed["unit"], parsed["product"], parsed["unit_price"], parsed["total"])
            hint = _at_hint(qty, parsed["unit_price"])
        else:
            item_line = f"N{parsed['buy_amount']:,}"

        if parsed["due_date"]:
            due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
            return (
                f"Confirm:\n{customer.name} bought {item_line}\n"
                f"and paid N{parsed['paid_amount']:,}\n"
                f"Balance due on: {due_date_text}{hint}\n\nReply YES or 1 to save, EDIT or 2 to change."
            )
        return (
            f"Confirm:\n{customer.name} bought {item_line}\n"
            f"and paid N{parsed['paid_amount']:,}?{hint}\n\n"
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

    # Log every parsed transaction for tiTi training
    source = "voice" if voice_transcript_text else "text"
    log_parse(db, phone, business_owner_phone, voice_transcript_text or parsed.get("raw_text", ""), parsed, source, user)

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
            f"Confirm service/direct income:\n{direct_sale_item_line(parsed)}\n\n"
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

    # Note any deviation from the standard selling price (internal only)
    below_cost = _price_deviation_alert(
        db, business_owner_phone,
        parsed.get("product"), parsed.get("unit_price"),
    )

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

    no_details_hint = ""
    if not parsed.get("product") and not parsed.get("invoice_items"):
        cname = customer.name.title()
        no_details_hint = (
            "\n\n⚠️ No product details captured.\n"
            "To include item + quantity, resend as:\n"
            f"{cname} bought 10 dozen paper bags for 65000"
        )

    confirm_msg = f"{confirm_msg}\n{balance_after_line}{below_cost}{phone_warning}{no_details_hint}"
    if parsed.get("artisan_note"):
        confirm_msg = (
            f"{confirm_msg}\n"
            "This will record customer debt and payment.\n"
            f"{parsed['artisan_note']}"
        )
    confirm_msg = apply_voice_confirmation_options(confirm_msg, voice_transcript_text)

    send_message(phone, confirm_msg)
    return {"status": "pending"}
