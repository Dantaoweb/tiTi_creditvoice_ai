"""
How a school runs: register a pupil, set what each class owes, open the term,
collect fees, hand out textbooks.

The one decision everything else follows from: a pupil is a Customer and a
charge is an ordinary credit transaction. That is not a shortcut — it means a
pupil's balance, their receipts, the debtors list, fee reminders and the
business scorecard all work from the day this ships, because they are the same
machinery every other business already uses. A separate Student model would
have meant rebuilding every one of them.

What is genuinely new is the part a shop does not have: fees are owed per term,
and the school knows what they will be before anyone pays. Writing that down is
what turns "unpaid" from "whatever somebody remembered to type" into a figure
the bursar can chase.
"""
import logging
from datetime import datetime

from models import (
    AcademicSession, Customer, FeeInvoice, FeeItem, FeeSchedule, SchoolClass,
    SchoolTerm, StudentEnrolment, Transaction, TransactionItem, utcnow,
)

_log = logging.getLogger(__name__)

TERM_NAMES = ("First Term", "Second Term", "Third Term")
FEE_KINDS = ("FEE", "LEVY", "BOOK", "UNIFORM", "OTHER")


# ── Session and term ─────────────────────────────────────────────────────────

def start_session(db, owner_phone, name, term_names=TERM_NAMES, make_current=True):
    """Open a school year and its terms. The first term becomes the current one."""
    if make_current:
        db.query(AcademicSession).filter(
            AcademicSession.owner_phone == owner_phone).update({"is_current": False})
        db.query(SchoolTerm).filter(
            SchoolTerm.owner_phone == owner_phone).update({"is_current": False})

    session = AcademicSession(owner_phone=owner_phone, name=name.strip(),
                              is_current=bool(make_current))
    db.add(session)
    db.flush()
    terms = []
    for position, term_name in enumerate(term_names, start=1):
        term = SchoolTerm(owner_phone=owner_phone, session_id=session.id,
                          name=term_name, position=position,
                          is_current=bool(make_current and position == 1))
        db.add(term)
        terms.append(term)
    db.commit()
    return session, terms


def current_session(db, owner_phone):
    return (db.query(AcademicSession)
            .filter(AcademicSession.owner_phone == owner_phone,
                    AcademicSession.is_current == True)        # noqa: E712
            .first())


def current_term(db, owner_phone):
    return (db.query(SchoolTerm)
            .filter(SchoolTerm.owner_phone == owner_phone,
                    SchoolTerm.is_current == True)             # noqa: E712
            .first())


def set_current_term(db, owner_phone, term_id):
    term = db.query(SchoolTerm).filter(SchoolTerm.owner_phone == owner_phone,
                                       SchoolTerm.id == term_id).first()
    if not term:
        return None
    db.query(SchoolTerm).filter(SchoolTerm.owner_phone == owner_phone).update(
        {"is_current": False})
    term.is_current = True
    db.query(AcademicSession).filter(
        AcademicSession.owner_phone == owner_phone).update({"is_current": False})
    session = db.query(AcademicSession).filter(
        AcademicSession.id == term.session_id).first()
    if session:
        session.is_current = True
    db.commit()
    return term


# ── Pupils ───────────────────────────────────────────────────────────────────

def next_admission_no(db, owner_phone, session=None):
    """A readable admission number — the year and a running count."""
    session = session or current_session(db, owner_phone)
    year = (session.name or "").split("/")[0].strip() if session else ""
    year = year or str(utcnow().year)
    count = db.query(StudentEnrolment).filter(
        StudentEnrolment.owner_phone == owner_phone).count()
    return f"{year}/{count + 1:04d}"


