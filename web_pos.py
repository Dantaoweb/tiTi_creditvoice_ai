"""POS (Point of Sale) save logic for the web app."""
import uuid

from models import Customer, InventoryItem, InventoryMovement, Transaction, TransactionItem, User, utcnow


def save_pos_sale(db, owner_phone, user_id, customer_id, items, payment_amount, branch_id=None, due_date=None):
    """
    Save a POS sale and deduct inventory.

    Transaction type rules:
    - No customer → SALE
    - Customer + fully paid → SALE
    - Customer + partial payment → BUY (total) + PAY (paid amount)
    - Customer + zero payment → BUY (full debt)

    Returns receipt dict.
    """
    total = sum(float(it.get("qty", 1)) * int(it.get("unit_price", 0)) for it in items)
    paid = min(int(payment_amount or 0), total)

    has_customer = bool(customer_id)
    is_credit = has_customer and paid < total

    tx_type = "BUY" if is_credit else "SALE"

    main_tx = Transaction(
        customer_id=customer_id,
        type=tx_type,
        amount=total,
        product=f"POS Sale ({len(items)} item{'s' if len(items) != 1 else ''})",
        recorded_by_id=user_id,
        message_id=f"web-pos-{uuid.uuid4()}",
        branch_id=branch_id,
        due_date=due_date if is_credit else None,
    )
    db.add(main_tx)
    db.flush()

    for it in items:
        qty = int(it.get("qty", 1))
        up = int(it.get("unit_price", 0))
        db.add(TransactionItem(
            transaction_id=main_tx.id,
            product=it.get("name", ""),
            quantity=qty,
            unit=it.get("unit"),
            unit_price=up,
            total=qty * up,
        ))

    pay_tx_id = None
    if is_credit and paid > 0:
        pay_tx = Transaction(
            customer_id=customer_id,
            type="PAY",
            amount=paid,
            product=f"Part payment — POS #{main_tx.id}",
            recorded_by_id=user_id,
            message_id=f"web-pos-pay-{uuid.uuid4()}",
            branch_id=branch_id,
        )
        db.add(pay_tx)
        db.flush()
        pay_tx_id = pay_tx.id

    # Deduct inventory for items linked to an inventory record (skip service items)
    for it in items:
        item_id = it.get("inventory_item_id")
        if not item_id:
            continue
        inv = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
        if not inv:
            continue
        if inv.quantity is None or inv.category == "service":
            continue  # service items have no stock to deduct
        qty = float(it.get("qty", 1))
        sold_unit = (it.get("sold_unit") or "").lower().strip()

        # Retail sub-unit sale: deduct a fraction of one base unit per piece
        if sold_unit and inv.retail_unit and sold_unit == inv.retail_unit.lower() and inv.retail_per_base:
            deduct = qty / inv.retail_per_base
        else:
            # Fraction prefix sale: "half", "quarter", "1/8" sent from POS as a multiplier
            fraction = float(it.get("fraction", 1.0) or 1.0)
            deduct = qty * fraction

        inv.quantity = max(0.0, (inv.quantity or 0.0) - deduct)
        inv.updated_at = utcnow()
        db.add(InventoryMovement(
            owner_phone=owner_phone,
            item_id=inv.id,
            movement_type="OUT",
            quantity=deduct,
            unit_price=int(it.get("unit_price", 0)) or None,
            source_type="POS",
            source_id=main_tx.id,
            recorded_by_id=user_id,
            note="POS sale",
        ))

    db.commit()

    return {
        "receipt_id": main_tx.id,
        "total": int(total),
        "paid": paid,
        "change": 0,
        "balance_owed": int(total - paid) if has_customer else 0,
        "transaction_type": tx_type,
        "pay_tx_id": pay_tx_id,
    }


def get_pos_receipt(db, tx_id, user=None):
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        return None
    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == tx_id).all()
    customer = db.query(Customer).filter(Customer.id == tx.customer_id).first() if tx.customer_id else None
    recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None

    # Find the linked PAY transaction to get actual paid amount for credit sales
    paid_amount = tx.amount  # default: fully paid
    if tx.type == "BUY":
        pay_tx = db.query(Transaction).filter(
            Transaction.product == f"Part payment — POS #{tx_id}",
            Transaction.customer_id == tx.customer_id,
        ).first()
        paid_amount = pay_tx.amount if pay_tx else 0

    balance_owed = max(0, tx.amount - paid_amount) if customer else 0

    # Business-specific receipt config
    from business_templates import receipt_config_for_user, DEFAULT_RECEIPT_CONFIG
    config = receipt_config_for_user(user) if user else DEFAULT_RECEIPT_CONFIG

    # Business name from user record
    biz_name = None
    if user:
        biz_name = getattr(user, "business_name", None) or getattr(user, "name", None)

    return {
        "id": tx.id,
        "type": tx.type,
        "total": tx.amount,
        "paid": paid_amount,
        "balance_owed": balance_owed,
        "due_date": tx.due_date.isoformat() if tx.due_date else None,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.customer_phone,
        } if customer else None,
        "recorded_by": recorder.name if recorder else None,
        "biz_name": biz_name,
        "config": config,
        "items": [
            {
                "product": it.product,
                "qty": it.quantity,
                "unit": it.unit,
                "unit_price": it.unit_price,
                "total": it.total,
            }
            for it in items
        ],
    }
