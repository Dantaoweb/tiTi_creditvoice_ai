from models import Customer, PendingAction
from messages import with_confirm_disclaimer
from transaction_setup import build_projected_balance_line


def handle_artisan_payment_pending(
    db,
    phone,
    text,
    pending,
    business_owner_phone,
    visible_recorded_by_id,
    send_message,
):
    """
    Handles the ARTISAN_PAYMENT_CHOICE pending state.
    Triggered when a payment is ambiguous — could be new service income or
    a customer paying an existing debt.
    """
    normalized = text.lower().strip()

    if normalized in ["1", "service", "work", "income", "new work"]:
        pending.action = "SALE"
        pending.buy_amount = pending.paid_amount
        pending.product = pending.product or f"service/work - {pending.customer_name}"
        pending.quantity = 1
        pending.unit_price = pending.buy_amount
        db.commit()
        send_message(
            phone,
            with_confirm_disclaimer(
                f"Confirm service income, no customer debt:\n"
                f"{pending.product.title()} - N{pending.buy_amount:,}\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            ),
        )
        return {"status": "artisan_service_confirm"}

    if normalized in ["2", "debt", "debit", "old debt", "existing debt"]:
        from sqlalchemy import func as _func
        customer = db.query(Customer).filter(
            _func.lower(Customer.name) == _func.lower(pending.customer_name),
            Customer.owner_phone == business_owner_phone
        ).first()
        if not customer:
            customer = Customer(
                name=pending.customer_name,
                owner_phone=business_owner_phone
            )
            db.add(customer)
            db.flush()

        pending.action = "PAY"
        pending.last_customer = customer.name
        db.commit()
        balance_after_line = build_projected_balance_line(
            db,
            customer.id,
            {"buy_amount": 0, "paid_amount": pending.paid_amount},
            visible_recorded_by_id
        )
        send_message(
            phone,
            with_confirm_disclaimer(
                f"Confirm debt payment:\n"
                f"{customer.name.title()} paid N{pending.paid_amount:,}\n"
                f"{balance_after_line}\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            ),
        )
        return {"status": "artisan_debt_payment_confirm"}

    if normalized in ["edit", "change", "cancel", "back", "exit"]:
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            "Enter again. Example:\nI received 1000 for doing chair\nor\nAde paid 7000"
        )
        return {"status": "artisan_choice_cancelled"}

    # Default: re-show the choice
    send_message(
        phone,
        f"{pending.customer_name.title()} paid you N{pending.paid_amount:,}.\n\n"
        "What is this for?\n"
        "1. For the work/service you did, no customer debt\n"
        "2. He/she paid debt owed to you"
    )
    return {"status": "artisan_choice_waiting"}