def register_pupil(db, owner_phone, name, class_id=None, parent_name=None,
                   parent_phone=None, admission_no=None, session_id=None,
                   branch_id=None):
    """Register a pupil: a Customer to carry the money, an enrolment to carry
    the class. Re-registering an existing pupil moves them rather than making a
    second record of the same child."""
    name = (name or "").strip()
    if not name:
        raise ValueError("A pupil needs a name.")

    session = (db.query(AcademicSession).filter(
        AcademicSession.id == session_id).first() if session_id
        else current_session(db, owner_phone))

    customer = (db.query(Customer)
                .filter(Customer.owner_phone == owner_phone,
                        Customer.name.ilike(name))
                .first())
    if customer is None:
        customer = Customer(owner_phone=owner_phone, name=name, balance=0,
                            customer_phone=(parent_phone or "").strip() or None,
                            branch_id=branch_id)
        db.add(customer)
        db.flush()
    elif parent_phone and not customer.customer_phone:
        customer.customer_phone = parent_phone.strip()

    enrolment = (db.query(StudentEnrolment)
                 .filter(StudentEnrolment.owner_phone == owner_phone,
                         StudentEnrolment.customer_id == customer.id,
                         StudentEnrolment.session_id == (session.id if session else None))
                 .first())
    if enrolment is None:
        enrolment = StudentEnrolment(
            owner_phone=owner_phone, customer_id=customer.id,
            session_id=session.id if session else None,
            admission_no=(admission_no or "").strip() or next_admission_no(db, owner_phone, session),
        )
        db.add(enrolment)
    if class_id:
        enrolment.class_id = class_id
    if parent_name:
        enrolment.parent_name = parent_name.strip()
    enrolment.status = "ACTIVE"
    db.commit()
    return customer, enrolment


def promote(db, owner_phone, customer_id, to_class_id, session_id):
    """Move a pupil into the next class for a new session, keeping the old
    record — a promotion is history, not an edit."""
    existing = (db.query(StudentEnrolment)
                .filter(StudentEnrolment.owner_phone == owner_phone,
                        StudentEnrolment.customer_id == customer_id,
                        StudentEnrolment.session_id == session_id)
                .first())
    if existing:
        existing.class_id = to_class_id
        existing.status = "ACTIVE"
        db.commit()
        return existing

    previous = (db.query(StudentEnrolment)
                .filter(StudentEnrolment.owner_phone == owner_phone,
                        StudentEnrolment.customer_id == customer_id)
                .order_by(StudentEnrolment.enrolled_at.desc()).first())
    enrolment = StudentEnrolment(
        owner_phone=owner_phone, customer_id=customer_id, class_id=to_class_id,
        session_id=session_id, status="ACTIVE",
        admission_no=previous.admission_no if previous else None,
        parent_name=previous.parent_name if previous else None,
    )
    db.add(enrolment)
    db.commit()
    return enrolment


def pupils_in_class(db, owner_phone, class_id, session_id):
    return (db.query(StudentEnrolment)
            .filter(StudentEnrolment.owner_phone == owner_phone,
                    StudentEnrolment.class_id == class_id,
                    StudentEnrolment.session_id == session_id,
                    StudentEnrolment.status == "ACTIVE")
            .all())


# ── What a class owes ────────────────────────────────────────────────────────

def set_fee_schedule(db, owner_phone, term_id, class_id, amounts):
    """What this class owes this term: {fee_item_id: amount}. An item left out
    is removed, so the schedule always reads as the whole bill."""
    existing = {s.fee_item_id: s for s in db.query(FeeSchedule).filter(
        FeeSchedule.owner_phone == owner_phone,
        FeeSchedule.term_id == term_id,
        FeeSchedule.class_id == class_id).all()}

    for item_id, amount in (amounts or {}).items():
        amount = int(amount or 0)
        row = existing.pop(item_id, None)
        if row is None:
            db.add(FeeSchedule(owner_phone=owner_phone, term_id=term_id,
                               class_id=class_id, fee_item_id=item_id, amount=amount))
        else:
            row.amount = amount
    for leftover in existing.values():
        db.delete(leftover)
    db.commit()
    return schedule_for(db, owner_phone, term_id, class_id)


