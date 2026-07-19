from datetime import datetime, timedelta, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

from context_memory import save_context
from inventory_suppliers import (
    add_inventory_movement,
    deduct_inventory_for_items,
    find_or_create_supplier,
    get_supplier_balance,
    upsert_stock_with_prices,
)
from messages import balance_status_line, pending_transaction_summary
from models import (
    Branch, Customer, InventoryItem,
    SupplierPayment, SupplierPurchase, Transaction, TransactionNote,
)
from parser import add_transaction_items
from plans import plan_allows_feature
from reports import get_balance
from transaction_setup import update_parse_log_outcome


def _get_default_branch_id(db, owner_phone):
    branch = db.query(Branch).filter(
        Branch.owner_phone == owner_phone,
        Branch.is_default == True,
    ).first()
    return branch.id if branch else None


def _get_recording_branch_id(db, owner_phone, user):
    """Tag the transaction to the recorder's assigned branch when they have one
    (so a branch's staff record into their branch), else the business default."""
    if user and getattr(user, "branch_id", None):
        return user.branch_id
    return _get_default_branch_id(db, owner_phone)


def _add_price_deviation_note(db, owner_phone, tx_id, product, unit_price, recorder_name):
    """
    If unit_price deviates from the inventory selling_price, write a TransactionNote
    recording the deviation and who made it.  Internal only — never shown in customer receipt.
    """
    if not product or not unit_price:
        return
    try:
        from sqlalchemy import func
        item = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone,
            func.lower(InventoryItem.name) == product.lower().strip(),
            InventoryItem.selling_price.isnot(None),
        ).first()
        if not item or not item.selling_price:
            return
        diff = unit_price - item.selling_price
        if diff == 0:
            return
        direction = "discount" if diff < 0 else "premium"
        sign = "−" if diff < 0 else "+"
        note = (
            f"Price {direction}: {product.title()} sold at N{unit_price:,} "
            f"(standard N{item.selling_price:,}, {sign}N{abs(diff):,}). "
            f"Recorded by {recorder_name.title()}."
        )
        db.add(TransactionNote(transaction_id=tx_id, note=note))
    except Exception:
        pass


def pending_stock_items(pending, pending_items):
    if pending_items:
        return pending_items
    if not pending.product:
        return []
    return [{
        "product": pending.product,
        "quantity": pending.quantity or 1,
        "unit": pending.unit,
        "unit_price": pending.unit_price or pending.buy_amount,
        "total": pending.buy_amount,
    }]


def apply_sale_inventory(db, owner_phone, tx_id, user_id, pending, pending_items, source_type):
    items = pending_stock_items(pending, pending_items)
    if not items:
        return [], [], []

    add_transaction_items(db, tx_id, items)
    return deduct_inventory_for_items(
        db, owner_phone, items, source_type, tx_id, user_id,
    )


def build_stock_save_message(stock_updates, stock_missing):
    stock_msg = ""
    if stock_updates:
        stock_msg += "\n\nStock updated:\n" + "\n".join(stock_updates)
    if stock_missing:
        stock_msg += "\n\nStock item not found: " + ", ".join(stock_missing)
        stock_msg += "\nSend STOCK to check inventory."
    return stock_msg


def _notify_customer_receipt(db, customer, tx, balance, user, business_owner_phone, send_message):
    """Send a simple receipt to the customer's WhatsApp after a BUY transaction."""
    if not customer or not customer.customer_phone:
        return
    try:
        from business_templates import receipt_config_for_user
        from customer_commands import _build_reprint_receipt
        from models import User as _U
        owner = db.query(_U).filter(_U.phone == business_owner_phone).first()
        cfg = receipt_config_for_user(owner) if owner else None
        business_name = (owner.name if owner else user.name) or ""
        receipt = _build_reprint_receipt(db, business_name, business_owner_phone, customer, tx, balance, cfg)
        send_message(customer.customer_phone, receipt)
    except Exception:
        pass


