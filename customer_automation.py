import re
from datetime import datetime, timedelta

from sqlalchemy import func

from models import (
    AutomationSettings,
    CustomerConversation,
    InventoryItem,
    ReminderMemory,
    SalesOrder,
    SalesOrderItem,
    SalesOrderPayment,
    User,
)
from subscriptions import ensure_feature_allowed, get_business_subscription


AUTOMATION_FEATURE = "CUSTOMER_SALES_BOT"


def normalize_phone(value):
    digits = re.sub(r"\D+", "", value or "")
    if digits.startswith("0") and len(digits) == 11:
        return "234" + digits[1:]
    return digits


def get_or_create_automation_settings(db, owner_phone):
    settings = db.query(AutomationSettings).filter(
        AutomationSettings.owner_phone == owner_phone
    ).first()
    if settings:
        return settings

    settings = AutomationSettings(owner_phone=owner_phone)
    db.add(settings)
    db.flush()
    return settings


def automation_status_message(settings):
    return (
        "Customer Bot Settings\n\n"
        f"Bot: {'ON' if settings.bot_enabled else 'OFF'}\n"
        f"Auto reply: {'ON' if settings.auto_reply_enabled else 'OFF'}\n"
        f"Auto order: {'ON' if settings.auto_order_enabled else 'OFF'}\n"
        f"Part payment: {'ON' if settings.allow_part_payment else 'OFF'}\n"
        f"Payment: {settings.payment_modes or 'Not set'}\n"
        f"Delivery: {settings.delivery_note or 'Not set'}\n"
        f"Pickup: {settings.pickup_address or 'Not set'}\n\n"
        "Controls:\n"
        "bot on\n"
        "bot off\n"
        "auto order on\n"
        "auto order off\n"
        "part payment on\n"
        "part payment off\n"
        "take over 2348012345678\n"
        "bot resume 2348012345678"
    )


def parse_money_value(value):
    if value is None:
        return None
    value = value.strip().replace(",", "")
    match = re.match(r"^(\d+(?:\.\d+)?)(k|m)?$", value, re.I)
    if not match:
        return None
    amount = int(float(match.group(1)))
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        amount *= 1000
    elif suffix == "m":
        amount *= 1000000
    return amount


def parse_add_product_command(text):
    match = re.match(
        r"^add\s+product\s+(?P<body>.+?)\s+price\s+(?P<price>\d[\d,\.]*(?:k|m)?)"
        r"(?:\s+qty\s+(?P<qty>\d+))?"
        r"(?:\s+unit\s+(?P<unit>[a-zA-Z]+))?"
        r"(?:\s+size\s+(?P<size>[a-zA-Z0-9\-\/]+))?"
        r"(?:\s+color\s+(?P<color>[a-zA-Z ]+?))?$",
        text,
        re.I,
    )
    if not match:
        return None
    return {
        "name": match.group("body").strip().lower(),
        "price": parse_money_value(match.group("price")),
        "quantity": int(match.group("qty") or 0),
        "unit": match.group("unit"),
        "size": match.group("size"),
        "color": (match.group("color") or "").strip() or None,
    }


def find_product_by_name(db, owner_phone, product_name):
    return db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name) == product_name.lower().strip(),
    ).first()


def upsert_product_from_command(db, owner_phone, parsed):
    item = find_product_by_name(db, owner_phone, parsed["name"])
    if not item:
        item = InventoryItem(
            owner_phone=owner_phone,
            name=parsed["name"],
            quantity=0,
            is_available=True,
        )
        db.add(item)
        db.flush()

    item.selling_price = parsed["price"]
    item.quantity = parsed["quantity"]
    item.unit = parsed["unit"]
    item.size = parsed["size"]
    item.color = parsed["color"]
    item.is_available = True
    item.updated_at = datetime.utcnow()
    return item


def build_product_message(item):
    unit = f" {item.unit}" if item.unit else ""
    return (
        f"{item.name.title()} saved.\n\n"
        f"Price: N{(item.selling_price or 0):,}\n"
        f"Stock: {(item.quantity or 0):,}{unit}\n"
        f"Size: {item.size or 'Not set'}\n"
        f"Color: {item.color or 'Not set'}"
    )


def list_orders_message(db, owner_phone):
    orders = db.query(SalesOrder).filter(
        SalesOrder.owner_phone == owner_phone,
        SalesOrder.status.in_(["PENDING_OWNER_CONFIRMATION", "CONFIRMED", "DELIVERY_PENDING"]),
    ).order_by(
        SalesOrder.created_at.desc()
    ).limit(10).all()
    if not orders:
        return "No pending customer bot orders."

    msg = "Pending Orders\n\n"
    for order in orders:
        msg += (
            f"#{order.id} - {order.customer_phone}\n"
            f"Status: {order.status.replace('_', ' ').title()}\n"
            f"Payment: {order.payment_status.replace('_', ' ').title()}\n"
            f"Total: N{order.total_amount:,} | Paid: N{order.paid_amount:,} | Balance: N{order.balance_amount:,}\n\n"
        )
    msg += "Reply: confirm payment 12, reject payment 12, confirm order 12, deliver order 12"
    return msg.strip()