def schedule_for(db, owner_phone, term_id, class_id):
    """The bill for a class this term, compulsory items first."""
    rows = (db.query(FeeSchedule, FeeItem)
            .join(FeeItem, FeeItem.id == FeeSchedule.fee_item_id)
            .filter(FeeSchedule.owner_phone == owner_phone,
                    FeeSchedule.term_id == term_id,
                    FeeSchedule.class_id == class_id)
            .all())
    out = [{"fee_item_id": s.fee_item_id, "name": i.name, "kind": i.kind,
            "amount": s.amount or 0, "is_optional": bool(i.is_optional)}
           for s, i in rows]
    out.sort(key=lambda r: (r["is_optional"], r["name"]))
    return out


# ── Opening a term ───────────────────────────────────────────────────────────

def _charge(db, owner_phone, customer, term, class_id, lines, kind, recorded_by_id=None):
    """Write one charge as an ordinary credit transaction, itemised.

    Going through Transaction is the point: the balance listeners, receipts,
    debtor reports and reminders all pick it up without knowing a thing about
    schools.
    """
    total = sum(int(line["amount"]) * int(line.get("quantity", 1) or 1) for line in lines)
    if total <= 0:
        return None

    label = f"{term.name} fees" if kind == "TERM" else lines[0]["name"]
    tx = Transaction(
        customer_id=customer.id,
        type="BUY",                       # a charge the pupil now owes
        amount=total,
        product=label,
        recorded_by_id=recorded_by_id,
        created_at=utcnow(),
    )
    db.add(tx)
    db.flush()

    for line in lines:
        quantity = int(line.get("quantity", 1) or 1)
        db.add(TransactionItem(
            transaction_id=tx.id, product=line["name"], quantity=quantity,
            unit_price=int(line["amount"]), total=int(line["amount"]) * quantity,
        ))

    invoice = FeeInvoice(owner_phone=owner_phone, customer_id=customer.id,
                         term_id=term.id, class_id=class_id,
                         transaction_id=tx.id, total=total, kind=kind)
    db.add(invoice)
    return invoice


def open_term(db, owner_phone, term_id, recorded_by_id=None):
    """Charge every active pupil what their class owes this term.

    Optional items (textbooks) are left out — a pupil owes a book when they
    take one, not because their class has one on the list. Running this twice
    charges nobody twice.
    """
    term = db.query(SchoolTerm).filter(SchoolTerm.owner_phone == owner_phone,
                                       SchoolTerm.id == term_id).first()
    if not term:
        raise ValueError("That term does not exist.")

    already = {
        inv.customer_id for inv in db.query(FeeInvoice).filter(
            FeeInvoice.owner_phone == owner_phone,
            FeeInvoice.term_id == term_id,
            FeeInvoice.kind == "TERM").all()
    }

    charged, skipped, total = 0, 0, 0
    classes = db.query(SchoolClass).filter(SchoolClass.owner_phone == owner_phone,
                                           SchoolClass.is_active == True).all()  # noqa: E712
    for school_class in classes:
        lines = [row for row in schedule_for(db, owner_phone, term_id, school_class.id)
                 if not row["is_optional"] and row["amount"] > 0]
        if not lines:
            continue
        for enrolment in pupils_in_class(db, owner_phone, school_class.id, term.session_id):
            if enrolment.customer_id in already:
                skipped += 1
                continue
            customer = db.query(Customer).filter(
                Customer.id == enrolment.customer_id).first()
            if not customer:
                continue
            invoice = _charge(db, owner_phone, customer, term, school_class.id,
                              lines, "TERM", recorded_by_id)
            if invoice:
                charged += 1
                total += invoice.total
    term.invoiced_at = utcnow()
    db.commit()
    return {"charged": charged, "already_charged": skipped, "total": total,
            "term": term.name}