def _notify_customer_payment_receipt(db, customer, pay_tx, balance, user, business_owner_phone, recorder_phone, send_message):
    """Deliver a payment receipt after a PAY transaction.

    A receipt is always *generated* as proof of payment. It is delivered to the
    customer's WhatsApp when a phone is on file; otherwise it is sent to the
    person who recorded it (owner/staff) so evidence still exists — no payment
    is left without a receipt just because the customer has no saved phone.
    """
    if not pay_tx:
        return
    try:
        from business_templates import receipt_config_for_user
        from models import User as _U
        owner = db.query(_U).filter(_U.phone == business_owner_phone).first()
        cfg = receipt_config_for_user(owner) if owner else {}
        business_name = (owner.name if owner else (user.name if user else "")) or ""
        customer_label = cfg.get("customer_label", "Customer")
        footer = cfg.get("footer", "Thank you.")
        cust_name = (customer.name.title() if customer and customer.name else "Customer")
        date_str = (pay_tx.created_at or _utcnow()).strftime("%d/%m/%Y  %H:%M")

        lines = [
            business_name.upper(),
            date_str,
            "--------------------",
            f"{customer_label}: {cust_name}",
            "--------------------",
            "PAYMENT RECEIVED",
            f"Paid:     N{pay_tx.amount:,}",
        ]
        if balance > 0:
            lines.append(f"Balance:  N{balance:,}")
        elif balance < 0:
            lines.append(f"Credit:   N{abs(balance):,}")
        else:
            lines.append("Settled:  Fully paid")
        lines.append("--------------------")
        lines.append(f"Ref: PAY-{pay_tx.id}")
        lines.append(footer)
        receipt = "\n".join(lines)

        if customer and customer.customer_phone:
            send_message(customer.customer_phone, receipt)
        elif recorder_phone:
            # No phone on file — hand the receipt to whoever recorded it so the
            # payment still has documented evidence.
            send_message(
                recorder_phone,
                f"🧾 Payment receipt for {cust_name} (no phone on file — keep for your records):\n\n{receipt}",
            )
    except Exception:
        pass


def send_low_stock_alerts(send_message, owner_phone, low_stock_alerts):
    if not low_stock_alerts:
        return
    send_message(
        owner_phone,
        "Low stock alert:\n" + "\n".join(low_stock_alerts)
    )


def save_direct_sale(
    db,
    phone,
    pending,
    user,
    business_owner_phone,
    message_id,
    pending_items,
    inventory_enabled,
    send_message,
):
    # Read before any write — summary uses pending fields that are deleted below
    sale_saved_msg = pending_transaction_summary(pending)

    # Duplicate guard (pure read — outside try)
    recent_tx = db.query(Transaction).filter(
        Transaction.type == "SALE",
        Transaction.amount == pending.buy_amount,
        Transaction.product == pending.product,
        Transaction.recorded_by_id == user.id,
        Transaction.created_at >= _utcnow() - timedelta(minutes=2),
    ).first()
    if recent_tx:
        send_message(phone, "A similar direct sale was already recorded just a moment ago.")
        db.delete(pending)
        db.commit()
        return {"status": "duplicate_sale_prevention"}

    stock_updates = []
    stock_missing = []
    low_stock_alerts = []

    try:
        tx = Transaction(
            customer_id=None,
            type="SALE",
            amount=pending.buy_amount,
            product=pending.product,
            quantity=pending.quantity,
            unit=pending.unit,
            unit_price=pending.unit_price,
            recorded_by_id=user.id,
            message_id=message_id,
            created_at=_utcnow(),
            branch_id=_get_recording_branch_id(db, business_owner_phone, user),
        )
        db.add(tx)
        db.flush()
        _add_price_deviation_note(
            db, business_owner_phone, tx.id,
            pending.product, pending.unit_price, user.name,
        )
        if inventory_enabled:
            stock_updates, stock_missing, low_stock_alerts = apply_sale_inventory(
                db, business_owner_phone, tx.id, user.id, pending, pending_items, "SALE",
            )
        db.delete(pending)
        db.commit()
    except Exception:
        db.rollback()
        send_message(phone, "Something went wrong saving this sale. Please try again.")
        return {"status": "save_error"}

    # Notifications sent after commit — a send failure does not undo the save
    stock_msg = build_stock_save_message(stock_updates, stock_missing)
    send_message(phone, f"{sale_saved_msg}{stock_msg}")
    send_low_stock_alerts(send_message, business_owner_phone, low_stock_alerts)
    return {"status": "direct_sale_saved"}


