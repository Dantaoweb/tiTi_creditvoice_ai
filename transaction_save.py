from datetime import datetime, timedelta

from inventory_suppliers import (
    add_inventory_movement,
    deduct_inventory_for_items,
    find_or_create_supplier,
    get_supplier_balance,
)
from messages import balance_status_line, pending_transaction_summary
from models import Customer, CustomerMemory, SupplierPayment, SupplierPurchase, Transaction
from parser import add_transaction_items
from plans import plan_allows_feature
from reports import get_balance


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
        return [], []

    add_transaction_items(db, tx_id, items)
    return deduct_inventory_for_items(
        db,
        owner_phone,
        items,
        source_type,
        tx_id,
        user_id,
    )


def build_stock_save_message(stock_updates, stock_missing):
    stock_msg = ""
    if stock_updates:
        stock_msg += "\n\nStock updated:\n" + "\n".join(stock_updates)
    if stock_missing:
        stock_msg += "\n\nStock item not found: " + ", ".join(stock_missing)
        stock_msg += "\nSend STOCK to check inventory."
    return stock_msg


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
    sale_saved_msg = pending_transaction_summary(pending)
    recent_tx = db.query(Transaction).filter(
        Transaction.type == "SALE",
        Transaction.amount == pending.buy_amount,
        Transaction.product == pending.product,
        Transaction.recorded_by_id == user.id,
        Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2),
    ).first()

    if recent_tx:
        send_message(phone, "A similar direct sale was already recorded just a moment ago.")
        db.delete(pending)
        db.commit()
        return {"status": "duplicate_sale_prevention"}

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
        created_at=datetime.utcnow(),
    )
    db.add(tx)
    db.flush()
    stock_updates = []
    stock_missing = []
    if inventory_enabled:
        stock_updates, stock_missing = apply_sale_inventory(
            db,
            business_owner_phone,
            tx.id,
            user.id,
            pending,
            pending_items,
            "SALE",
        )

    db.delete(pending)
    db.commit()

    stock_msg = build_stock_save_message(stock_updates, stock_missing)
    send_message(phone, f"{sale_saved_msg}{stock_msg}")
    return {"status": "direct_sale_saved"}


def save_supplier_pending(db, phone, pending, user, business_owner_phone, pending_items, send_message):
    supplier = find_or_create_supplier(db, business_owner_phone, pending.customer_name)
    saved_summary = pending_transaction_summary(pending)

    if pending.action == "SUPPLIER_PURCHASE":
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
            created_at=datetime.utcnow(),
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
    else:
        payment = SupplierPayment(
            supplier_id=supplier.id,
            owner_phone=business_owner_phone,
            amount=pending.paid_amount,
            product=pending.product,
            recorded_by_id=user.id,
            created_at=datetime.utcnow(),
        )
        db.add(payment)

    db.delete(pending)
    db.commit()
    balance = get_supplier_balance(db, supplier.id)
    send_message(phone, f"{saved_summary}\nSupplier balance: N{balance:,}")
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
    customer = db.query(Customer).filter(
        Customer.name == pending.customer_name,
        Customer.owner_phone == business_owner_phone,
    ).first()
    if not customer:
        send_message(phone, "Customer not found.")
        db.delete(pending)
        db.commit()
        return {"status": "customer_not_found"}

    check_amount = pending.buy_amount if pending.action in ["BUY", "COMBINED"] else pending.paid_amount
    check_type = "BUY" if pending.action == "COMBINED" else pending.action
    recent_tx = db.query(Transaction).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == check_type,
        Transaction.amount == check_amount,
        Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2),
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

    saved_summary = pending_transaction_summary(pending, customer)
    stock_updates = []
    stock_missing = []

    if pending.action == "BUY":
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
            created_at=datetime.utcnow(),
        )
        db.add(tx)
        db.flush()
        if inventory_enabled:
            stock_updates, stock_missing = apply_sale_inventory(
                db,
                business_owner_phone,
                tx.id,
                user.id,
                pending,
                pending_items,
                "CUSTOMER_SALE",
            )

    elif pending.action == "PAY":
        tx = Transaction(
            customer_id=customer.id,
            type="PAY",
            amount=pending.paid_amount,
            recorded_by_id=user.id,
            message_id=message_id,
            created_at=datetime.utcnow(),
        )
        db.add(tx)
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
            created_at=datetime.utcnow(),
        )
        db.add(buy_tx)
        db.flush()
        if inventory_enabled:
            stock_updates, stock_missing = apply_sale_inventory(
                db,
                business_owner_phone,
                buy_tx.id,
                user.id,
                pending,
                pending_items,
                "CUSTOMER_SALE",
            )

        pay_tx = Transaction(
            customer_id=customer.id,
            type="PAY",
            amount=pending.paid_amount,
            recorded_by_id=user.id,
            message_id=f"{message_id}_pay",
            created_at=datetime.utcnow(),
        )
        db.add(pay_tx)

    memory = db.query(CustomerMemory).filter(CustomerMemory.phone == phone).first()
    if not memory:
        db.add(CustomerMemory(phone=phone, last_customer=customer.name))
    else:
        memory.last_customer = customer.name

    db.delete(pending)
    db.commit()

    balance = get_balance(db, customer.id, visible_recorded_by_id)
    msg = f"{saved_summary}\n{balance_status_line(balance)}"
    msg += build_stock_save_message(stock_updates, stock_missing)

    send_message(phone, msg)
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