def charge_items(db, owner_phone, customer_id, term_id, items, recorded_by_id=None):
    """Charge a pupil for something taken during the term — textbooks, a
    uniform, an exam fee they were not down for.

    `items` is [{fee_item_id, quantity}]; the price comes from the class
    schedule when it is set there, and from the item's own price otherwise.
    """
    term = db.query(SchoolTerm).filter(SchoolTerm.owner_phone == owner_phone,
                                       SchoolTerm.id == term_id).first()
    customer = db.query(Customer).filter(Customer.owner_phone == owner_phone,
                                         Customer.id == customer_id).first()
    if not term or not customer:
        raise ValueError("Unknown pupil or term.")

    enrolment = (db.query(StudentEnrolment)
                 .filter(StudentEnrolment.owner_phone == owner_phone,
                         StudentEnrolment.customer_id == customer_id,
                         StudentEnrolment.session_id == term.session_id)
                 .first())
    class_id = enrolment.class_id if enrolment else None
    priced = {row["fee_item_id"]: row["amount"]
              for row in (schedule_for(db, owner_phone, term_id, class_id) if class_id else [])}

    lines = []
    for entry in items or []:
        item = db.query(FeeItem).filter(FeeItem.owner_phone == owner_phone,
                                        FeeItem.id == entry.get("fee_item_id")).first()
        if not item:
            continue
        amount = priced.get(item.id) or item.default_amount or 0
        if amount <= 0:
            continue
        lines.append({"name": item.name, "amount": int(amount),
                      "quantity": int(entry.get("quantity", 1) or 1)})
    if not lines:
        return None

    invoice = _charge(db, owner_phone, customer, term, class_id, lines, "EXTRA",
                      recorded_by_id)
    db.commit()
    return invoice


# ── Collecting ───────────────────────────────────────────────────────────────

def term_summary(db, owner_phone, term_id):
    """Expected, collected and outstanding for a term — overall and per class.

    Collected is counted against the term the money was taken in, not against
    particular invoices: a parent paying ₦30,000 off a ₦45,000 bill is paying
    the term, and splitting that across line items would invent a precision
    nobody has.
    """
    from sqlalchemy import func

    term = db.query(SchoolTerm).filter(SchoolTerm.owner_phone == owner_phone,
                                       SchoolTerm.id == term_id).first()
    if not term:
        return None

    invoices = db.query(FeeInvoice).filter(FeeInvoice.owner_phone == owner_phone,
                                           FeeInvoice.term_id == term_id).all()
    expected = sum(inv.total or 0 for inv in invoices)

    customer_ids = {inv.customer_id for inv in invoices}
    collected = 0
    if customer_ids:
        start = term.starts_on or min((inv.created_at for inv in invoices
                                       if inv.created_at), default=None)
        q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.customer_id.in_(customer_ids),
            Transaction.type == "PAY",
            Transaction.is_voided != True,                    # noqa: E712
        )
        if start is not None:
            q = q.filter(Transaction.created_at >= start)
        if term.ends_on:
            q = q.filter(Transaction.created_at < term.ends_on)
        collected = int(q.scalar() or 0)

    by_class = {}
    classes = {c.id: c for c in db.query(SchoolClass).filter(
        SchoolClass.owner_phone == owner_phone).all()}
    for inv in invoices:
        row = by_class.setdefault(inv.class_id, {"expected": 0, "pupils": set()})
        row["expected"] += inv.total or 0
        row["pupils"].add(inv.customer_id)

    classes_out = []
    for class_id, row in by_class.items():
        school_class = classes.get(class_id)
        outstanding = 0
        for customer_id in row["pupils"]:
            balance = db.query(Customer.balance).filter(
                Customer.id == customer_id).scalar() or 0
            outstanding += max(int(balance), 0)
        classes_out.append({
            "class_id": class_id,
            "class_name": school_class.name if school_class else "—",
            "pupils": len(row["pupils"]),
            "expected": row["expected"],
            "outstanding": outstanding,
            "collected": max(row["expected"] - outstanding, 0),
        })
    classes_out.sort(key=lambda r: r["outstanding"], reverse=True)

    outstanding_total = sum(r["outstanding"] for r in classes_out)
    return {
        "term": term.name,
        "term_id": term.id,
        "invoiced_pupils": len(customer_ids),
        "expected": expected,
        "collected": collected,
        "outstanding": outstanding_total,
        "collection_rate": (round(100.0 * (expected - outstanding_total) / expected)
                            if expected else 0),
        "classes": classes_out,
    }