def pending_payment_message(db, owner_phone):
    rows = db.query(SalesOrder, SalesOrderPayment).join(
        SalesOrderPayment,
        SalesOrderPayment.order_id == SalesOrder.id,
    ).filter(
        SalesOrder.owner_phone == owner_phone,
        SalesOrderPayment.status == "PENDING_OWNER_CONFIRMATION",
    ).order_by(
        SalesOrderPayment.created_at.desc()
    ).limit(10).all()
    if not rows:
        return "No payment evidence waiting for confirmation."

    msg = "Payment Evidence Waiting\n\n"
    for order, payment in rows:
        msg += (
            f"Order #{order.id} - {order.customer_phone}\n"
            f"Amount claimed: N{payment.amount:,}\n"
            f"Evidence: {payment.evidence_ref or 'Not provided'}\n"
            f"Reply: confirm payment {order.id} or reject payment {order.id}\n\n"
        )
    return msg.strip()


def deliveries_message(db, owner_phone):
    orders = db.query(SalesOrder).filter(
        SalesOrder.owner_phone == owner_phone,
        SalesOrder.status.in_(["CONFIRMED", "DELIVERY_PENDING"]),
    ).order_by(
        SalesOrder.created_at.desc()
    ).limit(10).all()
    if not orders:
        return "No delivery or pickup orders pending."

    msg = "Deliveries / Pickups\n\n"
    for order in orders:
        msg += (
            f"Order #{order.id} - {order.customer_phone}\n"
            f"Delivery: {order.delivery_status.replace('_', ' ').title()}\n"
            f"Payment: {order.payment_status.replace('_', ' ').title()}\n"
            f"Balance: N{order.balance_amount:,}\n\n"
        )
    msg += "Reply: deliver order 12 or order 12 delivered"
    return msg.strip()


def low_stock_message(db, owner_phone):
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.quantity <= func.coalesce(InventoryItem.low_stock_alert, 3),
        InventoryItem.is_available == True,
    ).order_by(
        InventoryItem.quantity.asc()
    ).limit(15).all()
    if not items:
        return "No low stock item found."

    msg = "Low Stock\n\n"
    for item in items:
        unit = f" {item.unit}" if item.unit else ""
        threshold = item.low_stock_alert if item.low_stock_alert is not None else 3
        msg += f"{item.name.title()}: {item.quantity or 0:,}{unit} left (alert: {threshold})\n"
    return msg.strip()


def order_balance_reminders(db, owner_phone):
    return db.query(ReminderMemory).filter(
        ReminderMemory.phone == owner_phone,
        ReminderMemory.reminder_type == "ORDER_BALANCE",
        ReminderMemory.balance > 0,
    ).order_by(
        ReminderMemory.due_date.asc()
    ).limit(20).all()


def balance_reminders_message(db, owner_phone):
    reminders = order_balance_reminders(db, owner_phone)
    if not reminders:
        return "No order balance reminder found."

    msg = "Order Balance Reminders\n\n"
    for reminder in reminders:
        due = reminder.due_date.strftime("%d/%m/%Y") if reminder.due_date else "No date"
        msg += (
            f"{reminder.customer_name or reminder.customer_phone}\n"
            f"Balance: N{reminder.balance:,}\n"
            f"Due: {due}\n\n"
        )
    return msg.strip()


def today_assistant_message(db, owner_phone):
    pending_payments = db.query(SalesOrderPayment).join(
        SalesOrder,
        SalesOrderPayment.order_id == SalesOrder.id,
    ).filter(
        SalesOrder.owner_phone == owner_phone,
        SalesOrderPayment.status == "PENDING_OWNER_CONFIRMATION",
    ).count()
    pending_orders = db.query(SalesOrder).filter(
        SalesOrder.owner_phone == owner_phone,
        SalesOrder.status == "PENDING_OWNER_CONFIRMATION",
    ).count()
    delivery_count = db.query(SalesOrder).filter(
        SalesOrder.owner_phone == owner_phone,
        SalesOrder.status.in_(["CONFIRMED", "DELIVERY_PENDING"]),
    ).count()
    interested_count = db.query(CustomerConversation).filter(
        CustomerConversation.owner_phone == owner_phone,
        CustomerConversation.status.in_(["AUTO", "NEEDS_OWNER"]),
        CustomerConversation.stage.in_(["ANSWERED_PRODUCT", "ASK_PRODUCT", "OWNER_NEEDED"]),
    ).count()
    low_stock_count = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.quantity <= func.coalesce(InventoryItem.low_stock_alert, 3),
        InventoryItem.is_available == True,
    ).count()
    balance_count = len(order_balance_reminders(db, owner_phone))

    return (
        "Today Assistant\n\n"
        f"Pending orders: {pending_orders}\n"
        f"Payment evidence to confirm: {pending_payments}\n"
        f"Deliveries / pickups: {delivery_count}\n"
        f"Order balances to follow: {balance_count}\n"
        f"Interested customers: {interested_count}\n"
        f"Low stock items: {low_stock_count}\n\n"
        "Commands:\n"
        "pending payments\n"
        "deliveries\n"
        "send reminders\n"
        "interested customers\n"
        "low stock"
    )


