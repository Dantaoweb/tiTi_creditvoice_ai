"""POS (Point of Sale) save logic for the web app."""
import uuid

from models import Customer, InventoryItem, InventoryMovement, Transaction, TransactionItem, User, utcnow


def save_pos_sale(db, owner_phone, user_id, customer_id, items, payment_amount):
    """
    Save a POS sale and deduct inventory.

    Transaction type rules:
    - No customer → SALE
    - Customer + fully paid → SALE
    - Customer + partial payment → BUY (total) + PAY (paid amount)
    - Customer + zero payment → BUY (full debt)

    Returns receipt dict.
    """
    total = sum(int(it.get("qty", 1)) * int(it.get("unit_price", 0)) for it in items)
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
        )
        db.add(pay_tx)
        db.flush()
        pay_tx_id = pay_tx.id

    # Deduct inventory for items linked to an inventory record
    for it in items:
        item_id = it.get("inventory_item_id")
        if not item_id:
            continue
        inv = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
        if not inv:
            continue
        qty = int(it.get("qty", 1))
        inv.quantity = (inv.quantity or 0) - qty
        inv.updated_at = utcnow()
        db.add(InventoryMovement(
            owner_phone=owner_phone,
            item_id=inv.id,
            movement_type="OUT",
            quantity=qty,
            unit_price=int(it.get("unit_price", 0)) or None,
            source_type="POS",
            source_id=main_tx.id,
            recorded_by_id=user_id,
            note="POS sale",
        ))

    db.commit()

    return {
        "receipt_id": main_tx.id,
        "total": total,
        "paid": paid,
        "change": 0,
        "balance_owed": total - paid if has_customer else 0,
        "transaction_type": tx_type,
        "pay_tx_id": pay_tx_id,
    }


def get_pos_receipt(db, tx_id):
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        return None
    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == tx_id).all()
    customer = db.query(Customer).filter(Customer.id == tx.customer_id).first() if tx.customer_id else None
    recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
    return {
        "id": tx.id,
        "type": tx.type,
        "total": tx.amount,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.customer_phone,
        } if customer else None,
        "recorded_by": recorder.name if recorder else None,
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
