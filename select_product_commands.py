import json
import re
from datetime import datetime, timezone

from business_templates import DEFAULT_RECEIPT_CONFIG, receipt_config_for_user
from constants import (
    ACTION_SELECT_PRODUCT_CART,
    ACTION_SELECT_PRODUCT_CONFIRM,
    ACTION_SELECT_PRODUCT_CUSTOMER,
    ACTION_SELECT_PRODUCT_DUE,
    ACTION_SELECT_PRODUCT_LIST,
    ACTION_SELECT_PRODUCT_PAYMENT,
    ACTION_SELECT_PRODUCT_QTY,
)
from inventory_suppliers import deduct_inventory_for_items
from models import Customer, InventoryItem, PendingAction, Transaction, User
from parser import add_transaction_items
from plans import plan_allows_feature


# ── Helpers ──────────────────────────────────────────────────────────────────

def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_payload(pending):
    return json.loads(pending.payload_json or "{}")


def _load_cart(pending):
    return json.loads(pending.items_json or "[]")


def _save_payload(pending, payload):
    pending.payload_json = json.dumps(payload)


def _save_cart(pending, cart):
    pending.items_json = json.dumps(cart)


def _cart_total(cart):
    return sum(item["total"] for item in cart)


# ── Message builders ──────────────────────────────────────────────────────────

def build_product_list_message(items):
    msg = "Select product:\n\n"
    for i, item in enumerate(items, start=1):
        unit_label = f" {item.unit}" if item.unit else ""
        stock_label = f" ({item.quantity:,}{unit_label} in stock)" if item.quantity else ""
        msg += f"{i}. {item.name.title()} - N{item.selling_price:,}{stock_label}\n"
    return msg.strip()


def build_cart_message(cart):
    total = _cart_total(cart)
    msg = "Cart:\n\n"
    for i, item in enumerate(cart, start=1):
        deviation = item.get("deviation", 0)
        standard = item.get("standard_price", 0)
        cost = item.get("cost_price")
        price = item.get("unit_price", 0)

        notes = []
        if deviation < 0:
            notes.append(f"↓ N{abs(deviation):,} below standard (N{standard:,})")
        # Above standard: silent on screen — recorded as internal note only
        if cost and price < cost:
            loss = cost - price
            notes.append(f"⚠ N{loss:,} below cost price (N{cost:,}) — selling at a loss")

        note_str = ("\n   " + "\n   ".join(notes)) if notes else ""
        msg += (
            f"{i}. {item['product'].title()} x {item['quantity']} "
            f"@ N{item['unit_price']:,} = N{item['total']:,}{note_str}\n"
        )
    msg += f"\nTotal: N{total:,}\n\n"
    msg += "1. Add another product\n2. Checkout\n3. Cancel"
    return msg


def build_confirm_message(cart, customer_name, paid, total, due_date_str=None):
    balance = total - paid
    total_discount = sum(
        abs(item.get("deviation", 0)) * item.get("quantity", 1)
        for item in cart
        if item.get("deviation", 0) < 0
    )
    has_loss = any(item.get("below_cost") for item in cart)

    msg = "Confirm sale:\n\n"
    msg += f"Customer: {customer_name.title()}\n"
    for item in cart:
        msg += f"{item['product'].title()} x {item['quantity']} = N{item['total']:,}\n"
    msg += f"\nTotal:   N{total:,}\n"

    if total_discount > 0:
        standard_total = total + total_discount
        msg += f"Standard: N{standard_total:,}\n"
        msg += f"Discount: N{total_discount:,}\n"
    if has_loss:
        msg += "⚠ One or more items sold below cost price.\n"

    msg += f"Paid:    N{paid:,}\n"
    if balance > 0:
        msg += f"Balance: N{balance:,}\n"
        if due_date_str:
            msg += f"Due:     {due_date_str}\n"

    msg += "\n\nYES to save."
    if total_discount > 0:
        msg += "\nYES RECEIPT to save and show discount on customer receipt."
    return msg