def send_due_order_balance_reminders(db, owner_phone, send_message):
    reminders = order_balance_reminders(db, owner_phone)
    sent_count = 0
    for reminder in reminders:
        if not reminder.customer_phone:
            continue
        send_message(
            reminder.customer_phone,
            f"Hello {reminder.customer_name or ''},\n\n"
            f"This is a reminder that your order balance is N{reminder.balance:,}.\n"
            "Please contact the business if you have already paid."
        )
        sent_count += 1
    return sent_count


def order_item_summary(db, order_id):
    items = db.query(SalesOrderItem).filter(
        SalesOrderItem.order_id == order_id
    ).all()
    if not items:
        return "Items: Not listed"
    lines = []
    for item in items:
        unit = f" {item.unit}" if item.unit else ""
        lines.append(
            f"{item.product.title()} x {item.quantity:,}{unit} - N{item.total:,}"
        )
    return "\n".join(lines)


def customer_receipt_message(db, order):
    return (
        f"Receipt for order #{order.id}\n\n"
        f"{order_item_summary(db, order.id)}\n\n"
        f"Total: N{order.total_amount:,}\n"
        f"Paid: N{order.paid_amount:,}\n"
        f"Balance: N{order.balance_amount:,}\n"
        f"Payment status: {order.payment_status.replace('_', ' ').title()}\n"
        f"Delivery: {order.delivery_status.replace('_', ' ').title()}"
    )


def notify_customer_order_update(db, send_message, order, message):
    if not order.customer_phone:
        return
    send_message(
        order.customer_phone,
        f"{message}\n\n{customer_receipt_message(db, order)}"
    )


def list_interested_customers_message(db, owner_phone, product=None):
    query = db.query(CustomerConversation).filter(
        CustomerConversation.owner_phone == owner_phone,
        CustomerConversation.status.in_(["AUTO", "NEEDS_OWNER"]),
        CustomerConversation.stage.in_(["ANSWERED_PRODUCT", "ASK_PRODUCT", "OWNER_NEEDED"]),
    )
    if product:
        item = find_matching_inventory_item(db, owner_phone, product)
        if item:
            query = query.filter(CustomerConversation.matched_item_id == item.id)
        else:
            query = query.filter(
                func.lower(CustomerConversation.product_query).like(f"%{product.lower()}%")
            )
    conversations = query.order_by(
        CustomerConversation.updated_at.desc()
    ).limit(10).all()
    if not conversations:
        return "No interested customers found yet."

    msg = "Interested Customers\n\n"
    for conversation in conversations:
        item_name = "Unknown product"
        if conversation.matched_item_id:
            item = db.query(InventoryItem).filter(
                InventoryItem.id == conversation.matched_item_id
            ).first()
            if item:
                item_name = item.name.title()
        elif conversation.product_query:
            item_name = conversation.product_query.title()
        msg += (
            f"{conversation.customer_phone} - {item_name}\n"
            f"Last: {conversation.last_customer_message or 'No message'}\n\n"
        )
    msg += "Reply: follow up product name"
    return msg.strip()


def get_latest_pending_order_for_customer(db, owner_phone, customer_phone):
    return db.query(SalesOrder).filter(
        SalesOrder.owner_phone == owner_phone,
        SalesOrder.customer_phone == customer_phone,
        SalesOrder.status.in_(["PENDING_OWNER_CONFIRMATION", "CONFIRMED", "DELIVERY_PENDING"]),
    ).order_by(
        SalesOrder.created_at.desc()
    ).first()


