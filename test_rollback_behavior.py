"""
Rollback Behaviour Tests
========================
These tests prove what the trader sees on WhatsApp when a database error
occurs mid-save, and verify that no partial data is left behind.

Scenario: Provision store owner sells rice to Ade.
          The transaction is confirmed (YES) but the inventory
          deduction throws an unexpected error.

WITHOUT rollback (old code)
───────────────────────────
  WhatsApp conversation:
    Owner:   Ade bought rice 5000
    tiTi:    Confirm: Ade bought N5,000?  YES to save.
    Owner:   yes
    tiTi:    [crash — no reply sent, or a generic error]

  Database state:
    transactions      → 1 row saved  (BUY N5,000 for Ade)   ← orphaned
    inventory_items   → quantity unchanged                   ← wrong
    pending_actions   → row still there OR deleted mid-way  ← inconsistent

  Result: Ade's balance is wrong. Stock was not deducted.
          If the owner tries again → duplicate transaction.

WITH rollback (current code)
─────────────────────────────
  WhatsApp conversation:
    Owner:   yes
    tiTi:    Something went wrong saving this transaction. Please try again.

  Database state:
    transactions      → 0 rows  ← clean
    inventory_items   → quantity unchanged, correctly
    pending_actions   → 1 row still there  ← owner can retry

  Result: Owner tries again → saves correctly on retry.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (
    Customer,
    InventoryItem,
    PendingAction,
    Transaction,
    User,
)
from transaction_save import save_customer_pending


# ── Test database setup ───────────────────────────────────────────────────────

def make_test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def make_owner(db, phone="2348001111111"):
    user = User(
        phone=phone,
        name="Mama Store",
        role="user",
        business_category="retail_trading",
        business_type="provision_store",
        business_type_label="Provision Store",
        subscription_plan="GO",
        subscription_status="ACTIVE",
    )
    db.add(user)
    db.flush()
    return user


def make_customer(db, owner_phone, name="ade"):
    customer = Customer(name=name, owner_phone=owner_phone)
    db.add(customer)
    db.flush()
    return customer


def make_inventory(db, owner_phone, product="rice", quantity=50, cost=3000, sell=4000):
    item = InventoryItem(
        owner_phone=owner_phone,
        name=product,
        quantity=quantity,
        cost_price=cost,
        selling_price=sell,
        is_available=True,
    )
    db.add(item)
    db.flush()
    return item


def make_pending_buy(db, phone, customer_name, product, amount, unit_price=None, quantity=None):
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    pending = PendingAction(
        phone=phone,
        customer_name=customer_name,
        last_customer=customer_name,
        action="BUY",
        buy_amount=amount,
        paid_amount=0,
        product=product,
        quantity=quantity or 1,
        unit=None,
        unit_price=unit_price,
        items_json="[]",
        source_text=None,
    )
    db.add(pending)
    db.commit()
    return pending


# ── Scenario 1: Happy path ────────────────────────────────────────────────────

def test_happy_path_saves_transaction_and_deducts_stock():
    """
    WhatsApp flow:
        Owner:  Ade bought 2 bags rice at 4000 each
        tiTi:   Confirm: Ade bought 2 bag of rice at N4,000 each, total: N8,000?
                YES to save.
        Owner:  yes
        tiTi:   Ade charge saved. Amount: N8,000
                Projected balance: N8,000
                Stock updated: Rice: 48 left
    """
    db = make_test_db()
    messages_sent = []

    user = make_owner(db)
    customer = make_customer(db, user.phone)
    inventory = make_inventory(db, user.phone, product="rice", quantity=50)
    pending = make_pending_buy(
        db, user.phone, "ade", "rice", amount=8000, unit_price=4000, quantity=2
    )

    subscription = {"plan": "GO", "limits": {}}

    result = save_customer_pending(
        db=db,
        phone=user.phone,
        pending=pending,
        user=user,
        business_owner_phone=user.phone,
        visible_recorded_by_id=None,
        message_id="msg-001",
        pending_items=[],
        inventory_enabled=True,
        send_message=lambda p, m: messages_sent.append((p, m)),
    )

    # ── Transaction saved ────────────────────────────────────────────────────
    assert result["status"] == "saved", f"Expected 'saved', got {result}"
    txs = db.query(Transaction).filter(Transaction.customer_id == customer.id).all()
    assert len(txs) == 1
    assert txs[0].type == "BUY"
    assert txs[0].amount == 8000

    # ── Stock deducted ───────────────────────────────────────────────────────
    db.refresh(inventory)
    assert inventory.quantity == 48, f"Expected 48, got {inventory.quantity}"

    # ── Pending deleted ──────────────────────────────────────────────────────
    remaining = db.query(PendingAction).filter(PendingAction.phone == user.phone).count()
    assert remaining == 0

    # ── Message sent to owner ────────────────────────────────────────────────
    assert len(messages_sent) == 1
    assert "8,000" in messages_sent[0][1]


# ── Scenario 2: DB crash mid-save → rollback ─────────────────────────────────

def test_inventory_failure_rolls_back_transaction_and_preserves_pending():
    """
    WhatsApp flow:
        Owner:  yes
        tiTi:   Something went wrong saving this transaction. Please try again.

    DB state after:
        - NO transaction row saved (clean rollback)
        - Stock quantity unchanged (50, not 48)
        - PendingAction still exists (owner can retry)

    This is the key guarantee: the owner is told to retry, and the retry
    will work cleanly because nothing was half-saved.
    """
    db = make_test_db()
    messages_sent = []

    user = make_owner(db)
    customer = make_customer(db, user.phone)
    inventory = make_inventory(db, user.phone, product="rice", quantity=50)
    pending = make_pending_buy(
        db, user.phone, "ade", "rice", amount=8000, unit_price=4000, quantity=2
    )

    subscription = {"plan": "GO", "limits": {}}

    # Simulate a database crash during inventory deduction
    with patch(
        "transaction_save.apply_sale_inventory",
        side_effect=Exception("Simulated DB failure during inventory deduction"),
    ):
        result = save_customer_pending(
            db=db,
            phone=user.phone,
            pending=pending,
            user=user,
            business_owner_phone=user.phone,
            visible_recorded_by_id=None,
            message_id="msg-002",
            pending_items=[],
            inventory_enabled=True,
            send_message=lambda p, m: messages_sent.append((p, m)),
        )

    # ── Status signals the error ─────────────────────────────────────────────
    assert result["status"] == "save_error", f"Expected 'save_error', got {result}"

    # ── NO transaction was saved (full rollback) ─────────────────────────────
    txs = db.query(Transaction).filter(Transaction.customer_id == customer.id).all()
    assert len(txs) == 0, (
        f"Rollback failed — found {len(txs)} orphaned transaction(s) in DB.\n"
        "WITHOUT rollback this would show as N8,000 debt on Ade's account "
        "even though the sale never properly completed."
    )

    # ── Stock quantity is UNCHANGED ──────────────────────────────────────────
    db.refresh(inventory)
    assert inventory.quantity == 50, (
        f"Rollback failed — stock is now {inventory.quantity} instead of 50.\n"
        "WITHOUT rollback the owner's stock count would be wrong."
    )

    # ── PendingAction still exists so owner can retry ────────────────────────
    remaining = db.query(PendingAction).filter(PendingAction.phone == user.phone).count()
    assert remaining == 1, (
        f"Expected pending action to survive rollback (so owner can retry), "
        f"but found {remaining} rows."
    )

    # ── Owner sees a clear error message, not silence ────────────────────────
    assert len(messages_sent) == 1
    assert "wrong" in messages_sent[0][1].lower(), (
        f"Expected 'Something went wrong' message, got: {messages_sent[0][1]}"
    )
    print(f"\n  tiTi said: '{messages_sent[0][1]}'")


# ── Scenario 3: Retry after rollback succeeds cleanly ────────────────────────

def test_retry_after_rollback_succeeds():
    """
    After the owner gets 'Something went wrong. Please try again.'
    they just send 'yes' again. The pending is still there,
    and this time it saves cleanly.

    WhatsApp flow:
        Owner:  yes           ← first attempt (DB crash)
        tiTi:   Something went wrong. Please try again.
        Owner:  yes           ← retry
        tiTi:   Ade charge saved. Amount: N8,000
                Balance: N8,000
                Stock updated: Rice: 48 left
    """
    db = make_test_db()
    messages_sent = []
    user = make_owner(db)
    customer = make_customer(db, user.phone)
    inventory = make_inventory(db, user.phone, product="rice", quantity=50)
    pending = make_pending_buy(
        db, user.phone, "ade", "rice", amount=8000, unit_price=4000, quantity=2
    )
    subscription = {"plan": "GO", "limits": {}}

    def send(p, m):
        messages_sent.append((p, m))

    # ── First attempt crashes ────────────────────────────────────────────────
    with patch(
        "transaction_save.apply_sale_inventory",
        side_effect=Exception("Simulated crash"),
    ):
        result1 = save_customer_pending(
            db, user.phone, pending, user, user.phone,
            None, "msg-003", [], True, send,
        )

    assert result1["status"] == "save_error"
    assert db.query(Transaction).count() == 0   # nothing saved
    assert db.query(PendingAction).count() == 1  # pending survives

    # Reload pending (rollback resets the session state)
    pending = db.query(PendingAction).filter(PendingAction.phone == user.phone).first()

    # ── Retry without the crash ──────────────────────────────────────────────
    result2 = save_customer_pending(
        db, user.phone, pending, user, user.phone,
        None, "msg-003", [], True, send,
    )

    assert result2["status"] == "saved", f"Retry failed with: {result2}"

    # ── Everything saved correctly on retry ──────────────────────────────────
    assert db.query(Transaction).filter(Transaction.customer_id == customer.id).count() == 1
    db.refresh(inventory)
    assert inventory.quantity == 48
    assert db.query(PendingAction).count() == 0

    # ── Two messages total: error then success ───────────────────────────────
    assert len(messages_sent) == 2
    assert "wrong" in messages_sent[0][1].lower()  # error message
    assert "8,000" in messages_sent[1][1]           # success message
    print(f"\n  Attempt 1: '{messages_sent[0][1]}'")
    print(f"  Attempt 2: '{messages_sent[1][1][:60]}...'")