def save_supplier_pending(db, phone, pending, user, business_owner_phone, pending_items, send_message):
    # Capture fields that will be lost when pending is deleted inside try
    saved_summary = pending_transaction_summary(pending)
    action = pending.action
    supplier_name_key = pending.customer_name

    supplier = None
    try:
        supplier = find_or_create_supplier(db, business_owner_phone, supplier_name_key)
        if action == "SUPPLIER_PURCHASE":
            purchase = SupplierPurchase(
                supplier_id=supplier.id,
                owner_phone=business_owner_phone,
                product=pending.product,
                quantity=pending.quantity,
                unit=pending.unit,
                unit_price=pending.unit_price,
                total=pending.buy_amount,
                paid_amount=pending.paid_amount,
                due_date=pending.due_date,
                recorded_by_id=user.id,
                created_at=_utcnow(),
            )
            db.add(purchase)
            db.flush()
            stock_item = pending_items[0] if pending_items else None
            stock_product = stock_item.get("product") if stock_item else pending.product
            stock_quantity = stock_item.get("quantity") if stock_item else (pending.quantity or 1)
            stock_unit = stock_item.get("unit") if stock_item else pending.unit
            stock_unit_price = stock_item.get("unit_price") if stock_item else pending.unit_price
            add_inventory_movement(
                db,
                business_owner_phone,
                stock_product,
                stock_quantity,
                stock_unit,
                stock_unit_price,
                "IN",
                "SUPPLIER_PURCHASE",
                purchase.id,
                user.id,
                f"Supplied by {supplier.name.title()}",
            )
            import json as _json
            _payload = _json.loads(pending.payload_json or "{}")
            _selling_price = _payload.get("selling_price")
            _retail_unit = _payload.get("retail_unit")
            _retail_per_base = _payload.get("retail_per_base")
            _retail_price = _payload.get("retail_price")
            if _selling_price or (_retail_unit and _retail_per_base):
                _price_item = upsert_stock_with_prices(
                    db, business_owner_phone,
                    stock_product, stock_unit,
                    stock_unit_price, _selling_price,
                )
                if _retail_unit and _retail_per_base and _price_item:
                    _price_item.retail_unit = _retail_unit
                    _price_item.retail_per_base = int(_retail_per_base)
                    if _retail_price:
                        _price_item.retail_price = int(_retail_price)
        else:
            payment = SupplierPayment(
                supplier_id=supplier.id,
                owner_phone=business_owner_phone,
                amount=pending.paid_amount,
                product=pending.product,
                recorded_by_id=user.id,
                created_at=_utcnow(),
            )
            db.add(payment)

        db.delete(pending)
        db.commit()
    except Exception:
        db.rollback()
        send_message(phone, "Something went wrong saving this record. Please try again.")
        return {"status": "save_error"}

    balance = get_supplier_balance(db, supplier.id)
    debt_label = "Total debt" if action == "SUPPLIER_PURCHASE" else "Total debt remaining"
    send_message(
        phone,
        f"{saved_summary}\n{debt_label} to {supplier.name.title()}: N{balance:,}"
    )
    return {"status": "supplier_saved"}