def handle_order_owner_command(db, phone, normalized, owner_phone, send_message):
    if normalized in ["today", "daily assistant", "business today"]:
        send_message(phone, today_assistant_message(db, owner_phone))
        return {"status": "automation_today"}

    if normalized == "pending payments":
        send_message(phone, pending_payment_message(db, owner_phone))
        return {"status": "automation_pending_payments"}

    if normalized in ["deliveries", "pending deliveries"]:
        send_message(phone, deliveries_message(db, owner_phone))
        return {"status": "automation_deliveries"}

    if normalized == "low stock":
        send_message(phone, low_stock_message(db, owner_phone))
        return {"status": "automation_low_stock"}

    if normalized in ["send reminders", "send order reminders"]:
        sent_count = send_due_order_balance_reminders(db, owner_phone, send_message)
        send_message(phone, f"Order balance reminders sent: {sent_count}")
        return {"status": "automation_reminders_sent"}

    if normalized in ["follow ups", "followups"]:
        send_message(phone, list_interested_customers_message(db, owner_phone))
        return {"status": "automation_followups"}

    if normalized in ["orders", "pending orders"]:
        send_message(phone, list_orders_message(db, owner_phone))
        return {"status": "automation_orders"}

    if normalized == "interested customers":
        send_message(phone, list_interested_customers_message(db, owner_phone))
        return {"status": "automation_interested_customers"}

    interested_match = re.match(r"^interested customers\s+(.+)$", normalized)
    if interested_match:
        product = interested_match.group(1).strip()
        send_message(phone, list_interested_customers_message(db, owner_phone, product))
        return {"status": "automation_interested_customers"}

    followup_match = re.match(r"^follow up\s+(.+)$", normalized)
    if followup_match:
        product = followup_match.group(1).strip()
        item = find_matching_inventory_item(db, owner_phone, product)
        if not item:
            send_message(phone, f"Product not found for follow-up: {product.title()}")
            return {"status": "automation_followup_product_not_found"}
        conversations = db.query(CustomerConversation).filter(
            CustomerConversation.owner_phone == owner_phone,
            CustomerConversation.matched_item_id == item.id,
            CustomerConversation.status == "AUTO",
            CustomerConversation.stage == "ANSWERED_PRODUCT",
        ).order_by(
            CustomerConversation.updated_at.desc()
        ).limit(20).all()
        if not conversations:
            send_message(phone, f"No interested customers found for {item.name.title()}.")
            return {"status": "automation_followup_empty"}
        sent_count = 0
        for conversation in conversations:
            send_message(
                conversation.customer_phone,
                f"Hello, {item.name.title()} is still available.\n\n"
                f"{describe_item(item, get_or_create_automation_settings(db, owner_phone))}\n\n"
                "Reply here if you want to order."
            )
            sent_count += 1
        send_message(phone, f"Follow-up sent to {sent_count} interested customer(s).")
        return {"status": "automation_followup_sent"}

    payment_decision = re.match(r"^(confirm|reject)\s+payment\s+(\d+)$", normalized)
    if payment_decision:
        decision = payment_decision.group(1)
        order_id = int(payment_decision.group(2))
        order = db.query(SalesOrder).filter(
            SalesOrder.id == order_id,
            SalesOrder.owner_phone == owner_phone,
        ).first()
        if not order:
            send_message(phone, f"Order #{order_id} not found.")
            return {"status": "automation_order_not_found"}
        payment = db.query(SalesOrderPayment).filter(
            SalesOrderPayment.order_id == order.id,
            SalesOrderPayment.status == "PENDING_OWNER_CONFIRMATION",
        ).order_by(
            SalesOrderPayment.created_at.desc()
        ).first()
        if not payment:
            send_message(phone, f"No pending payment evidence found for order #{order.id}.")
            return {"status": "automation_payment_not_found"}
        if decision == "reject":
            payment.status = "REJECTED"
            order.payment_status = "PAYMENT_REJECTED"
            order.updated_at = datetime.utcnow()
            db.commit()
            send_message(phone, f"Payment evidence rejected for order #{order.id}.")
            notify_customer_order_update(
                db,
                send_message,
                order,
                f"Your payment evidence for order #{order.id} could not be confirmed. Please contact the business or send clearer evidence.",
            )
            return {"status": "automation_payment_rejected"}

        payment.status = "OWNER_CONFIRMED"
        order.paid_amount = (order.paid_amount or 0) + (payment.amount or 0)
        order.balance_amount = max((order.total_amount or 0) - order.paid_amount, 0)
        order.payment_status = "PAID" if order.balance_amount == 0 else "PART_PAID"
        order.updated_at = datetime.utcnow()
        if order.balance_amount:
            db.add(
                ReminderMemory(
                    phone=owner_phone,
                    customer_name=order.customer_name or order.customer_phone,
                    customer_phone=order.customer_phone,
                    balance=order.balance_amount,
                    due_date=datetime.utcnow() + timedelta(days=1),
                    reminder_type="ORDER_BALANCE",
                )
            )
            db.add(
                ReminderMemory(
                    phone=order.customer_phone,
                    customer_name=order.customer_name or order.customer_phone,
                    customer_phone=order.customer_phone,
                    balance=order.balance_amount,
                    due_date=datetime.utcnow() + timedelta(days=1),
                    reminder_type="CUSTOMER_ORDER_BALANCE",
                )
            )
        db.commit()
        send_message(
            phone,
            f"Payment confirmed for order #{order.id}.\n"
            f"Paid: N{order.paid_amount:,}\n"
            f"Balance: N{order.balance_amount:,}"
        )
        notify_customer_order_update(
            db,
            send_message,
            order,
            f"Your payment has been confirmed for order #{order.id}.",
        )
        return {"status": "automation_payment_confirmed"}

    match = re.match(r"^(confirm|reject|deliver|order\s+delivered)\s+order\s+(\d+)$", normalized)
    if not match:
        match = re.match(r"^order\s+(\d+)\s+delivered$", normalized)
        if match:
            action = "delivered"
            order_id = int(match.group(1))
        else:
            action = None
            order_id = None
    else:
        action = match.group(1).replace("order ", "")
        order_id = int(match.group(2))

    paid_match = re.match(r"^paid\s+order\s+(\d+)\s+(\d[\d,\.]*(?:k|m)?)$", normalized)
    if paid_match:
        order_id = int(paid_match.group(1))
        amount = parse_money_value(paid_match.group(2))
        order = db.query(SalesOrder).filter(
            SalesOrder.id == order_id,
            SalesOrder.owner_phone == owner_phone,
        ).first()
        if not order:
            send_message(phone, f"Order #{order_id} not found.")
            return {"status": "automation_order_not_found"}
        order.payment_status = "PAYMENT_EVIDENCE_RECEIVED"
        order.updated_at = datetime.utcnow()
        db.add(
            SalesOrderPayment(
                order_id=order.id,
                amount=amount,
                status="PENDING_OWNER_CONFIRMATION",
                evidence_ref="owner entered payment evidence",
            )
        )
        db.commit()
        send_message(
            phone,
            f"Payment evidence added for order #{order.id}.\n\n"
            f"Amount claimed: N{amount:,}\n"
            f"Reply: confirm payment {order.id}\n"
            f"Or: reject payment {order.id}"
        )
        return {"status": "automation_order_payment_evidence_added"}

    if not action:
        return None

    order = db.query(SalesOrder).filter(
        SalesOrder.id == order_id,
        SalesOrder.owner_phone == owner_phone,
    ).first()
    if not order:
        send_message(phone, f"Order #{order_id} not found.")
        return {"status": "automation_order_not_found"}

    if action == "confirm":
        order.status = "CONFIRMED"
        message = f"Order #{order.id} confirmed."
        customer_message = f"Your order #{order.id} has been confirmed."
    elif action == "reject":
        order.status = "REJECTED"
        message = f"Order #{order.id} rejected."
        customer_message = f"Your order #{order.id} could not be confirmed. Please contact the business."
    elif action == "deliver":
        order.status = "DELIVERY_PENDING"
        order.delivery_status = "OUT_FOR_DELIVERY"
        message = f"Order #{order.id} marked for delivery."
        customer_message = f"Your order #{order.id} is out for delivery."
    else:
        order.status = "COMPLETED"
        order.delivery_status = "DELIVERED"
        message = f"Order #{order.id} marked as delivered."
        customer_message = f"Your order #{order.id} has been marked delivered."
    order.updated_at = datetime.utcnow()
    db.commit()
    send_message(phone, message)
    notify_customer_order_update(db, send_message, order, customer_message)
    return {"status": "automation_order_updated"}


