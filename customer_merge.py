"""
Same customer, two records — finding them, stopping new ones, merging them.

A customer saved as "Mr Adewale" and again as "mr adewale" (or "Mr  Adewale")
splits one person's debt across two records, and the app shows both as
"Mr Adewale". find_customer_named() matches names ignoring capitals and extra
spaces, so new sales reuse the record; merge_customers() joins two records
into one: every record pointing at the extra one moves to the one kept, the
balance adds up, and the extra record is deleted.
"""
from sqlalchemy import case, func

from models import Customer, Transaction


def tidy_name(name):
    """One space between words, none at the ends."""
    return " ".join((name or "").split())


def name_key(name):
    return tidy_name(name).lower()


def find_customer_named(db, owner_phone, name, exclude_id=None):
    """The business's customer with this name — capitals and extra spaces
    ignored. The oldest wins if there are already two. `exclude_id` skips one
    record (a rename checking for a clash with someone else)."""
    key = name_key(name)
    if not key or not owner_phone:
        return None
    base = db.query(Customer).filter(Customer.owner_phone == owner_phone)
    if exclude_id is not None:
        base = base.filter(Customer.id != exclude_id)
    exact = base.filter(func.lower(Customer.name) == key).order_by(Customer.id.asc()).first()
    if exact:
        return exact
    # Saved with extra spaces ("Mr  Adewale"): narrow by the longest word, then compare tidied
    word = max(key.split(), key=len)
    for c in base.filter(func.lower(Customer.name).contains(word, autoescape=True)) \
                 .order_by(Customer.id.asc()).limit(500):
        if name_key(c.name) == key:
            return c
    return None


def duplicate_groups(db, owner_phone):
    """Customers sharing a name (capitals and spaces ignored), oldest first."""
    rows = db.query(Customer).filter(Customer.owner_phone == owner_phone).order_by(Customer.id.asc()).all()
    groups = {}
    for c in rows:
        key = name_key(c.name)
        if key:
            groups.setdefault(key, []).append(c)
    return [g for g in groups.values() if len(g) > 1]


def _customer_columns():
    """Every column, in every table, that points at a customer."""
    from database import Base
    cols = []
    for table in Base.metadata.sorted_tables:
        if table.name == Customer.__tablename__:
            continue
        for col in table.columns:
            if any(fk.column.table.name == Customer.__tablename__ for fk in col.foreign_keys) \
                    or col.name == "customer_id":
                cols.append((table, col))
    return cols


def _true_balance(db, customer_id):
    total = db.query(func.coalesce(func.sum(case(
        (Transaction.type == "BUY", Transaction.amount),
        (Transaction.type == "PAY", -Transaction.amount),
        else_=0,
    )), 0)).filter(Transaction.customer_id == customer_id, Transaction.is_voided.isnot(True)).scalar()
    return int(total or 0)


def merge_customers(db, owner_phone, keep_id, other_id):
    """Join `other` into `keep`. Returns (kept customer, records moved).
    Raises ValueError when the two can't be merged."""
    if keep_id == other_id:
        raise ValueError("Pick two different customers.")
    keep = db.query(Customer).filter(Customer.id == keep_id, Customer.owner_phone == owner_phone).first()
    other = db.query(Customer).filter(Customer.id == other_id, Customer.owner_phone == owner_phone).first()
    if not keep or not other:
        raise ValueError("Customer not found.")

    moved = 0
    for table, col in _customer_columns():
        res = db.execute(table.update().where(col == other.id).values({col.name: keep.id}))
        moved += res.rowcount or 0

    # What the kept record lacks, it takes from the other
    for attr in ("customer_phone", "secondary_phone", "category", "profile_json", "branch_id", "created_by_id"):
        if not getattr(keep, attr) and getattr(other, attr):
            setattr(keep, attr, getattr(other, attr))
    if other.created_at and (not keep.created_at or other.created_at < keep.created_at):
        keep.created_at = other.created_at
    if other.last_transaction_at and (not keep.last_transaction_at
                                      or other.last_transaction_at > keep.last_transaction_at):
        keep.last_transaction_at = other.last_transaction_at

    db.delete(other)
    db.flush()
    # Moved in bulk (no per-row listeners), so the balance is summed afresh
    keep.balance = _true_balance(db, keep.id)
    db.commit()
    return keep, moved