def build_owner_receipt(business_name, customer_name, cart, total, paid, balance, due_date_str, tx_id, config=None):
    cfg = config or DEFAULT_RECEIPT_CONFIG
    now = _utcnow()
    date_str = now.strftime("%d/%m/%Y  %H:%M")
    lines = [
        business_name.upper(),
        date_str,
        "--------------------",
        f"{cfg['customer_label']}: {customer_name.title()}",
        "--------------------",
    ]
    for item in cart:
        lines.append(f"{item['product'].title()}")
        lines.append(f"  x{item['quantity']} @ N{item['unit_price']:,} = N{item['total']:,}")
    lines.append("--------------------")
    lines.append(f"{cfg['amount_label']}:    N{total:,}")
    lines.append(f"Paid:     N{paid:,}")
    if balance > 0:
        lines.append(f"Balance:  N{balance:,}")
        if due_date_str:
            lines.append(f"Due:      {due_date_str}")
    lines.append("--------------------")
    lines.append(f"Ref: TXN-{tx_id}")
    lines.append(cfg["footer"])
    return "\n".join(lines)


def build_customer_receipt(
    business_name, customer_name, cart, total, paid,
    balance, due_date_str, tx_id, config=None, show_discount=False,
):
    cfg = config or DEFAULT_RECEIPT_CONFIG
    now = _utcnow()
    date_str = now.strftime("%d/%m/%Y  %H:%M")
    lines = [
        cfg["title"].upper(),
        business_name.title(),
        date_str,
        "--------------------",
        f"{cfg['customer_label']}: {customer_name.title()}",
        "--------------------",
    ]

    total_saved = 0
    for item in cart:
        deviation = item.get("deviation", 0)
        standard = item.get("standard_price", 0)
        lines.append(f"{item['product'].title()}")
        if show_discount and deviation < 0 and standard:
            # Show standard price crossed out, then actual
            item_saving = abs(deviation) * item["quantity"]
            total_saved += item_saving
            lines.append(
                f"  x{item['quantity']} @ N{standard:,} = N{standard * item['quantity']:,}"
            )
            lines.append(f"  Discount:  -N{item_saving:,}")
            lines.append(f"  You pay:    N{item['total']:,}")
        else:
            lines.append(
                f"  x{item['quantity']} @ N{item['unit_price']:,} = N{item['total']:,}"
            )

    lines.append("--------------------")
    lines.append(f"{cfg['amount_label']}:    N{total:,}")
    if show_discount and total_saved > 0:
        lines.append(f"You saved: N{total_saved:,}")
    lines.append(f"Paid:     N{paid:,}")
    if balance > 0:
        lines.append(f"Balance:  N{balance:,}")
        if due_date_str:
            lines.append(f"Due date: {due_date_str}")
    lines.append("--------------------")
    lines.append(f"Ref: TXN-{tx_id}")
    lines.append(cfg["footer"])
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def start_select_product(db, phone, business_owner_phone, send_message):
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == business_owner_phone,
        InventoryItem.selling_price.isnot(None),
        InventoryItem.selling_price > 0,
        InventoryItem.is_available == True,
    ).order_by(InventoryItem.name.asc()).limit(20).all()

    if not items:
        send_message(
            phone,
            "No products with a selling price found.\n\n"
            "Set up your products first:\n"
            "add stock rice cost 3000 sell 4000\n"
            "add stock paracetamol 500mg cost 150 sell 200"
        )
        return {"status": "select_product_empty"}

    item_ids = [item.id for item in items]
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    pending = PendingAction(
        phone=phone,
        action=ACTION_SELECT_PRODUCT_LIST,
        customer_name="",
        last_customer="",
        buy_amount=0,
        paid_amount=0,
        items_json=json.dumps([]),
        payload_json=json.dumps({"item_ids": item_ids}),
    )
    db.add(pending)
    db.commit()

    send_message(phone, build_product_list_message(items))
    return {"status": "select_product_list"}


# ── State handlers ────────────────────────────────────────────────────────────

