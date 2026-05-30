from datetime import datetime, timezone
from sqlalchemy import func

from business_templates import DEFAULT_RECEIPT_CONFIG, receipt_config_for_user
from models import Customer, Transaction, TransactionItem, TransactionNote, User
from reports import (
    format_transaction_note_thread,
    get_balance,
    get_transaction_notes,
    get_visible_transaction,
)
from subscriptions import ensure_feature_allowed


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _build_reprint_receipt(db, business_name, business_owner_phone, customer, tx, balance, config):
    cfg = config or DEFAULT_RECEIPT_CONFIG
    now = _utcnow()
    date_str = tx.created_at.strftime("%d/%m/%Y  %H:%M") if tx.created_at else now.strftime("%d/%m/%Y  %H:%M")

    lines = [
        business_name.upper(),
        date_str,
        "--------------------",
        f"{cfg['customer_label']}: {customer.name.title()}",
        "--------------------",
    ]

    # Use TransactionItems if they exist, otherwise use the transaction's own fields
    items = db.query(TransactionItem).filter(TransactionItem.transaction_id == tx.id).all()
    if items:
        for item in items:
            lines.append(f"{item.product.title()}")
            qty_label = f"x{item.quantity} " if item.quantity and item.quantity > 1 else ""
            lines.append(f"  {qty_label}@ N{item.unit_price:,} = N{item.total:,}")
    elif tx.product:
        qty = tx.quantity or 1
        lines.append(f"{tx.product.title()}")
        lines.append(f"  x{qty} = N{tx.amount:,}")
    else:
        lines.append(f"N{tx.amount:,}")

    lines.append("--------------------")
    lines.append(f"{cfg['amount_label']}:    N{tx.amount:,}")
    if balance > 0:
        lines.append(f"Balance:  N{balance:,}")
    elif balance < 0:
        lines.append(f"Credit:   N{abs(balance):,}")
    else:
        lines.append("Settled:  Fully paid")
    lines.append("--------------------")
    lines.append(f"Ref: TXN-{tx.id}")
    lines.append(cfg["footer"])
    return "\n".join(lines)


