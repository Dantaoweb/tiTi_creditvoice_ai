"""
Voiding a sale returns the stock it deducted.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import InventoryItem, InventoryMovement
from inventory_suppliers import deduct_inventory_for_items, restore_inventory_for_voided_sale

OWNER = "2348007777777"


def make_db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e)()


def _rice(db):
    return db.query(InventoryItem).filter_by(owner_phone=OWNER, name="rice").one()


def test_void_returns_deducted_stock():
    db = make_db()
    db.add(InventoryItem(owner_phone=OWNER, name="rice", unit="bag", quantity=20,
                         selling_price=75000, cost_price=60000, is_available=True))
    db.commit()
    TX = 101

    # A sale deducts 5 bags (source POS, linked to the transaction).
    deduct_inventory_for_items(db, OWNER, [{"product": "rice", "quantity": 5, "unit": "bag", "unit_price": 75000}],
                               "POS", TX, None)
    db.commit()
    assert _rice(db).quantity == 15

    # Voiding returns them.
    restored = restore_inventory_for_voided_sale(db, OWNER, TX, None)
    db.commit()
    assert _rice(db).quantity == 20
    assert restored and restored[0]["name"] == "rice" and restored[0]["quantity"] == 5

    # A reversing IN movement is logged for the audit trail.
    rev = db.query(InventoryMovement).filter_by(
        owner_phone=OWNER, source_type="VOID_REVERSAL", source_id=TX).all()
    assert len(rev) == 1 and rev[0].movement_type == "IN"

    # Idempotent — re-running does not double-restore.
    assert restore_inventory_for_voided_sale(db, OWNER, TX, None) == []
    db.commit()
    assert _rice(db).quantity == 20


def test_void_without_deduction_is_noop():
    db = make_db()
    db.add(InventoryItem(owner_phone=OWNER, name="rice", unit="bag", quantity=20,
                         selling_price=75000, is_available=True))
    db.commit()
    # A payment (no stock movement) → nothing to return.
    assert restore_inventory_for_voided_sale(db, OWNER, 555, None) == []
    assert _rice(db).quantity == 20
