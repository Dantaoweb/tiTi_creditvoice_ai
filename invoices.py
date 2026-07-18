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


def format_invoice_text(receipt):
    """Build the WhatsApp invoice message from a get_pos_receipt() dict.

    Framed as a request to pay: itemised lines, total, amount due and due date,
    under the business name and INV-xxxx reference.
    """
    cfg = receipt.get("config") or {}
    cust = receipt.get("customer") or {}
    total = int(receipt.get("total") or 0)
    due = int(receipt.get("balance_owed") or 0)
    ref = format_invoice_number(receipt.get("invoice_number"))

    lines = ["*INVOICE*"]
    if receipt.get("biz_name"):
        lines.append(receipt["biz_name"])
    if ref:
        lines.append(ref)
    lines.append("--------------------")
    if cust.get("name"):
        lines.append(f"Bill to: {cust['name'].title()}")
        lines.append("--------------------")
    for it in receipt.get("items", []):
        name = (it.get("product") or "").title()
        qty = it.get("qty", 1)
        lines.append(f"{name}")
        lines.append(f"  x{qty} @ N{int(it.get('unit_price', 0)):,} = N{int(it.get('total', 0)):,}")
    lines.append("--------------------")
    lines.append(f"Total:       N{total:,}")
    lines.append(f"*Amount due: N{due:,}*")
    if receipt.get("due_date"):
        lines.append(f"Due by: {receipt['due_date'][:10]}")
    lines.append("--------------------")
    if cfg.get("footer"):
        lines.append(cfg["footer"])
    return "\n".join(lines)


def _invoice_status(outstanding, due_date, now):
    """Open / Overdue / Paid from an invoice's outstanding amount and due date."""
    if outstanding <= 0:
        return "paid"
    if due_date and due_date < now:
        return "overdue"
    return "open"


def list_business_invoices(db, owner_phone, status_filter=None):
    """Return this business's issued invoices (newest first) with a derived
    per-invoice outstanding and status.

    Because the app keeps a single running balance per customer rather than
    allocating payments to specific sales, each invoice's outstanding is derived
    by FIFO allocation: the customer's total (non-voided) payments are applied to
    their sales oldest-first, so older debt is cleared before newer. Status is
    then Paid (outstanding 0), Overdue (owing and past due) or Open.
    """
    now = _utcnow()

    invoiced = (
        db.query(Transaction, Customer)
        .join(Customer, Transaction.customer_id == Customer.id)
        .filter(
            Customer.owner_phone == owner_phone,
            Transaction.invoice_number.isnot(None),
            Transaction.is_voided.isnot(True),
        )
        .all()
    )
    if not invoiced:
        return []

    # Per-customer FIFO payment pool, computed once per customer.
    outstanding_by_tx = {}
    seen_customers = {}
    for tx, customer in invoiced:
        cid = customer.id
        if cid not in seen_customers:
            seen_customers[cid] = True
            buys = (
                db.query(Transaction)
                .filter(
                    Transaction.customer_id == cid,
                    Transaction.type == "BUY",
                    Transaction.is_voided.isnot(True),
                )
                .order_by(Transaction.created_at.asc(), Transaction.id.asc())
                .all()
            )
            pay_total = (
                db.query(func.coalesce(func.sum(Transaction.amount), 0))
                .filter(
                    Transaction.customer_id == cid,
                    Transaction.type == "PAY",
                    Transaction.is_voided.isnot(True),
                )
                .scalar()
            ) or 0
            pool = int(pay_total)
            for b in buys:
                applied = min(pool, b.amount or 0)
                outstanding_by_tx[b.id] = (b.amount or 0) - applied
                pool -= applied

    rows = []
    for tx, customer in invoiced:
        outstanding = outstanding_by_tx.get(tx.id, tx.amount or 0)
        status = _invoice_status(outstanding, tx.due_date, now)
        if status_filter and status != status_filter:
            continue
        rows.append({
            "id": tx.id,
            "invoice_number": tx.invoice_number,
            "invoice_ref": format_invoice_number(tx.invoice_number),
            "customer_id": customer.id,
            "customer_name": customer.name,
            "total": tx.amount or 0,
            "outstanding": outstanding,
            "due_date": tx.due_date.isoformat() if tx.due_date else None,
            "issued_at": (tx.invoiced_at or tx.created_at).isoformat() if (tx.invoiced_at or tx.created_at) else None,
            "sent_at": tx.invoice_sent_at.isoformat() if tx.invoice_sent_at else None,
            "status": status,
        })

    rows.sort(key=lambda r: (r["invoice_number"] or 0), reverse=True)
    return rows