def handle_automation_owner_command(db, phone, text, user, send_message):
    if not user:
        return None

    clean = (text or "").strip()
    normalized = clean.lower()
    if not re.match(
        r"^(bot|customer bot|auto reply|auto order|part payment|take over|i will take it up from here|bot resume|automation|add product|set price|set payment|payment mode|set delivery|delivery note|pickup address|business hours|min deposit|product|orders|pending orders|confirm order|reject order|deliver order|order \d+ delivered|paid order|confirm payment|reject payment|interested customers|follow up|follow ups|followups|today|daily assistant|business today|pending payments|deliveries|pending deliveries|low stock|send reminders|send order reminders)",
        normalized,
    ):
        return None

    subscription = get_business_subscription(db, user)
    owner = subscription["owner"] or user
    owner_phone = owner.phone
    settings = get_or_create_automation_settings(db, owner_phone)

    if normalized in ["automation", "customer bot", "bot status", "bot settings"]:
        send_message(phone, automation_status_message(settings))
        return {"status": "automation_status"}

    allowed, upgrade_message = ensure_feature_allowed(
        db,
        owner,
        AUTOMATION_FEATURE,
        "customer sales bot",
    )
    if not allowed:
        send_message(phone, upgrade_message)
        return {"status": "automation_upgrade_required"}

    parsed_product = parse_add_product_command(clean)
    if parsed_product:
        item = upsert_product_from_command(db, owner_phone, parsed_product)
        db.commit()
        send_message(phone, build_product_message(item))
        return {"status": "automation_product_saved"}

    price_match = re.match(r"^set\s+price\s+(.+?)\s+(\d[\d,\.]*(?:k|m)?)$", normalized)
    if price_match:
        product_name = price_match.group(1).strip()
        item = find_product_by_name(db, owner_phone, product_name)
        if not item:
            send_message(phone, f"Product not found: {product_name.title()}\n\nSend: add product {product_name} price 20000 qty 5")
            return {"status": "automation_product_not_found"}
        item.selling_price = parse_money_value(price_match.group(2))
        item.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"{item.name.title()} price set to N{item.selling_price:,}.")
        return {"status": "automation_product_price_updated"}

    product_toggle = re.match(r"^product\s+(.+?)\s+(on|off)$", normalized)
    if product_toggle:
        product_name = product_toggle.group(1).strip()
        item = find_product_by_name(db, owner_phone, product_name)
        if not item:
            send_message(phone, f"Product not found: {product_name.title()}")
            return {"status": "automation_product_not_found"}
        item.is_available = product_toggle.group(2) == "on"
        item.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"{item.name.title()} is now {'available' if item.is_available else 'unavailable'}.")
        return {"status": "automation_product_availability_updated"}

    setting_match = re.match(
        r"^(?:set\s+payment|payment mode)\s+(.+)$",
        clean,
        re.I,
    )
    if setting_match:
        settings.payment_modes = setting_match.group(1).strip()
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"Payment mode saved: {settings.payment_modes}")
        return {"status": "automation_payment_mode_updated"}

    setting_match = re.match(r"^(?:set\s+delivery|delivery note)\s+(.+)$", clean, re.I)
    if setting_match:
        settings.delivery_note = setting_match.group(1).strip()
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"Delivery note saved: {settings.delivery_note}")
        return {"status": "automation_delivery_note_updated"}

    setting_match = re.match(r"^pickup address\s+(.+)$", clean, re.I)
    if setting_match:
        settings.pickup_address = setting_match.group(1).strip()
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"Pickup address saved: {settings.pickup_address}")
        return {"status": "automation_pickup_address_updated"}

    setting_match = re.match(r"^business hours\s+(.+)$", clean, re.I)
    if setting_match:
        settings.business_hours = setting_match.group(1).strip()
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"Business hours saved: {settings.business_hours}")
        return {"status": "automation_business_hours_updated"}

    setting_match = re.match(r"^min deposit\s+(\d{1,3})%?$", normalized)
    if setting_match:
        settings.min_deposit_percent = int(setting_match.group(1))
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"Minimum deposit set to {settings.min_deposit_percent}%.")
        return {"status": "automation_min_deposit_updated"}

    order_result = handle_order_owner_command(
        db,
        phone,
        normalized,
        owner_phone,
        send_message,
    )
    if order_result:
        return order_result

    if normalized == "bot on":
        settings.bot_enabled = True
        settings.auto_reply_enabled = True
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(
            phone,
            "Customer bot is ON.\n\n"
            "Customers can start by sending:\n"
            f"shop {owner_phone}\n\n"
            "The bot will answer from your saved stock and alert you when it is unsure."
        )
        return {"status": "automation_bot_on"}

    if normalized == "bot off":
        settings.bot_enabled = False
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, "Customer bot is OFF. You will handle customers manually.")
        return {"status": "automation_bot_off"}

    if normalized in ["auto order on", "auto order off"]:
        settings.auto_order_enabled = normalized.endswith("on")
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(
            phone,
            f"Auto order is {'ON' if settings.auto_order_enabled else 'OFF'}."
        )
        return {"status": "automation_auto_order_updated"}

    if normalized in ["auto reply on", "auto reply off"]:
        settings.auto_reply_enabled = normalized.endswith("on")
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(
            phone,
            f"Auto reply is {'ON' if settings.auto_reply_enabled else 'OFF'}."
        )
        return {"status": "automation_auto_reply_updated"}

    if normalized in ["part payment on", "part payment off"]:
        settings.allow_part_payment = normalized.endswith("on")
        settings.updated_at = datetime.utcnow()
        db.commit()
        send_message(
            phone,
            f"Part payment is {'ON' if settings.allow_part_payment else 'OFF'}."
        )
        return {"status": "automation_part_payment_updated"}

    target_phone = None
    if normalized == "i will take it up from here":
        conversation = db.query(CustomerConversation).filter(
            CustomerConversation.owner_phone == owner_phone,
            CustomerConversation.status == "NEEDS_OWNER",
        ).order_by(
            CustomerConversation.updated_at.desc()
        ).first()
        target_phone = conversation.customer_phone if conversation else None
    else:
        match = re.search(r"(?:take over|bot resume)\s+(\+?\d[\d\s\-]{6,})", normalized)
        if match:
            target_phone = normalize_phone(match.group(1))

    if normalized.startswith("take over") or normalized == "i will take it up from here":
        if not target_phone:
            send_message(phone, "Send: take over 2348012345678")
            return {"status": "automation_takeover_missing_customer"}
        conversation = get_or_create_conversation(db, owner_phone, target_phone)
        conversation.status = "HUMAN_TAKEOVER"
        conversation.stage = "OWNER_HANDLING"
        conversation.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"Bot stopped for {target_phone}. You can take it from here.")
        return {"status": "automation_takeover"}

    if normalized.startswith("bot resume"):
        if not target_phone:
            send_message(phone, "Send: bot resume 2348012345678")
            return {"status": "automation_resume_missing_customer"}
        conversation = get_or_create_conversation(db, owner_phone, target_phone)
        conversation.status = "AUTO"
        conversation.stage = "START"
        conversation.updated_at = datetime.utcnow()
        db.commit()
        send_message(phone, f"Bot resumed for {target_phone}.")
        return {"status": "automation_resume"}

    return None