def handle_customer_command(
    db,
    phone,
    text,
    parsed,
    user,
    business_owner_phone,
    visible_recorded_by_id,
    send_message,
):
    command_type = parsed.get("type")

    if command_type == "ADD_TRANSACTION_NOTE":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "TRANSACTION_NOTES", "Transaction notes")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "transaction_notes_plan_blocked"}

        visible_tx = get_visible_transaction(
            db,
            business_owner_phone,
            parsed["transaction_id"],
            visible_recorded_by_id,
        )
        if not visible_tx:
            send_message(phone, "Transaction not found.")
            return {"status": "transaction_note_not_found"}

        transaction, customer = visible_tx
        note = TransactionNote(
            transaction_id=transaction.id,
            author_user_id=user.id,
            note=parsed["note"],
        )
        db.add(note)
        db.commit()
        transaction_name = customer.name.title() if customer else "direct sale"
        send_message(
            phone,
            f"Note added to transaction #{transaction.id} for {transaction_name}."
        )
        return {"status": "transaction_note_added"}

    if command_type == "TRANSACTION_NOTES":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "TRANSACTION_NOTES", "Transaction notes")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "transaction_notes_plan_blocked"}

        visible_tx, notes = get_transaction_notes(
            db,
            business_owner_phone,
            parsed["transaction_id"],
            visible_recorded_by_id,
        )
        if not visible_tx:
            send_message(phone, "Transaction not found.")
            return {"status": "transaction_notes_not_found"}

        transaction, customer = visible_tx
        send_message(
            phone,
            format_transaction_note_thread(transaction, customer, notes)
        )
        return {"status": "transaction_notes"}

    if command_type == "CUSTOMER_TRANSACTIONS":
        customer = db.query(Customer).filter(
            Customer.name == parsed.get("name", ""),
            Customer.owner_phone == business_owner_phone,
        ).first()
        if not customer:
            send_message(phone, "Customer not found.")
            return {"status": "customer_transactions_not_found"}

        buy_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
        )
        pay_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "PAY",
        )
        tx_query = db.query(Transaction).filter(
            Transaction.customer_id == customer.id
        )
        if visible_recorded_by_id:
            buy_query = buy_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
            pay_query = pay_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
            tx_query = tx_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)

        tx_count = tx_query.count()
        if visible_recorded_by_id and tx_count == 0:
            send_message(phone, "Customer not found.")
            return {"status": "customer_transactions_not_found"}

        total_buy = buy_query.scalar()
        total_pay = pay_query.scalar()
        recent_transactions = tx_query.order_by(
            Transaction.created_at.desc()
        ).limit(5).all()
        recent_lines = ""
        if recent_transactions:
            recent_lines = "\n\nRecent transactions\n"
            for tx in recent_transactions:
                tx_date = tx.created_at.strftime("%d/%m/%Y")
                recent_lines += f"#{tx.id} {tx_date} {tx.type}: N{tx.amount:,}\n"
            recent_lines += "\nAdd note:\nnote transaction 12 customer promised Friday"

        send_message(
            phone,
            f"{customer.name.title()} transactions\n"
            f"Total: {tx_count:,}\n"
            f"Bought: N{total_buy:,}\n"
            f"Paid: N{total_pay:,}"
            f"{recent_lines}"
        )
        return {"status": "customer_transactions"}

    if command_type == "PRINT_RECEIPT":
        # Look up owner for niche receipt config
        owner = db.query(User).filter(User.phone == business_owner_phone).first()
        receipt_cfg = receipt_config_for_user(owner) if owner else DEFAULT_RECEIPT_CONFIG
        business_name = (owner.name if owner else "") or "Business"

        # Find by transaction ID or by customer name (most recent BUY)
        tx_id = parsed.get("transaction_id")
        customer = None

        if tx_id:
            tx = db.query(Transaction).filter(
                Transaction.id == tx_id,
                Transaction.type == "BUY",
            ).first()
            if not tx or not tx.customer_id:
                send_message(phone, f"Transaction #{tx_id} not found.")
                return {"status": "print_receipt_tx_not_found"}
            customer = db.query(Customer).filter(Customer.id == tx.customer_id).first()
        else:
            name = parsed.get("customer_name", "").lower()
            customer = db.query(Customer).filter(
                Customer.owner_phone == business_owner_phone,
                Customer.name == name,
            ).first()
            if not customer:
                send_message(phone, f"Customer not found: {name.title()}\nTry: print receipt [exact name]")
                return {"status": "print_receipt_not_found"}
            tx = db.query(Transaction).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "BUY",
            ).order_by(Transaction.created_at.desc()).first()
            if not tx:
                send_message(phone, f"No purchase record found for {name.title()}.")
                return {"status": "print_receipt_no_tx"}

        balance = get_balance(db, customer.id, visible_recorded_by_id)
        receipt = _build_reprint_receipt(
            db, business_name, business_owner_phone,
            customer, tx, balance, receipt_cfg,
        )

        send_message(phone, receipt)

        if customer.customer_phone:
            send_message(customer.customer_phone, receipt)
        else:
            send_message(
                phone,
                f"Tip: Save {customer.name.title()}'s number to send receipts:\n"
                f"{customer.name} phone 08012345678"
            )
        return {"status": "print_receipt_sent"}

    if command_type == "BALANCE":
        name = text.replace("balance", "").strip().lower()
        customer = db.query(Customer).filter(
            Customer.name == name,
            Customer.owner_phone == business_owner_phone,
        ).first()

        if not customer:
            send_message(phone, "Customer not found.")
            return {"status": "not_found"}

        balance = get_balance(db, customer.id, visible_recorded_by_id)
        if visible_recorded_by_id:
            has_customer_access = db.query(Transaction).filter(
                Transaction.customer_id == customer.id,
                Transaction.recorded_by_id == visible_recorded_by_id,
            ).first()
            if not has_customer_access:
                send_message(phone, "Customer not found.")
                return {"status": "not_found"}

        if balance < 0:
            msg = f"{customer.name} credit: N{abs(balance):,}"
        else:
            msg = f"{customer.name} balance: N{balance:,}"

        send_message(phone, msg)
        return {"status": "balance"}

    return None
