"""POS (Point of Sale) save logic for the web app."""
import uuid

from models import Customer, InventoryItem, InventoryMovement, Transaction, TransactionItem, User, utcnow


def save_pos_sale(db, owner_phone, user_id, customer_id, items, payment_amount,
                  branch_id=None, due_date=None, customer_name=None, customer_phone=None,
                  service_date=None):
    """
    Save a POS sale and deduct inventory.

    Transaction type rules:
    - No customer → SALE
    - Customer + fully paid → SALE
    - Customer + partial payment → BUY (total) + PAY (paid amount)
    - Customer + zero payment → BUY (full debt)

    A customer not yet on the list can be added inline: pass `customer_name`
    (and optionally `customer_phone`) with no `customer_id`. An existing
    customer with that name is reused; otherwise a new one is created. This
    lets part payments be recorded for walk-ins who aren't on the list yet.

    Returns receipt dict.
    """
    # A supplied customer_id MUST belong to this business — otherwise a caller
    # could attach a sale/debt to another business's customer (cross-tenant IDOR).
    if customer_id:
        owned = db.query(Customer).filter(
            Customer.id == customer_id,
            Customer.owner_phone == owner_phone,
        ).first()
        if not owned:
            raise ValueError("Customer not found for this business.")

    # Reject non-positive quantities/prices — a negative line would create a
    # negative-amount transaction that corrupts reports and can be abused to wipe
    # a customer's debt or invent credit.
    for _it in items:
        try:
            _q = float(_it.get("qty", 1)); _p = int(_it.get("unit_price", 0))
        except (TypeError, ValueError):
            raise ValueError("Invalid item quantity or price.")
        if _q <= 0 or _p < 0:
            raise ValueError("Item quantity must be positive and price cannot be negative.")
    if int(payment_amount or 0) < 0:
        raise ValueError("Payment cannot be negative.")

    # Resolve an inline (unlisted) customer by name when no id was selected.
    if not customer_id and customer_name and customer_name.strip():
        cname = customer_name.strip()
        cphone = (customer_phone or "").strip() or None
        existing = db.query(Customer).filter(
            Customer.owner_phone == owner_phone,
            Customer.name == cname,
        ).first()
        if existing:
            customer_id = existing.id
            if cphone and not existing.customer_phone:
                existing.customer_phone = cphone
        else:
            new_customer = Customer(
                owner_phone=owner_phone,
                name=cname,
                customer_phone=cphone,
            )
            db.add(new_customer)
            db.flush()
            customer_id = new_customer.id

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
        service_date=service_date,
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

    # Deduct inventory (skip service items). Harmonised with quick sale and item
    # customization: prefer the explicitly-linked item, but fall back to matching
    # by name so a POS line typed by name still deducts from the same stock when
    # a same-named item exists — the same find_matching_inventory_item the other
    # sale paths use, so identical names deduct identically everywhere.
    from inventory_suppliers import find_matching_inventory_item
    for it in items:
        item_id = it.get("inventory_item_id")
        inv = db.query(InventoryItem).filter(InventoryItem.id == item_id).first() if item_id else None
        if not inv:
            name = (it.get("name") or "").strip()
            inv = find_matching_inventory_item(db, owner_phone, name, it.get("unit")) if name else None
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

    # Payment receipt (standalone PAY transaction) — amount paid + current balance
    if tx.type == "PAY":
        from business_templates import receipt_config_for_user, DEFAULT_RECEIPT_CONFIG
        from reports import get_balance
        cfg = receipt_config_for_user(user) if user else DEFAULT_RECEIPT_CONFIG
        bname = (getattr(user, "business_name", None) or getattr(user, "name", None)) if user else None
        bal = get_balance(db, tx.customer_id) if tx.customer_id else 0
        return {
            "id": tx.id,
            "type": "PAY",
            "total": tx.amount,
            "paid": tx.amount,
            "balance_owed": max(0, bal),
            "due_date": None,
            "service_date": None,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "customer": {
                "id": customer.id, "name": customer.name, "phone": customer.customer_phone,
            } if customer else None,
            "recorded_by": recorder.name if recorder else None,
            "biz_name": bname,
            "config": cfg,
            "items": [],
            "note": tx.product,
            "invoice_number": tx.invoice_number,
        }

    # Find the linked PAY transaction to get the actual paid amount for credit
    # sales. Sales are created two ways, each linking the payment differently:
    #   • Web POS    → PAY tagged product "Part payment — POS #<id>"
    #   • WhatsApp   → BUY message_id "<base>_buy", PAY message_id "<base>_pay"
    paid_amount = tx.amount  # default: fully paid
    if tx.type == "BUY":
        pay_tx = db.query(Transaction).filter(
            Transaction.product == f"Part payment — POS #{tx_id}",
            Transaction.customer_id == tx.customer_id,
        ).first()
        if not pay_tx and tx.message_id and tx.message_id.endswith("_buy"):
            _base = tx.message_id[:-4]
            pay_tx = db.query(Transaction).filter(
                Transaction.message_id == f"{_base}_pay",
                Transaction.customer_id == tx.customer_id,
                Transaction.type == "PAY",
            ).first()
        paid_amount = pay_tx.amount if pay_tx else 0

    balance_owed = max(0, tx.amount - paid_amount) if customer else 0

    # Business-specific receipt config
    from business_templates import receipt_config_for_user, DEFAULT_RECEIPT_CONFIG
    config = receipt_config_for_user(user) if user else DEFAULT_RECEIPT_CONFIG

    # Business name + address from the owner record
    biz_name = None
    biz_address = None
    if user:
        biz_name = getattr(user, "business_name", None) or getattr(user, "name", None)
        biz_address = getattr(user, "address", None)

    # Branch this sale belongs to (its own name/address print on the receipt)
    branch_name = branch_address = None
    if tx.branch_id:
        from models import Branch
        _br = db.query(Branch).filter(Branch.id == tx.branch_id).first()
        if _br:
            branch_name = _br.name
            branch_address = _br.address

    return {
        "id": tx.id,
        "type": tx.type,
        "total": tx.amount,
        "paid": paid_amount,
        "balance_owed": balance_owed,
        "due_date": tx.due_date.isoformat() if tx.due_date else None,
        "service_date": tx.service_date.isoformat() if tx.service_date else None,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.customer_phone,
        } if customer else None,
        "recorded_by": recorder.name if recorder else None,
        "biz_name": biz_name,
        "biz_address": biz_address,
        "branch_name": branch_name,
        "branch_address": branch_address,
        "config": config,
        "invoice_number": tx.invoice_number,
        "invoice_sent_at": tx.invoice_sent_at.isoformat() if tx.invoice_sent_at else None,
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