def find_owner_from_customer_text(db, text):
    match = re.search(r"\b(?:shop|business|store)\s+(\+?\d[\d\s\-]{6,})\b", text or "", re.I)
    if not match:
        return None
    owner_phone = normalize_phone(match.group(1))
    return db.query(User).filter(
        User.phone == owner_phone,
        User.parent_id == None,
    ).first()


def get_active_customer_conversation(db, customer_phone):
    return db.query(CustomerConversation).filter(
        CustomerConversation.customer_phone == customer_phone,
        CustomerConversation.status != "CLOSED",
    ).order_by(
        CustomerConversation.updated_at.desc()
    ).first()


def get_or_create_conversation(db, owner_phone, customer_phone):
    conversation = db.query(CustomerConversation).filter(
        CustomerConversation.owner_phone == owner_phone,
        CustomerConversation.customer_phone == customer_phone,
        CustomerConversation.status != "CLOSED",
    ).order_by(
        CustomerConversation.updated_at.desc()
    ).first()
    if conversation:
        return conversation

    conversation = CustomerConversation(
        owner_phone=owner_phone,
        customer_phone=customer_phone,
        status="AUTO",
        stage="START",
    )
    db.add(conversation)
    db.flush()
    return conversation


def extract_amount(text):
    match = re.search(r"\b(\d[\d,\.]*)(k|m)?\b", text or "", re.I)
    if not match:
        return None
    value = int(float(match.group(1).replace(",", "")))
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        value *= 1000
    elif suffix == "m":
        value *= 1000000
    return value


def extract_payment_amount(text):
    match = re.search(
        r"\b(?:paid|pay|deposit|deposited|transfer|transferred|sent|part payment)\s+(\d[\d,\.]*)(k|m)?\b",
        text or "",
        re.I,
    )
    if not match:
        return extract_amount(text)
    value = int(float(match.group(1).replace(",", "")))
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        value *= 1000
    elif suffix == "m":
        value *= 1000000
    return value


