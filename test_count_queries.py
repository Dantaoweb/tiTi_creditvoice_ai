"""
tiTi answers live-data "how many X do I have" questions with real counts
(branches, staff, suppliers, customers, products) — not the how-to FAQ.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import User, Branch, Customer, InventoryItem
from query_handler import handle_natural_language_query as ask

OWNER = "2348000000077"


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(User(id="o", phone=OWNER, name="Shop", role="owner"))
    db.add_all([Branch(owner_phone=OWNER, name="Ikeja", is_default=True),
                Branch(owner_phone=OWNER, name="Lekki")])
    db.add_all([User(id="s1", phone="234800000010", role="delegate", parent_id="o"),
                User(id="s2", phone="234800000011", role="delegate", parent_id="o"),
                User(id="s3", phone="234800000012", role="delegate_pending", parent_id="o")])
    db.add_all([Customer(name="Ada", owner_phone=OWNER), Customer(name="Bola", owner_phone=OWNER)])
    db.add(InventoryItem(owner_phone=OWNER, name="sugar", selling_price=100, quantity=5))
    db.commit()
    return db


def test_branch_count():
    a = ask(_db(), OWNER, "how many branches do i have")
    assert a and "2 branch" in a


def test_staff_count_and_synonyms():
    db = _db()
    for phrasing in ["how many staff do i have", "how many workers do i have", "how many employees do i have"]:
        a = ask(db, OWNER, phrasing)
        assert a and "2 staff member" in a, (phrasing, a)   # 2 active, 1 pending
        assert "pending" in a


def test_customer_and_product_counts():
    db = _db()
    assert "2 customer" in ask(db, OWNER, "how many customers do i have")
    assert "1 product" in ask(db, OWNER, "how many products do i have")


def test_supplier_count_zero():
    a = ask(_db(), OWNER, "how many suppliers do i have")
    assert a and "no suppliers" in a.lower()