def _handle_list_selection(db, phone, text, pending, business_owner_phone, send_message):
    payload = _load_payload(pending)
    item_ids = payload.get("item_ids", [])

    if not text.strip().isdigit():
        items = db.query(InventoryItem).filter(InventoryItem.id.in_(item_ids)).all()
        items.sort(key=lambda x: item_ids.index(x.id))
        send_message(
            phone,
            build_product_list_message(items) + "\n\nReply with a number.\nSend MENU to go back."
        )
        return {"status": "select_product_invalid_selection"}

    index = int(text.strip()) - 1
    if index < 0 or index >= len(item_ids):
        send_message(phone, f"Send a number between 1 and {len(item_ids)}.")
        return {"status": "select_product_out_of_range"}

    item = db.query(InventoryItem).filter(InventoryItem.id == item_ids[index]).first()
    if not item:
        send_message(phone, "Product not found. Send 'select product' to start again.")
        return {"status": "select_product_item_missing"}

    payload["selected_id"] = item.id
    payload["selected_name"] = item.name
    payload["selected_price"] = item.selling_price    # standard selling price
    payload["selected_cost_price"] = item.cost_price  # for below-cost alert
    payload["selected_unit"] = item.unit
    _save_payload(pending, payload)
    pending.action = ACTION_SELECT_PRODUCT_QTY
    db.commit()

    unit_label = f" {item.unit}" if item.unit else ""
    send_message(
        phone,
        f"Quantity for {item.name.title()}?\n"
        f"Price: N{item.selling_price:,}{unit_label} each"
    )
    return {"status": "select_product_qty_asked"}


def _parse_qty_price(text):
    """
    Parse trader input at the quantity step.
    Accepts:  "3"  |  "3 at 2500"  |  "3 2500"  |  "3 @ 2500"  |  "3 at 2.5k"
    Returns (qty, price_override) — price_override is None if not given.
    """
    import re as _re
    text = text.strip()
    m = _re.match(
        r"^(?P<qty>\d+)(?:\s*(?:at|@|,)?\s*(?P<price>\d[\d,\.]*(?:k|m)?))?$",
        text, _re.I,
    )
    if not m or not m.group("qty"):
        return None, None
    qty = int(m.group("qty"))
    if qty < 1:
        return None, None
    price_str = m.group("price")
    if not price_str:
        return qty, None
    ps = price_str.lower().replace(",", "").strip()
    try:
        if ps.endswith("k"):
            price = int(float(ps[:-1]) * 1_000)
        elif ps.endswith("m"):
            price = int(float(ps[:-1]) * 1_000_000)
        else:
            price = int(float(ps))
    except ValueError:
        return qty, None
    return qty, price


def _handle_qty_input(db, phone, text, pending, business_owner_phone, send_message):
    payload = _load_payload(pending)
    cart = _load_cart(pending)

    qty, price_override = _parse_qty_price(text)
    if qty is None:
        send_message(phone, "Send quantity. Examples:\n3\n3 at 2500 (custom price)")
        return {"status": "select_product_invalid_qty"}

    standard_price = payload.get("selected_price", 0)    # = selling_price
    cost_price = payload.get("selected_cost_price")
    price = price_override if price_override is not None else standard_price
    item_total = qty * price
    deviation = (price - standard_price) if price_override is not None else 0
    below_cost = bool(cost_price and price < cost_price)

    # Warn if selling more than available stock
    _inv_id = payload.get("selected_id")
    _stock_warning = ""
    if _inv_id:
        _inv_item = db.query(InventoryItem).filter(InventoryItem.id == _inv_id).first()
        if _inv_item and _inv_item.quantity is not None and qty > _inv_item.quantity:
            _stock_warning = (
                f"\n\n⚠ *Low stock:* Only {_inv_item.quantity:,} {_inv_item.unit or 'unit(s)'} left. "
                f"Selling {qty} will leave you with negative stock."
            )

    cart.append({
        "product": payload["selected_name"],
        "quantity": qty,
        "unit_price": price,
        "unit": payload.get("selected_unit"),
        "total": item_total,
        "inv_id": payload.get("selected_id"),
        "standard_price": standard_price,
        "deviation": deviation,      # negative=discount, positive=premium, 0=standard
        "cost_price": cost_price,
        "below_cost": below_cost,
    })

    total = _cart_total(cart)
    _save_cart(pending, cart)
    pending.buy_amount = total

    # Clear selected item from payload but keep item_ids
    for k in ("selected_id", "selected_name", "selected_price",
              "selected_cost_price", "selected_unit"):
        payload.pop(k, None)
    _save_payload(pending, payload)

    pending.action = ACTION_SELECT_PRODUCT_CART
    db.commit()

    send_message(phone, build_cart_message(cart) + _stock_warning)
    return {"status": "select_product_cart_shown"}


