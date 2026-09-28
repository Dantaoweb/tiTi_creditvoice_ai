"""
Repayments for a financed asset.

A financed motorcycle is, to the business, exactly what a supplier purchase is:
something received now and owed for. So the repayment plan rides the supplier
rails — one SupplierPurchase per installment — and gets the Suppliers page, the
supplier-due reminders and the payment receipts for free.

Two things keep that reuse honest:
  • the rows are tagged (finance_application_id, supplier.finance_partner_id) so
    financing never contaminates the trade-credit picture, and
  • every repayment carries how much it can be trusted: CLAIMED when the owner
    says so, PARTNER_CONFIRMED when the partner or admin confirms, and
    WALLET_CONFIRMED when the money was seen landing. Only confirmed repayments
    count as evidence in the scorecard.
"""
from datetime import timedelta

from sqlalchemy import func

from models import (
    FinanceApplication, Supplier, SupplierPayment, SupplierPurchase, utcnow,
)

CLAIMED = "CLAIMED"
PARTNER_CONFIRMED = "PARTNER_CONFIRMED"
WALLET_CONFIRMED = "WALLET_CONFIRMED"
CONFIRMED = (PARTNER_CONFIRMED, WALLET_CONFIRMED)

FREQUENCY_DAYS = {"WEEKLY": 7, "MONTHLY": 30}


def partner_supplier(db, owner_phone, partner):
    """The partner as a supplier of this business, created once and tagged so
    reports can separate financing from ordinary suppliers."""
    row = (
        db.query(Supplier)
        .filter(Supplier.owner_phone == owner_phone,
                Supplier.finance_partner_id == partner.id)
        .first()
    )
    if row:
        return row
    row = Supplier(
        name=partner.name, owner_phone=owner_phone,
        phone=partner.contact_phone, finance_partner_id=partner.id,
    )
    db.add(row)
    db.flush()
    return row


def generate_schedule(db, application, partner, count, amount_each, every="WEEKLY",
                      first_due=None, recorded_by_id=None):
    """Create the repayment plan: one supplier purchase per installment.

    Returns the created rows. Refuses to run twice for the same application —
    a second plan would double the business's recorded obligations.
    """
    if count < 1 or count > 120:
        raise ValueError("Number of installments must be between 1 and 120.")
    if amount_each < 1:
        raise ValueError("Each installment must be more than zero.")
    every = (every or "WEEKLY").upper()
    if every not in FREQUENCY_DAYS:
        raise ValueError(f"Repayment frequency must be one of {sorted(FREQUENCY_DAYS)}.")
    if existing_schedule(db, application.id):
        raise ValueError("This application already has a repayment plan.")

    supplier = partner_supplier(db, application.owner_phone, partner)
    step = FREQUENCY_DAYS[every]
    start = first_due or (utcnow() + timedelta(days=step))
    label = (application.asset_requested or "Financed asset").title()

    rows = []
    for i in range(1, count + 1):
        row = SupplierPurchase(
            supplier_id=supplier.id,
            owner_phone=application.owner_phone,
            product=f"{label} · installment {i} of {count}",
            quantity=1,
            unit_price=amount_each,
            total=amount_each,
            paid_amount=0,
            due_date=start + timedelta(days=step * (i - 1)),
            recorded_by_id=recorded_by_id,
            finance_application_id=application.id,
            installment_no=i,
            installments_total=count,
        )
        db.add(row)
        rows.append(row)

    application.installment_count = count
    application.installment_amount = amount_each
    application.installment_every = every
    application.updated_at = utcnow()
    db.flush()
    return rows


def existing_schedule(db, application_id):
    return (
        db.query(SupplierPurchase)
        .filter(SupplierPurchase.finance_application_id == application_id)
        .order_by(SupplierPurchase.installment_no.asc())
        .all()
    )


def record_repayment(db, application, installment_no, amount, verification=CLAIMED,
                     recorded_by_id=None, confirmed_by=None, note=None):
    """Record money paid against one installment.

    Over-payment of an installment is clamped: the extra belongs to the next
    one, and silently marking an installment as more than settled would distort
    the repayment record.
    """
    row = (
        db.query(SupplierPurchase)
        .filter(SupplierPurchase.finance_application_id == application.id,
                SupplierPurchase.installment_no == installment_no)
        .first()
    )
    if not row:
        raise ValueError("That installment is not part of this plan.")
    outstanding = max(0, int(row.total or 0) - int(row.paid_amount or 0))
    if outstanding <= 0:
        raise ValueError("That installment is already fully paid.")
    amount = min(int(amount), outstanding)
    if amount < 1:
        raise ValueError("Enter an amount above zero.")

    now = utcnow()
    row.paid_amount = int(row.paid_amount or 0) + amount
    payment = SupplierPayment(
        supplier_id=row.supplier_id,
        owner_phone=application.owner_phone,
        amount=amount,
        product=note or row.product,
        recorded_by_id=recorded_by_id,
        purchase_id=row.id,
        verification=verification,
        confirmed_at=now if verification in CONFIRMED else None,
        confirmed_by=confirmed_by if verification in CONFIRMED else None,
        created_at=now,
    )
    db.add(payment)
    db.flush()
    return row, payment