def extract_quantity(text):
    match = re.search(r"\b(?:order|buy|want|need|take|get)\s+(\d+)\b", text or "", re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d+)\s*(?:pcs|pieces|packs|bags|bottles|units)\b", text or "", re.I)
    if match:
        return int(match.group(1))
    return 1


def product_terms_from_text(text):
    clean = re.sub(
        r"\b(?:shop|business|store|how much|price|available|availability|do you have|i want|i need|order|buy|please|pls|is|are|the|a|an|for|of|in stock)\b",
        " ",
        (text or "").lower(),
    )
    clean = re.sub(r"\+?\d[\d\s\-]{6,}", " ", clean)
    clean = re.sub(r"[^a-z0-9\s]", " ", clean)
    words = [word for word in clean.split() if len(word) > 1 and not word.isdigit()]
    return words


def find_matching_inventory_item(db, owner_phone, text):
    terms = product_terms_from_text(text)
    if not terms:
        return None

    query = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone)
    for term in terms[:3]:
        match = query.filter(func.lower(InventoryItem.name).like(f"%{term}%")).first()
        if match:
            return match
    joined = " ".join(terms[:4])
    if joined:
        return query.filter(func.lower(InventoryItem.name).like(f"%{joined}%")).first()
    return None


def item_price(item):
    return item.selling_price


def describe_item(item, settings):
    price = item_price(item)
    lines = [f"{item.name.title()}"]
    if price:
        lines.append(f"Price: N{price:,}")
    if item.quantity is not None:
        unit = f" {item.unit}" if item.unit else ""
        lines.append(f"Available: {item.quantity:,}{unit}")
    if item.size:
        lines.append(f"Size: {item.size}")
    if item.color:
        lines.append(f"Color: {item.color}")
    if item.payment_modes or settings.payment_modes:
        lines.append(f"Payment: {item.payment_modes or settings.payment_modes}")
    if item.delivery_options or settings.delivery_note:
        lines.append(f"Delivery: {item.delivery_options or settings.delivery_note}")
    return "\n".join(lines)


def alert_owner(send_message, owner_phone, customer_phone, message):
    send_message(
        owner_phone,
        "Customer bot needs you.\n\n"
        f"Customer: {customer_phone}\n"
        f"{message}\n\n"
        f"Reply: take over {customer_phone}\n"
        f"Or update stock and reply: bot resume {customer_phone}"
    )


def add_order_payment_evidence(db, order, amount, evidence_ref=None, payment_mode=None):
    if not amount:
        return None
    payment = SalesOrderPayment(
        order_id=order.id,
        amount=amount,
        payment_mode=payment_mode,
        status="PENDING_OWNER_CONFIRMATION",
        evidence_ref=evidence_ref,
    )
    db.add(payment)
    order.payment_status = "PAYMENT_EVIDENCE_RECEIVED"
    order.updated_at = datetime.utcnow()
    return payment


def create_order_from_conversation(db, conversation, item, quantity, payment_amount=None, payment_mode=None, evidence_ref=None):
    price = item_price(item)
    if not price:
        return None
    total = price * quantity
    order = SalesOrder(
        owner_phone=conversation.owner_phone,
        customer_phone=conversation.customer_phone,
        customer_name=conversation.customer_name,
        status="PENDING_OWNER_CONFIRMATION",
        total_amount=total,
        paid_amount=0,
        balance_amount=total,
        payment_status="PAYMENT_EVIDENCE_RECEIVED" if payment_amount else "UNPAID",
        payment_mode=payment_mode,
        due_date=datetime.utcnow() + timedelta(days=1),
    )
    db.add(order)
    db.flush()
    db.add(
        SalesOrderItem(
            order_id=order.id,
            inventory_item_id=item.id,
            product=item.name,
            quantity=quantity,
            unit=item.unit,
            size=item.size,
            color=item.color,
            unit_price=price,
            total=total,
        )
    )
    if payment_amount:
        add_order_payment_evidence(
            db,
            order,
            payment_amount,
            evidence_ref=evidence_ref or "customer payment claim",
            payment_mode=payment_mode,
        )
    conversation.stage = "ORDER_CREATED"
    conversation.updated_at = datetime.utcnow()
    return order


