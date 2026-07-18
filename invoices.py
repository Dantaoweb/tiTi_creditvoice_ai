"""
Formal invoice support (web).

An invoice is a credit sale presented as a formal document: itemised
products/services with a total, amount due, due date, and a per-business
sequential number (INV-0001, INV-0002, …).

The number is assigned by the system — never typed by a user — the first time
an invoice is issued for a sale, and then reused. Numbering is per business
(scoped by the customer's owner_phone) so each business sees a clean 1, 2, 3…
sequence, and the value is stamped inside the caller's transaction so two
invoices can never receive the same number.
"""
from datetime import datetime, timezone

from sqlalchemy import func

from models import Customer, Transaction


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_invoice_number(number):
    """Render a stored invoice number as a formal reference, e.g. 1 -> 'INV-0001'."""
    if not number:
        return None
    return f"INV-{int(number):04d}"


def issue_invoice_number(db, tx, owner_phone):
    """Assign (once) and return this sale's per-business invoice number.

    Idempotent: if the sale already has a number it is returned unchanged.
    The caller is responsible for committing; the number is set on `tx` so it
    is persisted inside the same transaction that reads MAX()+1, keeping the
    sequence gap-free and collision-free under the app's single writer.
    """
    if tx.invoice_number:
        return tx.invoice_number

    current_max = (
        db.query(func.max(Transaction.invoice_number))
        .join(Customer, Transaction.customer_id == Customer.id)
        .filter(Customer.owner_phone == owner_phone)
        .scalar()
    )
    tx.invoice_number = int(current_max or 0) + 1
    tx.invoiced_at = _utcnow()
    return tx.invoice_number