def confirm_repayments(db, application, installment_no=None,
                       verification=PARTNER_CONFIRMED, confirmed_by=None):
    """Upgrade owner-claimed repayments to confirmed evidence."""
    q = (
        db.query(SupplierPayment)
        .join(SupplierPurchase, SupplierPayment.purchase_id == SupplierPurchase.id)
        .filter(SupplierPurchase.finance_application_id == application.id,
                SupplierPayment.verification == CLAIMED)
    )
    if installment_no is not None:
        q = q.filter(SupplierPurchase.installment_no == installment_no)
    now = utcnow()
    rows = q.all()
    for payment in rows:
        payment.verification = verification
        payment.confirmed_at = now
        payment.confirmed_by = confirmed_by
    return len(rows)


def _payments_by_purchase(db, purchase_ids):
    if not purchase_ids:
        return {}
    out = {}
    for payment in (
        db.query(SupplierPayment)
        .filter(SupplierPayment.purchase_id.in_(purchase_ids))
        .all()
    ):
        out.setdefault(payment.purchase_id, []).append(payment)
    return out


def schedule_summary(db, application_id):
    """The plan and how it is going — per installment and in total."""
    rows = existing_schedule(db, application_id)
    if not rows:
        return None
    payments = _payments_by_purchase(db, [r.id for r in rows])
    now = utcnow()

    installments, paid_total, confirmed_total, on_time, settled, late_open = [], 0, 0, 0, 0, 0
    for row in rows:
        row_payments = payments.get(row.id, [])
        paid = int(row.paid_amount or 0)
        confirmed = sum(int(p.amount or 0) for p in row_payments if p.verification in CONFIRMED)
        is_settled = paid >= int(row.total or 0)
        # "On time" means settled on or before the due date, judged by the last
        # payment that closed it.
        closed_at = max((p.created_at for p in row_payments), default=None) if is_settled else None
        was_on_time = bool(is_settled and row.due_date and closed_at and closed_at <= row.due_date)
        overdue = bool(not is_settled and row.due_date and row.due_date < now)
        paid_total += paid
        confirmed_total += confirmed
        settled += 1 if is_settled else 0
        on_time += 1 if was_on_time else 0
        late_open += 1 if overdue else 0
        installments.append({
            "installment_no": row.installment_no,
            "purchase_id": row.id,
            "amount": int(row.total or 0),
            "paid": paid,
            "confirmed": confirmed,
            "outstanding": max(0, int(row.total or 0) - paid),
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "settled": is_settled,
            "on_time": was_on_time,
            "overdue": overdue,
            "verification": (
                WALLET_CONFIRMED if any(p.verification == WALLET_CONFIRMED for p in row_payments)
                else PARTNER_CONFIRMED if any(p.verification == PARTNER_CONFIRMED for p in row_payments)
                else CLAIMED if row_payments else None
            ),
        })

    total = sum(int(r.total or 0) for r in rows)
    return {
        "installments": installments,
        "count": len(rows),
        "total": total,
        "paid": paid_total,
        "confirmed_paid": confirmed_total,
        "outstanding": max(0, total - paid_total),
        "settled_count": settled,
        "on_time_count": on_time,
        "overdue_count": late_open,
        "on_time_pct": round(100.0 * on_time / settled, 1) if settled else 0.0,
        "complete": settled == len(rows),
    }


def repayment_metrics(db, owner_phone):
    """This business's financing repayment record, across every financed asset.

    Counts only CONFIRMED repayments as settled — an owner marking themselves
    paid must not be able to build a repayment record nobody verified.
    """
    apps = [
        a.id for a in db.query(FinanceApplication.id)
        .filter(FinanceApplication.owner_phone == owner_phone).all()
    ]
    rows = (
        db.query(SupplierPurchase)
        .filter(SupplierPurchase.finance_application_id.isnot(None),
                SupplierPurchase.owner_phone == owner_phone)
        .all()
    ) if apps else []
    if not rows:
        return {
            "has_financing": False, "installments": 0, "settled": 0, "on_time": 0,
            "on_time_pct": 0.0, "overdue": 0, "financed_total": 0,
            "repaid_confirmed": 0, "outstanding": 0,
        }

    payments = _payments_by_purchase(db, [r.id for r in rows])
    now = utcnow()
    settled = on_time = overdue = 0
    financed = repaid = 0
    for row in rows:
        amount = int(row.total or 0)
        financed += amount
        row_payments = [p for p in payments.get(row.id, []) if p.verification in CONFIRMED]
        confirmed = sum(int(p.amount or 0) for p in row_payments)
        repaid += confirmed
        if confirmed >= amount and amount > 0:
            settled += 1
            closed_at = max((p.created_at for p in row_payments), default=None)
            if row.due_date and closed_at and closed_at <= row.due_date:
                on_time += 1
        elif row.due_date and row.due_date < now:
            overdue += 1

    return {
        "has_financing": True,
        "installments": len(rows),
        "settled": settled,
        "on_time": on_time,
        "on_time_pct": round(100.0 * on_time / settled, 1) if settled else 0.0,
        "overdue": overdue,
        "financed_total": financed,
        "repaid_confirmed": repaid,
        "outstanding": max(0, financed - repaid),
    }