def handle_customer_automation_message(db, phone, text, send_message):
    owner = None
    conversation = get_active_customer_conversation(db, phone)
    if conversation:
        owner = db.query(User).filter(User.phone == conversation.owner_phone).first()
    else:
        owner = find_owner_from_customer_text(db, text)
        if owner:
            conversation = get_or_create_conversation(db, owner.phone, phone)

    if not owner or not conversation:
        return None

    settings = get_or_create_automation_settings(db, owner.phone)
    conversation.last_customer_message = text
    conversation.product_query = text[:200]
    conversation.updated_at = datetime.utcnow()

    if not settings.bot_enabled or not settings.auto_reply_enabled:
        conversation.status = "NEEDS_OWNER"
        db.commit()
        send_message(phone, f"Welcome to {owner.name}. A team member will reply shortly.")
        alert_owner(send_message, owner.phone, phone, f"Customer message: {text}")
        return {"status": "customer_bot_owner_needed"}

    if conversation.status == "HUMAN_TAKEOVER":
        return {"status": "customer_bot_human_takeover"}

    payment_words = re.search(r"\b(paid|pay|deposit|transfer|sent|part payment|receipt|reference|ref)\b", text or "", re.I)
    payment_amount = extract_payment_amount(text) if payment_words else None
    existing_order = get_latest_pending_order_for_customer(db, owner.phone, phone)
    if payment_amount and existing_order and conversation.stage == "ORDER_CREATED":
        add_order_payment_evidence(
            db,
            existing_order,
            payment_amount,
            evidence_ref=text[:500],
        )
        db.commit()
        send_message(
            phone,
            "Payment evidence received.\n\n"
            f"Amount claimed: N{payment_amount:,}\n"
            "The business owner will confirm it."
        )
        alert_owner(
            send_message,
            owner.phone,
            phone,
            f"Payment evidence for order #{existing_order.id}: N{payment_amount:,}.\n"
            f"Reply: confirm payment {existing_order.id}\n"
            f"Or: reject payment {existing_order.id}"
        )
        return {"status": "customer_bot_payment_evidence_received"}

    if conversation.stage == "START":
        send_message(
            phone,
            f"Welcome to {owner.name}.\n\n"
            "What product are you asking about? You can send for example:\n"
            "price rice\n"
            "do you have black shoe"
        )
        conversation.stage = "ASK_PRODUCT"
        db.commit()
        return {"status": "customer_bot_welcome"}

    item = None
    if conversation.matched_item_id:
        item = db.query(InventoryItem).filter(InventoryItem.id == conversation.matched_item_id).first()
    item = find_matching_inventory_item(db, owner.phone, text) or item

    if not item:
        conversation.status = "NEEDS_OWNER"
        conversation.stage = "OWNER_NEEDED"
        db.commit()
        send_message(phone, "Let me confirm this for you.")
        alert_owner(send_message, owner.phone, phone, f"I could not match this product: {text}")
        return {"status": "customer_bot_product_uncertain"}

    price = item_price(item)
    if not price:
        conversation.status = "NEEDS_OWNER"
        conversation.stage = "OWNER_NEEDED"
        db.commit()
        send_message(phone, "Let me confirm the price for you.")
        alert_owner(send_message, owner.phone, phone, f"{item.name.title()} has no selling price.")
        return {"status": "customer_bot_price_missing"}

    if item.is_available is False or (item.quantity is not None and item.quantity <= 0):
        conversation.status = "NEEDS_OWNER"
        conversation.stage = "OWNER_NEEDED"
        db.commit()
        send_message(phone, "Let me confirm availability for you.")
        alert_owner(send_message, owner.phone, phone, f"{item.name.title()} may be out of stock.")
        return {"status": "customer_bot_stock_missing"}

    conversation.matched_item_id = item.id
    quantity = extract_quantity(text)
    conversation.quantity = quantity

    wants_order = bool(re.search(r"\b(order|buy|i want|i need|take|get)\b", text or "", re.I))
    if payment_amount and not settings.allow_part_payment and payment_amount < price * quantity:
        send_message(phone, "Part payment is not available for this order. Please make full payment.")
        db.commit()
        return {"status": "customer_bot_part_payment_disabled"}
    if payment_amount and settings.min_deposit_percent:
        minimum = int((price * quantity * settings.min_deposit_percent) / 100)
        if payment_amount < minimum:
            send_message(
                phone,
                f"Minimum deposit is {settings.min_deposit_percent}%.\n"
                f"For this order, please pay at least N{minimum:,}."
            )
            db.commit()
            return {"status": "customer_bot_deposit_too_low"}

    if payment_amount or (wants_order and settings.auto_order_enabled):
        order = create_order_from_conversation(
            db,
            conversation,
            item,
            quantity,
            payment_amount=payment_amount,
            evidence_ref=text[:500] if payment_amount else None,
        )
        db.commit()
        paid_line = (
            f"Payment evidence: N{payment_amount:,} waiting for owner confirmation\n"
            if payment_amount
            else "Payment: Not received yet\n"
        )
        send_message(
            phone,
            "Order received.\n\n"
            f"{item.name.title()} x {quantity}\n"
            f"Total: N{order.total_amount:,}\n"
            f"{paid_line}"
            f"Balance after confirmed payment will be updated by the owner.\n\n"
            "The business owner will confirm payment and continue from here."
        )
        evidence_line = (
            f" Payment evidence claimed: N{payment_amount:,}."
            if payment_amount
            else " No payment evidence yet."
        )
        alert_owner(
            send_message,
            owner.phone,
            phone,
            f"Order #{order.id}: {item.name.title()} x {quantity}, total N{order.total_amount:,}.{evidence_line}\n"
            f"Reply: confirm payment {order.id} when payment evidence is verified."
        )
        return {"status": "customer_bot_order_created"}

    reply = (
        f"{describe_item(item, settings)}\n\n"
        f"Reply: order {quantity}\n"
        "Or tell me the quantity you want."
    )
    conversation.stage = "ANSWERED_PRODUCT"
    conversation.last_bot_message = reply
    db.commit()
    send_message(phone, reply)
    return {"status": "customer_bot_product_answered"}
