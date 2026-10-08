"""
Formal invoice support (web).

An invoice is a request to pay, written before money or goods change hands. It
is its own record (models.Invoice) and is NOT a debt: it touches neither the
customer's balance nor stock until something actually happens —
  - delivered → the goods leave stock
  - paid      → it becomes an ordinary sale with a receipt, and whatever was
                not paid becomes the customer's debt.

Before this, an "invoice" was a number stamped on a credit sale that had
already been recorded. Those older invoices keep their numbers and stay listed
("from a sale"); no new ones are made that way.

Numbers are assigned by the system — never typed by a user — from one
per-business INV sequence shared by both kinds, so INV-0007 is never issued
twice. The value is stamped inside the caller's transaction.
"""
import math
from datetime import datetime, timezone

from sqlalchemy import func

from models import Customer, Invoice, InvoiceItem, Transaction


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_invoice_number(number):
    """Render a stored invoice number as a formal reference, e.g. 1 -> 'INV-0001'."""
    if not number:
        return None
    return f"INV-{int(number):04d}"


def next_invoice_number(db, owner_phone):
    """The next number in this business's INV sequence, which both kinds of
    invoice share: the older numbers on credit sales and the new Invoice rows."""
    from_sales = (
        db.query(func.max(Transaction.invoice_number))
        .join(Customer, Transaction.customer_id == Customer.id)
        .filter(Customer.owner_phone == owner_phone)
        .scalar()
    )
    from_invoices = (
        db.query(func.max(Invoice.number))
        .filter(Invoice.owner_phone == owner_phone)
        .scalar()
    )
    return max(int(from_sales or 0), int(from_invoices or 0)) + 1


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
    _addr = receipt.get("branch_address") or receipt.get("biz_address")
    if _addr:
        lines.append(_addr)
    if receipt.get("branch_name"):
        lines.append(f"{receipt['branch_name']} branch")
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
    # Debt carried in from earlier sales: an invoice showing only this sale's
    # amount understates what the customer actually owes the business.
    prev_bal = int(receipt.get("previous_balance") or 0)
    if prev_bal > 0:
        lines.append(f"Amount due (this invoice): N{due:,}")
        lines.append(f"Previous balance:          N{prev_bal:,}")
        lines.append(f"*Total due now:            N{int(receipt.get('total_owed_now') or (due + prev_bal)):,}*")
    else:
        lines.append(f"*Amount due: N{due:,}*")
    if receipt.get("due_date"):
        lines.append(f"Due by: {receipt['due_date'][:10]}")
    lines.append("--------------------")
    from business_templates import invoice_footer_for
    lines.append(invoice_footer_for(cfg))
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


# ── Invoices as their own record ────────────────────────────────────────────

class InvoiceError(ValueError):
    """A request the invoice's current state does not allow; the message is
    shown to the user as is."""


def invoice_status(inv, now=None):
    """Draft / Sent / Overdue while waiting for money; Part paid / Paid once it
    has become a sale; Cancelled. Delivery is tracked separately — goods can go
    out before or after the money comes in."""
    now = now or _utcnow()
    if inv.cancelled_at:
        return "cancelled"
    if inv.transaction_id:
        return "paid" if (inv.amount_paid or 0) >= (inv.total or 0) else "part_paid"
    if inv.due_date and inv.due_date < now:
        return "overdue"
    if inv.sent_at:
        return "sent"
    return "draft"


def apply_discount(lines_total, discount):
    """The invoice total after a discount off the whole invoice."""
    try:
        discount = int(discount or 0)
    except (TypeError, ValueError):
        raise InvoiceError("Invalid discount.")
    if discount < 0 or discount > lines_total:
        raise InvoiceError("The discount must be between zero and the invoice total.")
    return lines_total - discount, discount


