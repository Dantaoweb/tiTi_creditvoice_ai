"""
Personal savings plan: a frequency the saver commits to, an optional goal
amount, progress toward it, and when the next save is due (drives reminders).

Personal savings themselves are ordinary DIRECT transactions tagged
'personal_savings' — this module only adds the plan/goal/schedule on top.
"""
from datetime import datetime, timezone, timedelta

import sqlalchemy as sa

from models import SavingsPlan, Transaction
from reports import get_owner_transaction_query

_INTERVAL_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}
FREQUENCIES = tuple(_INTERVAL_DAYS.keys())


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _personal_rows(db, owner_phone):
    """The owner's personal-savings deposits (same filter the Thrift screen uses)."""
    base = get_owner_transaction_query(db, owner_phone)
    pf = sa.or_(
        sa.and_(Transaction.type == "DIRECT", Transaction.product.ilike("%personal_saving%")),
        sa.and_(Transaction.type == "DIRECT", Transaction.product.ilike("%personal saving%")),
        sa.and_(
            Transaction.customer_id == None,
            Transaction.type == "DIRECT",
            sa.or_(
                Transaction.product.ilike("%saving%"),
                Transaction.product.ilike("%thrift%"),
                Transaction.product.ilike("%ajo%"),
            ),
        ),
    )
    return base.filter(pf).all()


def get_plan(db, owner_phone):
    return db.query(SavingsPlan).filter(SavingsPlan.owner_phone == owner_phone).first()


def set_plan(db, owner_phone, frequency, goal_amount):
    plan = get_plan(db, owner_phone)
    if not plan:
        plan = SavingsPlan(owner_phone=owner_phone)
        db.add(plan)
    plan.frequency = frequency if frequency in _INTERVAL_DAYS else "weekly"
    plan.goal_amount = int(goal_amount) if goal_amount else None
    plan.updated_at = _utcnow()
    db.commit()
    return plan


def savings_summary(db, owner_phone):
    plan = get_plan(db, owner_phone)
    rows = _personal_rows(db, owner_phone)
    total = sum(int(t.amount or 0) for t in rows)
    last = max((t.created_at for t in rows if t.created_at), default=None)
    goal = plan.goal_amount if plan else None

    next_due = due = None
    overdue_days = 0
    if plan and plan.frequency in _INTERVAL_DAYS:
        interval = timedelta(days=_INTERVAL_DAYS[plan.frequency])
        anchor = last or plan.created_at or _utcnow()
        next_due = anchor + interval
        due = next_due <= _utcnow()
        if due:
            overdue_days = max(0, (_utcnow() - next_due).days)

    return {
        "has_plan": bool(plan),
        "frequency": plan.frequency if plan else None,
        "goal_amount": goal,
        "total_saved": total,
        "deposits": len(rows),
        "goal_pct": min(100, round(total / goal * 100)) if goal else None,
        "goal_reached": bool(goal and total >= goal),
        "last_saved_at": last.isoformat() if last else None,
        "next_due_at": next_due.isoformat() if next_due else None,
        "due": bool(due),
        "overdue_days": overdue_days,
    }
