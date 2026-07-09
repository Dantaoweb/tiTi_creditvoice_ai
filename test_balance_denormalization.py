"""
Denormalized Customer.balance tests
===================================
Customer.balance (BUY − PAY, voided excluded) is maintained automatically by
SQLAlchemy event listeners on Transaction (models.py) so no write path can
forget to update it. These tests exercise every mutation shape — insert, void,
amount edit, customer reassignment, delete — plus the read fast paths and the
scheduler's reconciliation safety net.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, Transaction, User
from reports import get_balance, get_unpaid_debtors


def make_test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def make_customer(db, name="ade", owner_phone="2348001111111"):
    customer = Customer(name=name, owner_phone=owner_phone, balance=0)
    db.add(customer)
    db.commit()
    return customer


def add_tx(db, customer_id, tx_type, amount, **kwargs):
    tx = Transaction(
        customer_id=customer_id,
        type=tx_type,
        amount=amount,
        message_id=f"test-{uuid.uuid4()}",
        **kwargs,
    )
    db.add(tx)
    db.commit()
    return tx


def stored_balance(db, customer_id):
    db.expire_all()
    return db.query(Customer.balance).filter(Customer.id == customer_id).scalar()


def true_balance(db, customer_id):
    """Authoritative recompute, bypassing the denormalized column."""
    total = 0
    for tx in db.query(Transaction).filter(Transaction.customer_id == customer_id):
        if tx.is_voided:
            continue
        if tx.type == "BUY":
            total += tx.amount
        elif tx.type == "PAY":
            total -= tx.amount
    return total


# ── Event listener coverage ───────────────────────────────────────────────────

def test_buy_and_pay_update_balance():
    db = make_test_db()
    c = make_customer(db)

    add_tx(db, c.id, "BUY", 5000)
    assert stored_balance(db, c.id) == 5000

    add_tx(db, c.id, "PAY", 2000)
    assert stored_balance(db, c.id) == 3000
    assert stored_balance(db, c.id) == true_balance(db, c.id)


def test_last_transaction_at_touched():
    db = make_test_db()
    c = make_customer(db)
    assert c.last_transaction_at is None
    add_tx(db, c.id, "BUY", 1000)
    db.expire_all()
    assert db.query(Customer).get(c.id).last_transaction_at is not None


def test_sale_and_direct_do_not_affect_balance():
    db = make_test_db()
    c = make_customer(db)
    add_tx(db, c.id, "SALE", 9000)          # fully-paid sale linked to customer
    add_tx(db, None, "DIRECT", 4000)        # personal savings / direct income
    assert stored_balance(db, c.id) == 0


def test_void_reverses_balance():
    db = make_test_db()
    c = make_customer(db)
    tx = add_tx(db, c.id, "BUY", 5000)
    add_tx(db, c.id, "PAY", 2000)
    assert stored_balance(db, c.id) == 3000

    tx.is_voided = True                      # how void_commands.py voids
    db.commit()
    assert stored_balance(db, c.id) == -2000
    assert stored_balance(db, c.id) == true_balance(db, c.id)


def test_amount_edit_applies_delta():
    db = make_test_db()
    c = make_customer(db)
    tx = add_tx(db, c.id, "PAY", 2000)
    assert stored_balance(db, c.id) == -2000

    tx.amount = 500
    db.commit()
    assert stored_balance(db, c.id) == -500


def test_customer_reassignment_moves_balance():
    db = make_test_db()
    a = make_customer(db, name="a")
    b = make_customer(db, name="b")
    tx = add_tx(db, a.id, "BUY", 700)
    assert stored_balance(db, a.id) == 700
    assert stored_balance(db, b.id) == 0

    tx.customer_id = b.id
    db.commit()
    assert stored_balance(db, a.id) == 0
    assert stored_balance(db, b.id) == 700


def test_delete_reverses_balance():
    db = make_test_db()
    c = make_customer(db)
    tx = add_tx(db, c.id, "BUY", 1200)
    db.delete(tx)
    db.commit()
    assert stored_balance(db, c.id) == 0


# ── Read paths ────────────────────────────────────────────────────────────────

def test_get_balance_reads_column_and_staff_filter_still_sums():
    db = make_test_db()
    c = make_customer(db)
    staff = User(id="staff-1", phone="2348002222222", name="Staff", role="user")
    db.add(staff)
    db.commit()

    add_tx(db, c.id, "BUY", 5000, recorded_by_id="staff-1")
    add_tx(db, c.id, "PAY", 1000)            # recorded by someone else/owner

    assert get_balance(db, c.id) == 4000                      # column fast path
    assert get_balance(db, c.id, "staff-1") == 5000           # filtered sum

    # NULL column (pre-backfill row) must fall back to the true sum
    db.query(Customer).filter(Customer.id == c.id).update(
        {"balance": None}, synchronize_session=False
    )
    db.commit()
    assert get_balance(db, c.id) == 4000


def test_get_unpaid_debtors_fast_path():
    db = make_test_db()
    owner = "2348001111111"
    debtor = make_customer(db, name="debtor", owner_phone=owner)
    settled = make_customer(db, name="settled", owner_phone=owner)

    add_tx(db, debtor.id, "BUY", 3000)
    add_tx(db, settled.id, "BUY", 2000)
    add_tx(db, settled.id, "PAY", 2000)

    debtors, total = get_unpaid_debtors(db, owner_phone=owner)
    assert [d["name"] for d in debtors] == ["debtor"]
    assert total == 3000


# ── Reconciliation safety net ─────────────────────────────────────────────────

def test_reconciler_repairs_drift_and_nulls():
    from proactive_scheduler import _reconcile_balances

    db = make_test_db()
    c1 = make_customer(db, name="drifted")
    c2 = make_customer(db, name="nulled")
    add_tx(db, c1.id, "BUY", 5000)
    add_tx(db, c2.id, "BUY", 800)

    # Corrupt one balance and NULL the other, then reconcile
    db.query(Customer).filter(Customer.id == c1.id).update(
        {"balance": 123}, synchronize_session=False
    )
    db.query(Customer).filter(Customer.id == c2.id).update(
        {"balance": None}, synchronize_session=False
    )
    db.commit()

    _reconcile_balances(db)
    assert stored_balance(db, c1.id) == 5000
    assert stored_balance(db, c2.id) == 800