def clean_invoice_items(items):
    """Validate and total the lines of an invoice. Same rules as a till sale:
    a name, a positive quantity, a price that is not negative."""
    lines = []
    for it in items or []:
        name = (it.get("name") or "").strip()
        try:
            qty = float(it.get("qty", 1))
            price = int(it.get("unit_price", 0))
        except (TypeError, ValueError):
            raise InvoiceError("Invalid item quantity or price.")
        if not name:
            raise InvoiceError("Every item needs a name.")
        if qty <= 0 or price < 0:
            raise InvoiceError("Item quantity must be positive and price cannot be negative.")
        lines.append({
            "inventory_item_id": it.get("inventory_item_id"),
            "name": name,
            "qty": qty,
            "unit": it.get("unit"),
            "sold_unit": it.get("sold_unit"),
            "fraction": it.get("fraction"),
            "unit_price": price,
            "total": int(round(qty * price)),
        })
    if not lines:
        raise InvoiceError("Add at least one item to the invoice.")
    return lines, sum(l["total"] for l in lines)


def _set_items(db, inv, lines):
    db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).delete()
    for l in lines:
        db.add(InvoiceItem(
            invoice_id=inv.id,
            inventory_item_id=l["inventory_item_id"],
            product=l["name"],
            quantity=l["qty"],
            unit=l["unit"],
            sold_unit=l["sold_unit"],
            fraction=l["fraction"],
            unit_price=l["unit_price"],
            total=l["total"],
        ))


def invoice_lines(db, inv):
    """The invoice's lines in the shape the till's sale and stock helpers take."""
    rows = (db.query(InvoiceItem)
            .filter(InvoiceItem.invoice_id == inv.id)
            .order_by(InvoiceItem.id.asc()).all())
    return [{
        "inventory_item_id": r.inventory_item_id,
        "name": r.product,
        "qty": r.quantity,
        "unit": r.unit,
        "sold_unit": r.sold_unit,
        "fraction": r.fraction,
        "unit_price": r.unit_price or 0,
        "total": r.total or 0,
    } for r in rows]


def create_invoice(db, owner_phone, user_id, customer_id, items, *, due_date=None,
                   note=None, branch_id=None, customer_name=None, customer_phone=None,
                   discount=0):
    """Write a new invoice. No debt, no stock movement — just the document,
    with the next number in the business's INV sequence."""
    from web_pos import resolve_sale_customer
    lines, lines_total = clean_invoice_items(items)
    total, discount = apply_discount(lines_total, discount)
    customer_id = resolve_sale_customer(db, owner_phone, customer_id, customer_name, customer_phone)
    if not customer_id:
        raise InvoiceError("Choose who the invoice is for.")
    inv = Invoice(
        owner_phone=owner_phone,
        branch_id=branch_id,
        customer_id=customer_id,
        number=next_invoice_number(db, owner_phone),
        total=total,
        discount=discount or None,
        due_date=due_date,
        note=(note or "").strip() or None,
        created_by_id=user_id,
    )
    db.add(inv)
    db.flush()
    _set_items(db, inv, lines)
    db.commit()
    return inv


def update_invoice(db, inv, items, *, due_date=None, note=None, discount=0):
    """Change the lines, due date or note — only while nothing has happened to
    it yet. Once goods are out or money is in, the record is what happened."""
    if inv.cancelled_at:
        raise InvoiceError("This invoice was cancelled.")
    if inv.transaction_id:
        raise InvoiceError("This invoice is already paid, so it can't be changed.")
    if inv.delivered_at:
        raise InvoiceError("The goods on this invoice are already delivered, so it can't be changed.")
    lines, lines_total = clean_invoice_items(items)
    total, discount = apply_discount(lines_total, discount)
    _set_items(db, inv, lines)
    inv.total = total
    inv.discount = discount or None
    inv.due_date = due_date
    inv.note = (note or "").strip() or None
    db.commit()
    return inv


def deliver_invoice(db, inv, user_id):
    """The goods have gone to the customer: take them out of stock, once."""
    from web_pos import deduct_stock_for_items
    if inv.cancelled_at:
        raise InvoiceError("This invoice was cancelled.")
    if inv.delivered_at:
        raise InvoiceError("Already marked as delivered.")
    deduct_stock_for_items(db, inv.owner_phone, invoice_lines(db, inv), user_id,
                           source_type="INVOICE", source_id=inv.id,
                           note=f"Delivered on {format_invoice_number(inv.number)}")
    inv.delivered_at = _utcnow()
    inv.delivered_by_id = user_id
    db.commit()
    return inv


