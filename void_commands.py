from datetime import datetime, timezone

from models import Customer, Transaction, TransactionNote, User
from reports import get_owner_transaction_query


def handle_void_transaction(db, phone, parsed, user, business_owner_phone, visible_recorded_by_id, send_message):
    if not user:
        send_message(phone, "You need to be registered to void transactions.")
        return {"status": "void_unregistered"}

    ref = (parsed.get("ref") or "last").strip().lower()
    reason = (parsed.get("reason") or "").strip()

    is_owner = user.phone == business_owner_phone

    # Staff see only their own transactions unless owner granted full view
    staff_filter = visible_recorded_by_id if not is_owner else None

    base_query = get_owner_transaction_query(
        db, business_owner_phone, recorded_by_id=staff_filter
    )

    if ref == "last":
        tx = base_query.order_by(Transaction.id.desc()).first()
    else:
        try:
            tx_id = int(ref)
        except ValueError:
            send_message(phone, "Invalid transaction reference. Use 'void last' or 'void [number]'.")
            return {"status": "void_bad_ref"}
        tx = base_query.filter(Transaction.id == tx_id).first()

    if not tx:
        send_message(phone, "Transaction not found or already voided.")
        return {"status": "void_not_found"}

    # Staff can only void transactions they personally recorded
    if not is_owner and tx.recorded_by_id != user.id:
        send_message(
            phone,
            f"Transaction #{tx.id} was not recorded by you.\n"
            "You can only void transactions you recorded yourself.\n"
            "Ask the business owner to void it."
        )
        return {"status": "void_permission_denied"}

    customer = None
    if tx.customer_id:
        customer = db.query(Customer).filter(Customer.id == tx.customer_id).first()

    customer_label = customer.name.title() if customer else "Direct Sale"
    type_label = {"BUY": "Credit Sale", "PAY": "Payment", "SALE": "Direct Sale"}.get(tx.type, tx.type)
    void_reason = reason or "No reason given"

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    tx.is_voided = True
    tx.void_reason = void_reason
    tx.voided_by_id = user.id
    tx.voided_at = now

    # Voiding a sale returns the stock it deducted (no-op for payments).
    from inventory_suppliers import restore_inventory_for_voided_sale
    restored = restore_inventory_for_voided_sale(db, business_owner_phone, tx.id, user.id)
    stock_line = ""
    if restored:
        parts = ", ".join(
            f"{r['name'].title()} +{int(r['quantity'])}{(' ' + r['unit']) if r['unit'] else ''}"
            for r in restored
        )
        stock_line = f"\nStock returned: {parts}"

    note_text = (
        f"VOIDED by {user.name.title()} on {now.strftime('%d/%m/%Y %H:%M')}. "
        f"Reason: {void_reason}"
    )
    db.add(TransactionNote(
        transaction_id=tx.id,
        author_user_id=user.id,
        note=note_text,
    ))
    db.commit()

    send_message(
        phone,
        f"Transaction #{tx.id} has been voided.\n\n"
        f"Customer: {customer_label}\n"
        f"Type: {type_label}\n"
        f"Amount: N{tx.amount:,}\n"
        f"Reason: {void_reason}{stock_line}\n\n"
        "This will no longer count in balances or reports."
    )

    # Alert owner when a staff member voids a transaction
    if not is_owner:
        recorded_at = tx.created_at.strftime("%d/%m/%Y %H:%M") if tx.created_at else "Unknown"
        send_message(
            business_owner_phone,
            f"*VOID ALERT* - Staff action\n\n"
            f"*{user.name.title()}* voided a transaction.\n\n"
            f"Transaction: #{tx.id}\n"
            f"Customer: {customer_label}\n"
            f"Type: {type_label}\n"
            f"Amount: N{tx.amount:,}\n"
            f"Originally recorded: {recorded_at}\n"
            f"Voided at: {now.strftime('%d/%m/%Y %H:%M')}\n"
            f"Reason given: {void_reason}\n\n"
            "Check your dashboard if this looks suspicious."
        )

    return {"status": "void_success"}