def save_customer_pending(
    db,
    phone,
    pending,
    user,
    business_owner_phone,
    visible_recorded_by_id,
    message_id,
    pending_items,
    inventory_enabled,
    send_message,
):
    from sqlalchemy import func as _func
    customer = db.query(Customer).filter(
        _func.lower(Customer.name) == _func.lower(pending.customer_name),
        Customer.owner_phone == business_owner_phone,
    ).first()
    if not customer:
        send_message(phone, "Customer not found.")
        db.delete(pending)
        db.commit()
        return {"status": "customer_not_found"}

    _pending_action = pending.action
    check_amount = pending.buy_amount if pending.action in ["BUY", "COMBINED"] else pending.paid_amount
    check_type = "BUY" if pending.action == "COMBINED" else pending.action
    recent_tx = db.query(Transaction).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == check_type,
        Transaction.amount == check_amount,
        Transaction.created_at >= _utcnow() - timedelta(minutes=2),
    ).first()

    if recent_tx:
        send_message(
            phone,
            f"A similar transaction for {customer.name.title()} was already recorded just now.\n\n"
            "If this was a mistake, ignore this message. If you truly need to add it again, "
            "wait a minute or send it with a clear note."
        )
        db.delete(pending)
        db.commit()
        return {"status": "duplicate_manual_prevention"}

    # Read before writes — summary uses pending fields that are deleted inside try
    saved_summary = pending_transaction_summary(pending, customer)
    stock_updates = []
    stock_missing = []
    low_stock_alerts = []
    _buy_tx_for_receipt = None
    _pay_tx_for_receipt = None

    try:
        _default_branch_id = _get_recording_branch_id(db, business_owner_phone, user)

        if pending.action == "BUY":
            _pending_items_count = len(pending_items) if pending_items else 0
            tx = Transaction(
                customer_id=customer.id,
                type="BUY",
                amount=pending.buy_amount,
                product=pending.product,
                quantity=pending.quantity,
                unit=pending.unit,
                unit_price=pending.unit_price,
                due_date=pending.due_date,
                recorded_by_id=user.id,
                message_id=message_id,
                created_at=_utcnow(),
                branch_id=_default_branch_id,
                is_invoice=(_pending_items_count > 1),
            )
            db.add(tx)
            db.flush()
            _buy_tx_for_receipt = tx
            _add_price_deviation_note(
                db, business_owner_phone, tx.id,
                pending.product, pending.unit_price, user.name,
            )
            if inventory_enabled:
                stock_updates, stock_missing, low_stock_alerts = apply_sale_inventory(
                    db, business_owner_phone, tx.id, user.id, pending, pending_items, "CUSTOMER_SALE",
                )

        elif pending.action == "PAY":
            tx = Transaction(
                customer_id=customer.id,
                type="PAY",
                amount=pending.paid_amount,
                recorded_by_id=user.id,
                message_id=message_id,
                created_at=_utcnow(),
                branch_id=_default_branch_id,
            )
            db.add(tx)
            db.flush()
            _pay_tx_for_receipt = tx
            if pending.due_date:
                latest_buy = db.query(Transaction).filter(
                    Transaction.customer_id == customer.id,
                    Transaction.type == "BUY",
                ).order_by(
                    Transaction.created_at.desc()
                ).first()
                if latest_buy:
                    latest_buy.due_date = pending.due_date

        elif pending.action == "COMBINED":
            buy_tx = Transaction(
                customer_id=customer.id,
                type="BUY",
                amount=pending.buy_amount,
                product=pending.product,
                quantity=pending.quantity,
                unit=pending.unit,
                unit_price=pending.unit_price,
                due_date=pending.due_date,
                recorded_by_id=user.id,
                message_id=f"{message_id}_buy",
                created_at=_utcnow(),
                branch_id=_default_branch_id,
            )
            db.add(buy_tx)
            db.flush()
            _buy_tx_for_receipt = buy_tx
            _add_price_deviation_note(
                db, business_owner_phone, buy_tx.id,
                pending.product, pending.unit_price, user.name,
            )
            if inventory_enabled:
                stock_updates, stock_missing, low_stock_alerts = apply_sale_inventory(
                    db, business_owner_phone, buy_tx.id, user.id, pending, pending_items, "CUSTOMER_SALE",
                )
            pay_tx = Transaction(
                customer_id=customer.id,
                type="PAY",
                amount=pending.paid_amount,
                recorded_by_id=user.id,
                message_id=f"{message_id}_pay",
                created_at=_utcnow(),
                branch_id=_default_branch_id,
            )
            db.add(pay_tx)

        save_context(
            db, phone,
            last_customer=customer.name,
            last_command=pending.action,
            last_amount=pending.buy_amount or pending.paid_amount,
            last_topic="transaction",
        )

        db.delete(pending)
        db.commit()
    except Exception:
        db.rollback()
        send_message(phone, "Something went wrong saving this transaction. Please try again.")
        return {"status": "save_error"}

    # Post-commit reads and notifications
    balance = get_balance(db, customer.id, visible_recorded_by_id)
    msg = f"{saved_summary}\n{balance_status_line(balance)}"
    msg += build_stock_save_message(stock_updates, stock_missing)
    if customer.customer_phone and _buy_tx_for_receipt and _pending_action in ("BUY", "COMBINED"):
        msg += f"\n\nReceipt sent to {customer.name.title()}."
    elif _pay_tx_for_receipt and _pending_action == "PAY":
        # A receipt is always produced; note where it went.
        msg += (f"\n\nPayment receipt sent to {customer.name.title()}."
                if customer.customer_phone
                else "\n\nPayment receipt below (no phone on file for this customer).")
    send_message(phone, msg)
    send_low_stock_alerts(send_message, business_owner_phone, low_stock_alerts)
    if customer.customer_phone and _buy_tx_for_receipt and _pending_action in ("BUY", "COMBINED"):
        _notify_customer_receipt(db, customer, _buy_tx_for_receipt, balance, user, business_owner_phone, send_message)
    elif _pay_tx_for_receipt and _pending_action == "PAY":
        _notify_customer_payment_receipt(db, customer, _pay_tx_for_receipt, balance, user, business_owner_phone, phone, send_message)
    return {"status": "saved"}


def save_confirmed_pending_transaction(
    db,
    phone,
    pending,
    user,
    business_owner_phone,
    visible_recorded_by_id,
    message_id,
    pending_items,
    subscription,
    send_message,
):
    inventory_enabled = bool(
        subscription and plan_allows_feature(subscription.get("plan"), "INVENTORY")
    )

    if pending.action == "SALE":
        return save_direct_sale(
            db,
            phone,
            pending,
            user,
            business_owner_phone,
            message_id,
            pending_items,
            inventory_enabled,
            send_message,
        )

    if pending.action in ["SUPPLIER_PURCHASE", "SUPPLIER_PAYMENT"]:
        return save_supplier_pending(
            db,
            phone,
            pending,
            user,
            business_owner_phone,
            pending_items,
            send_message,
        )

    if pending.action in ["BUY", "PAY", "COMBINED"]:
        return save_customer_pending(
            db,
            phone,
            pending,
            user,
            business_owner_phone,
            visible_recorded_by_id,
            message_id,
            pending_items,
            inventory_enabled,
            send_message,
        )

    return None