def pay_invoice(db, inv, user_id, amount):
    """The customer has paid — all of it, part of it, or (to take it on credit)
    nothing yet. It becomes an ordinary sale with a receipt; whatever was not
    paid becomes the customer's debt, due on the invoice's due date.

    Stock is not touched here: the goods leave stock when they are delivered,
    which may already have happened or may come later.
    """
    from web_pos import save_pos_sale
    if inv.cancelled_at:
        raise InvoiceError("This invoice was cancelled.")
    if inv.transaction_id:
        raise InvoiceError("This invoice is already paid. Collect anything still owed from Debts.")
    try:
        amount = int(amount or 0)
    except (TypeError, ValueError):
        raise InvoiceError("Enter the amount paid.")
    if amount < 0:
        raise InvoiceError("Payment cannot be negative.")
    if amount > (inv.total or 0):
        raise InvoiceError("That is more than the invoice total.")

    lines = invoice_lines(db, inv)
    # Paid in full means paid in full: with a fractional quantity the sale's
    # exact total can sit a fraction above the rounded invoice total, and that
    # fraction must not turn into debt.
    pay = amount
    if amount >= (inv.total or 0):
        pay = math.ceil(sum(float(l["qty"]) * int(l["unit_price"]) for l in lines) - (inv.discount or 0))
    result = save_pos_sale(
        db, inv.owner_phone, user_id, inv.customer_id, lines, pay,
        branch_id=inv.branch_id, due_date=inv.due_date,
        label=f"Invoice {format_invoice_number(inv.number)}",
        deduct_stock=False, commit=False, discount=inv.discount or 0,
    )
    inv.transaction_id = result["receipt_id"]
    inv.amount_paid = min(amount, inv.total or 0)
    inv.paid_at = _utcnow()
    db.commit()
    return inv, result


def reopen_invoice_for_voided_sale(db, tx_id):
    """The sale an invoice became was voided — the payment was a mistake — so
    the invoice is waiting for payment again. Its stock is untouched: that
    moved on delivery, not with the sale. The caller commits."""
    inv = db.query(Invoice).filter(Invoice.transaction_id == tx_id).first()
    if inv:
        inv.transaction_id = None
        inv.amount_paid = 0
        inv.paid_at = None
    return inv

def cancel_invoice(db, inv):
    """Withdraw an invoice nothing has happened to. Once goods have gone out
    or money has come in, there is something real to account for."""
    if inv.cancelled_at:
        return inv
    if inv.transaction_id:
        raise InvoiceError("This invoice is already paid, so it can't be cancelled.")
    if inv.delivered_at:
        raise InvoiceError("The goods are already delivered. Record the payment instead "
                           "(enter 0 to put it all on the customer's debt).")
    inv.cancelled_at = _utcnow()
    db.commit()
    return inv


def _business_header(db, owner_phone, branch_id):
    """Who the invoice is from: the same name, phone and address a receipt shows."""
    from business_templates import (
        DEFAULT_RECEIPT_CONFIG, business_display_name, receipt_config_for_user,
    )
    from models import Branch, User
    owner = db.query(User).filter(User.phone == owner_phone).first()
    out = {
        "biz_name": business_display_name(owner) if owner else None,
        "biz_phone": owner_phone,
        "biz_address": getattr(owner, "address", None) if owner else None,
        "branch_name": None,
        "branch_address": None,
        "config": receipt_config_for_user(owner) if owner else DEFAULT_RECEIPT_CONFIG,
    }
    if branch_id:
        br = db.query(Branch).filter(Branch.id == branch_id).first()
        if br:
            out["branch_name"] = br.name
            out["branch_address"] = br.address
    return out


