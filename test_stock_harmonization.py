"""
#5: stock deduction harmonizes across sale paths. A POS line typed by name (no
inventory_item_id) must deduct from the same stock item that quick sale / item
customization would, when the names match.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import User, InventoryItem
from web_pos import save_pos_sale
from inventory_suppliers import deduct_inventory_for_items

OWNER = "2348000000501"


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(User(id="u1", phone=OWNER, name="Shop", role="user"))
    db.commit()
    return db


def _stock(db, name, qty):
    it = InventoryItem(owner_phone=OWNER, name=name, quantity=qty, selling_price=500)
    db.add(it); db.commit()
    return it


def test_pos_line_typed_by_name_deducts_same_stock():
    db = _db()
    sugar = _stock(db, "sugar", 10)
    # POS cart line WITHOUT inventory_item_id (typed by name), quantity 3
    save_pos_sale(db, OWNER, "u1", None,
                  items=[{"name": "Sugar", "qty": 3, "unit_price": 500}],
                  payment_amount=1500)
    db.refresh(sugar)
    assert sugar.quantity == 7        # 10 - 3, deducted despite no link


def test_pos_and_quick_sale_hit_the_same_item():
    db = _db()
    rice = _stock(db, "rice", 20)
    # Quick-sale style deduction (name match)
    deduct_inventory_for_items(db, OWNER,
                               [{"product": "rice", "quantity": 5, "unit": None}],
                               "CUSTOMER_SALE", 1)
    db.commit()
    # POS by name
    save_pos_sale(db, OWNER, "u1", None,
                  items=[{"name": "rice", "qty": 4, "unit_price": 500}],
                  payment_amount=2000)
    db.refresh(rice)
    assert rice.quantity == 11        # 20 - 5 - 4, both paths hit the one item

    # Still exactly one "rice" item — no duplicate created
    assert db.query(InventoryItem).filter(InventoryItem.owner_phone == OWNER,
                                          InventoryItem.name == "rice").count() == 1


def test_linked_item_id_still_used_when_present():
    db = _db()
    milk = _stock(db, "milk", 8)
    save_pos_sale(db, OWNER, "u1", None,
                  items=[{"name": "milk", "inventory_item_id": milk.id, "qty": 2, "unit_price": 500}],
                  payment_amount=1000)
    db.refresh(milk)
    assert milk.quantity == 6