def _handle_cart_choice(db, phone, normalized, pending, business_owner_phone, send_message):
    cart = _load_cart(pending)
    payload = _load_payload(pending)

    if normalized in ["1", "add", "add another", "add another product", "more"]:
        # Re-show product list
        item_ids = payload.get("item_ids", [])
        items = db.query(InventoryItem).filter(
            InventoryItem.id.in_(item_ids)
        ).all()
        items.sort(key=lambda x: (item_ids.index(x.id) if x.id in item_ids else 999))
        pending.action = ACTION_SELECT_PRODUCT_LIST
        db.commit()
        send_message(phone, build_product_list_message(items))
        return {"status": "select_product_add_another"}

    if normalized in ["2", "checkout", "check out", "done"]:
        total = _cart_total(cart)
        pending.action = ACTION_SELECT_PRODUCT_CUSTOMER
        db.commit()
        send_message(
            phone,
            f"Total: N{total:,}\n\nCustomer name?"
        )
        return {"status": "select_product_checkout"}

    if normalized in ["3", "cancel", "exit", "back"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Cancelled. Send 'select product' to start again.")
        return {"status": "select_product_cancelled"}

    send_message(phone, build_cart_message(cart))
    return {"status": "select_product_cart_reprompt"}


def _handle_customer_name(db, phone, text, pending, business_owner_phone, send_message):
    name = text.strip().lower()
    if not name or len(name) < 2:
        send_message(phone, "Send the customer name.")
        return {"status": "select_product_customer_invalid"}

    # Look up existing customer to get their phone
    customer = db.query(Customer).filter(
        Customer.owner_phone == business_owner_phone,
        Customer.name == name,
    ).first()

    if not customer:
        customer = Customer(name=name, owner_phone=business_owner_phone)
        db.add(customer)
        db.flush()

    pending.customer_name = name
    pending.customer_phone = customer.customer_phone
    pending.action = ACTION_SELECT_PRODUCT_PAYMENT
    db.commit()

    total = pending.buy_amount
    send_message(
        phone,
        f"How much did {name.title()} pay?\n"
        f"Total debt: N{total:,}\n"
        "Send 0 if nothing was paid."
    )
    return {"status": "select_product_payment_asked"}


def _handle_payment(db, phone, text, pending, business_owner_phone, send_message):
    text = text.strip().replace(",", "")
    if not re.match(r"^\d+$", text):
        send_message(phone, "Send the amount paid. Example: 500\nOr send 0 for full credit.")
        return {"status": "select_product_payment_invalid"}

    paid = int(text)
    total = pending.buy_amount
    balance = total - paid

    if paid > total:
        send_message(phone, f"Paid amount cannot exceed total N{total:,}.\nSend the correct amount.")
        return {"status": "select_product_overpayment"}

    pending.paid_amount = paid

    if balance > 0:
        pending.action = ACTION_SELECT_PRODUCT_DUE
        db.commit()
        send_message(
            phone,
            f"Balance: N{balance:,}\n"
            f"When should {pending.customer_name.title()} pay?\n\n"
            "Send date DD/MM/YYYY or SKIP to save without a due date."
        )
        return {"status": "select_product_due_asked"}

    # No balance — go straight to confirm
    cart = _load_cart(pending)
    pending.action = ACTION_SELECT_PRODUCT_CONFIRM
    db.commit()
    send_message(phone, build_confirm_message(cart, pending.customer_name, paid, total))
    return {"status": "select_product_confirm_shown"}


def _handle_due_date(db, phone, text, pending, send_message):
    normalized = text.strip().lower()
    cart = _load_cart(pending)
    total = pending.buy_amount
    paid = pending.paid_amount
    due_date_str = None
    due_date = None

    if normalized not in ["skip", "no", "none"]:
        date_match = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", text)
        if date_match:
            day, month, year = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
            if year < 100:
                year += 2000
            try:
                due_date = datetime(year, month, day)
                due_date_str = due_date.strftime("%d/%m/%Y")
            except ValueError:
                send_message(phone, "Invalid date. Try DD/MM/YYYY or SKIP.")
                return {"status": "select_product_due_invalid"}
        elif "tomorrow" in normalized:
            from datetime import timedelta
            due_date = _utcnow() + timedelta(days=1)
            due_date_str = due_date.strftime("%d/%m/%Y")
        else:
            send_message(phone, "Send a date DD/MM/YYYY or SKIP.")
            return {"status": "select_product_due_invalid"}

    payload = _load_payload(pending)
    payload["due_date_str"] = due_date_str
    _save_payload(pending, payload)
    pending.due_date = due_date
    pending.action = ACTION_SELECT_PRODUCT_CONFIRM
    db.commit()

    send_message(phone, build_confirm_message(cart, pending.customer_name, paid, total, due_date_str))
    return {"status": "select_product_confirm_shown"}


def _handle_confirm(db, phone, normalized, pending, user, business_owner_phone, visible_recorded_by_id, subscription, message_id, business_name, send_message):
    if normalized in ["edit", "no", "cancel", "back"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Cancelled. Send 'select product' to start again.")
        return {"status": "select_product_confirm_cancelled"}

    show_discount = normalized in ["yes receipt", "yes d", "yes discount", "yes r"]
    if normalized not in ["yes", "yes receipt", "yes d", "yes discount", "yes r"]:
        cart = _load_cart(pending)
        payload = _load_payload(pending)
        send_message(
            phone,
            build_confirm_message(
                cart, pending.customer_name, pending.paid_amount,
                pending.buy_amount, payload.get("due_date_str")
            )
        )
        return {"status": "select_product_confirm_reprompt"}

    # ── Capture fields before any write (pending is deleted inside try) ─────────
    cart = _load_cart(pending)
    payload = _load_payload(pending)
    total = pending.buy_amount
    paid = pending.paid_amount
    balance = total - paid
    due_date = pending.due_date
    due_date_str = payload.get("due_date_str")
    customer_name = pending.customer_name
    customer_phone = pending.customer_phone

    # Customer lookup — pure read, outside try
    customer = db.query(Customer).filter(
        Customer.owner_phone == business_owner_phone,
        Customer.name == customer_name,
    ).first()

    inventory_enabled = bool(
        subscription and plan_allows_feature(subscription.get("plan"), "INVENTORY")
    )
    stock_lines = []
    low_alerts = []
    buy_tx = None

    try:
        if not customer:
            customer = Customer(name=customer_name, owner_phone=business_owner_phone)
            db.add(customer)
            db.flush()

        # BUY transaction
        buy_tx = Transaction(
            customer_id=customer.id,
            type="BUY",
            amount=total,
            product=", ".join(i["product"] for i in cart),
            due_date=due_date,
            recorded_by_id=user.id,
            message_id=f"{message_id}_sp_buy",
            created_at=_utcnow(),
        )
        db.add(buy_tx)
        db.flush()

        # Internal price deviation notes
        from models import TransactionNote
        for item in cart:
            deviation = item.get("deviation", 0)
            if deviation != 0:
                direction = "discount" if deviation < 0 else "premium"
                sign = "−" if deviation < 0 else "+"
                db.add(TransactionNote(
                    transaction_id=buy_tx.id,
                    note=(
                        f"Price {direction}: {item['product'].title()} sold at "
                        f"N{item['unit_price']:,} "
                        f"(standard N{item.get('standard_price', 0):,}, "
                        f"{sign}N{abs(deviation):,}). "
                        f"Recorded by {user.name.title()}."
                    ),
                ))

        # Record individual items
        add_transaction_items(db, buy_tx.id, [
            {
                "product": i["product"],
                "quantity": i["quantity"],
                "unit": i["unit"],
                "unit_price": i["unit_price"],
                "total": i["total"],
            }
            for i in cart
        ])

        # PAY transaction
        if paid > 0:
            db.add(Transaction(
                customer_id=customer.id,
                type="PAY",
                amount=paid,
                recorded_by_id=user.id,
                message_id=f"{message_id}_sp_pay",
                created_at=_utcnow(),
            ))

        # Inventory deduction
        if inventory_enabled:
            stock_items = [
                {"product": i["product"], "quantity": i["quantity"],
                 "unit": i["unit"], "unit_price": i["unit_price"]}
                for i in cart
            ]
            stock_lines, _missing, low_alerts = deduct_inventory_for_items(
                db, business_owner_phone, stock_items, "CUSTOMER_SALE", buy_tx.id, user.id,
            )

        db.delete(pending)
        db.commit()
    except Exception:
        db.rollback()
        send_message(phone, "Something went wrong saving this sale. Please try again.")
        return {"status": "save_error"}

    # Low-stock alerts sent after commit
    if low_alerts:
        from transaction_save import send_low_stock_alerts
        send_low_stock_alerts(send_message, business_owner_phone, low_alerts)

    # ── Get niche receipt config from owner's business type ───────────────────
    owner_user = db.query(User).filter(User.phone == business_owner_phone).first()
    receipt_cfg = receipt_config_for_user(owner_user) if owner_user else DEFAULT_RECEIPT_CONFIG

    # ── Build and send owner receipt ──────────────────────────────────────────
    owner_receipt = build_owner_receipt(
        business_name, customer_name, cart, total, paid, balance, due_date_str, buy_tx.id, receipt_cfg
    )
    if stock_lines:
        owner_receipt += "\n\nStock updated:\n" + "\n".join(stock_lines)

    send_message(phone, owner_receipt)

    # ── Forward receipt to customer if phone exists ───────────────────────────
    if customer_phone:
        customer_receipt = build_customer_receipt(
            business_name, customer_name, cart, total, paid, balance,
            due_date_str, buy_tx.id, receipt_cfg, show_discount=show_discount,
        )
        send_message(customer_phone, customer_receipt)
    else:
        send_message(
            phone,
            f"Tip: Save {customer_name.title()}'s number to send them receipts:\n"
            f"{customer_name} phone 08012345678"
        )

    return {"status": "select_product_saved"}


# ── Main pending dispatcher ───────────────────────────────────────────────────

def handle_select_product_pending(
    db, phone, text, pending, user,
    business_owner_phone, visible_recorded_by_id,
    subscription, message_id, business_name, send_message,
):
    action = pending.action

    if action == ACTION_SELECT_PRODUCT_LIST:
        return _handle_list_selection(db, phone, text, pending, business_owner_phone, send_message)

    if action == ACTION_SELECT_PRODUCT_QTY:
        return _handle_qty_input(db, phone, text, pending, business_owner_phone, send_message)

    if action == ACTION_SELECT_PRODUCT_CART:
        return _handle_cart_choice(db, phone, text.strip().lower(), pending, business_owner_phone, send_message)

    if action == ACTION_SELECT_PRODUCT_CUSTOMER:
        return _handle_customer_name(db, phone, text, pending, business_owner_phone, send_message)

    if action == ACTION_SELECT_PRODUCT_PAYMENT:
        return _handle_payment(db, phone, text, pending, business_owner_phone, send_message)

    if action == ACTION_SELECT_PRODUCT_DUE:
        return _handle_due_date(db, phone, text, pending, send_message)

    if action == ACTION_SELECT_PRODUCT_CONFIRM:
        return _handle_confirm(
            db, phone, text.strip().lower(), pending, user,
            business_owner_phone, visible_recorded_by_id,
            subscription, message_id, business_name, send_message,
        )

    return None