def invoice_document(db, inv):
    """Everything the invoice page and the WhatsApp text need."""
    from models import User
    from business_templates import invoice_footer_for
    customer = db.query(Customer).filter(Customer.id == inv.customer_id).first()
    creator = db.query(User).filter(User.id == inv.created_by_id).first() if inv.created_by_id else None
    status = invoice_status(inv)
    waiting = status in ("draft", "sent", "overdue")
    # What they already owe from before. It is not part of this invoice, but an
    # invoice that hides it understates what the customer has to settle.
    other_debt = max(0, int(customer.balance or 0)) if (customer and waiting) else 0
    doc = _business_header(db, inv.owner_phone, inv.branch_id)
    doc.update({
        "id": inv.id,
        "number": inv.number,
        "ref": format_invoice_number(inv.number),
        "status": status,
        "total": inv.total or 0,
        "discount": inv.discount or 0,
        "subtotal": (inv.total or 0) + (inv.discount or 0),
        "amount_paid": inv.amount_paid or 0,
        "moved_to_debt": max(0, (inv.total or 0) - (inv.amount_paid or 0)) if status == "part_paid" else 0,
        "other_debt": other_debt,
        "total_due_now": ((inv.total or 0) + other_debt) if waiting else 0,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "note": inv.note,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "sent_at": inv.sent_at.isoformat() if inv.sent_at else None,
        "delivered_at": inv.delivered_at.isoformat() if inv.delivered_at else None,
        "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
        "cancelled_at": inv.cancelled_at.isoformat() if inv.cancelled_at else None,
        "transaction_id": inv.transaction_id,
        "branch_id": inv.branch_id,
        "created_by": creator.name if creator else None,
        "customer": {
            "id": customer.id, "name": customer.name, "phone": customer.customer_phone,
        } if customer else None,
        "items": invoice_lines(db, inv),
    })
    doc["footer"] = invoice_footer_for(doc["config"])
    return doc


def format_invoice_doc_text(doc):
    """The WhatsApp message for an invoice: what is being asked for, and by when."""
    lines = ["*INVOICE*"]
    if doc.get("biz_name"):
        lines.append(doc["biz_name"])
    addr = doc.get("branch_address") or doc.get("biz_address")
    if addr:
        lines.append(addr)
    if doc.get("branch_name"):
        lines.append(f"{doc['branch_name']} branch")
    lines.append(doc["ref"])
    lines.append("--------------------")
    cust = doc.get("customer") or {}
    if cust.get("name"):
        lines.append(f"Bill to: {cust['name'].title()}")
        lines.append("--------------------")
    for it in doc.get("items", []):
        qty = it["qty"]
        qty = int(qty) if float(qty).is_integer() else qty
        lines.append((it.get("name") or "").title())
        lines.append(f"  x{qty} @ N{int(it['unit_price']):,} = N{int(it['total']):,}")
    lines.append("--------------------")
    if doc.get("discount"):
        lines.append(f"Subtotal: N{doc['subtotal']:,}")
        lines.append(f"Discount: -N{doc['discount']:,}")
    if doc.get("other_debt"):
        lines.append(f"This invoice:      N{doc['total']:,}")
        lines.append(f"Previous balance:  N{doc['other_debt']:,}")
        lines.append(f"*Total due now:    N{doc['total_due_now']:,}*")
    else:
        lines.append(f"*Amount due: N{doc['total']:,}*")
    if doc.get("due_date"):
        lines.append(f"Due by: {doc['due_date'][:10]}")
    if doc.get("note"):
        lines.append(doc["note"])
    lines.append("--------------------")
    lines.append(doc["footer"])
    return "\n".join(lines)


def list_new_invoices(db, owner_phone, branch_id=None, created_by_id=None):
    """This business's invoices (the new kind) as list rows."""
    q = (db.query(Invoice, Customer)
         .join(Customer, Invoice.customer_id == Customer.id)
         .filter(Invoice.owner_phone == owner_phone))
    if branch_id is not None:
        q = q.filter(Invoice.branch_id == branch_id)
    if created_by_id is not None:
        q = q.filter(Invoice.created_by_id == created_by_id)
    now = _utcnow()
    rows = []
    for inv, customer in q.all():
        status = invoice_status(inv, now)
        rows.append({
            "kind": "invoice",
            "id": inv.id,
            "invoice_number": inv.number,
            "invoice_ref": format_invoice_number(inv.number),
            "customer_id": customer.id,
            "customer_name": customer.name,
            "total": inv.total or 0,
            "outstanding": (inv.total or 0) if status in ("draft", "sent", "overdue") else 0,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "issued_at": inv.created_at.isoformat() if inv.created_at else None,
            "sent_at": inv.sent_at.isoformat() if inv.sent_at else None,
            "delivered": bool(inv.delivered_at),
            "status": status,
        })
    return rows