def format_receipt_text(receipt):
    """Build a WhatsApp text receipt from a get_pos_receipt() dict — used to
    send the customer their receipt after a web sale or payment."""
    from business_templates import DEFAULT_RECEIPT_CONFIG
    cfg = receipt.get("config") or DEFAULT_RECEIPT_CONFIG
    is_payment = receipt.get("type") == "PAY"
    cust = receipt.get("customer") or {}
    total = int(receipt.get("total") or 0)
    paid = int(receipt.get("paid") or 0)
    bal = int(receipt.get("balance_owed") or 0)

    lines = []
    lines.append("PAYMENT RECEIPT" if is_payment else (cfg.get("title") or "RECEIPT").upper())
    if receipt.get("biz_name"):
        lines.append(receipt["biz_name"])
    lines.append("--------------------")
    if cust.get("name"):
        lines.append(f"{cfg.get('customer_label', 'Customer')}: {cust['name'].title()}")
        lines.append("--------------------")

    if is_payment:
        lines.append(f"Amount Paid: N{paid:,}")
        if bal > 0:
            lines.append(f"Balance:     N{bal:,}")
    else:
        for it in receipt.get("items", []):
            lines.append(f"{(it.get('product') or '').title()}")
            lines.append(f"  x{it.get('qty', 1)} @ N{int(it.get('unit_price', 0)):,} = N{int(it.get('total', 0)):,}")
        lines.append("--------------------")
        lines.append(f"{cfg.get('amount_label', 'Total')}: N{total:,}")
        lines.append(f"Paid:  N{paid:,}")
        if bal > 0:
            lines.append(f"Balance: N{bal:,}")
        if receipt.get("service_date"):
            lines.append(f"Ready by: {receipt['service_date'][:10]}")

    lines.append("--------------------")
    lines.append(f"Ref: TXN-{receipt.get('id')}")
    if cfg.get("footer"):
        lines.append(cfg["footer"])
    return "\n".join(lines)