def defaulters(db, owner_phone, term_id, class_id=None, limit=200):
    """Who still owes, most first — the list a bursar actually works from."""
    invoices = db.query(FeeInvoice).filter(FeeInvoice.owner_phone == owner_phone,
                                           FeeInvoice.term_id == term_id)
    if class_id:
        invoices = invoices.filter(FeeInvoice.class_id == class_id)
    rows = invoices.all()
    if not rows:
        return []

    classes = {c.id: c.name for c in db.query(SchoolClass).filter(
        SchoolClass.owner_phone == owner_phone).all()}
    billed = {}
    for inv in rows:
        entry = billed.setdefault(inv.customer_id, {"billed": 0, "class_id": inv.class_id})
        entry["billed"] += inv.total or 0

    out = []
    for customer in db.query(Customer).filter(
            Customer.id.in_(list(billed.keys()))).all():
        balance = int(customer.balance or 0)
        if balance <= 0:
            continue
        entry = billed[customer.id]
        out.append({
            "customer_id": customer.id,
            "name": customer.name,
            "phone": customer.customer_phone,
            "class_name": classes.get(entry["class_id"], "—"),
            "billed": entry["billed"],
            "outstanding": balance,
        })
    out.sort(key=lambda r: r["outstanding"], reverse=True)
    return out[:limit]


def student_statement(db, owner_phone, customer_id):
    """Everything charged and paid for one pupil — what a parent asks for."""
    customer = db.query(Customer).filter(Customer.owner_phone == owner_phone,
                                         Customer.id == customer_id).first()
    if not customer:
        return None

    enrolment = (db.query(StudentEnrolment)
                 .filter(StudentEnrolment.owner_phone == owner_phone,
                         StudentEnrolment.customer_id == customer_id)
                 .order_by(StudentEnrolment.enrolled_at.desc()).first())
    school_class = (db.query(SchoolClass).filter(
        SchoolClass.id == enrolment.class_id).first() if enrolment and enrolment.class_id
        else None)

    entries = []
    transactions = (db.query(Transaction)
                    .filter(Transaction.customer_id == customer_id,
                            Transaction.is_voided != True)        # noqa: E712
                    .order_by(Transaction.created_at.desc()).limit(100).all())
    tx_ids = [t.id for t in transactions]
    items_by_tx = {}
    if tx_ids:
        for line in db.query(TransactionItem).filter(
                TransactionItem.transaction_id.in_(tx_ids)).all():
            items_by_tx.setdefault(line.transaction_id, []).append(line)

    for tx in transactions:
        entries.append({
            "id": tx.id,
            "date": tx.created_at.isoformat() if tx.created_at else None,
            "kind": "charge" if tx.type == "BUY" else ("payment" if tx.type == "PAY" else tx.type),
            "description": tx.product or "",
            "amount": int(tx.amount or 0),
            "items": [{"name": i.product, "quantity": i.quantity, "total": i.total}
                      for i in items_by_tx.get(tx.id, [])],
        })

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "parent_name": enrolment.parent_name if enrolment else None,
        "parent_phone": customer.customer_phone,
        "admission_no": enrolment.admission_no if enrolment else None,
        "class_name": school_class.name if school_class else None,
        "balance": int(customer.balance or 0),
        "entries": entries,
    }


def record_payment(db, owner_phone, customer_id, amount, term=None, note=None,
                   recorded_by_id=None):
    """A fee payment — an ordinary PAY transaction, so the receipt, the balance
    and the debtors list all follow."""
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("A payment needs an amount.")
    customer = db.query(Customer).filter(Customer.owner_phone == owner_phone,
                                         Customer.id == customer_id).first()
    if not customer:
        raise ValueError("Unknown pupil.")
    term = term or current_term(db, owner_phone)
    tx = Transaction(
        customer_id=customer.id, type="PAY", amount=amount,
        product=note or (f"{term.name} fees" if term else "School fees"),
        recorded_by_id=recorded_by_id, created_at=utcnow(),
    )
    db.add(tx)
    db.commit()
    return tx
