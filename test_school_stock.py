"""
A school's fee items are its stock — one list, never two entries.

Tuition and the PTA levy are service items in stock; textbooks and uniforms
are goods with a quantity. Charging a pupil from School fees takes books out of
stock (and a void puts them back); selling to a pupil at Select product goes on
their school bill for the term. A pupil can buy 3 of the 10 books on the list.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-school-stock-00000000")

import pytest

import school_service as school
from database import Base, SessionLocal, engine
from inventory_suppliers import restore_inventory_for_voided_sale
from models import Customer, FeeInvoice, FeeItem, InventoryItem, SchoolClass, Transaction, User
from web_pos import save_pos_sale

Base.metadata.create_all(engine)
_seq = iter(range(100, 900))


@pytest.fixture
def setup():
    phone = f"23480955771{next(_seq)}"
    db = SessionLocal()
    try:
        owner = User(phone=phone, name="Bright Star School", business_type="private_school")
        db.add(owner)
        db.commit()
        session, terms = school.start_session(db, phone, "2026/2027")
        jss1 = SchoolClass(owner_phone=phone, name="JSS 1", level_order=1)
        db.add(jss1)
        # The English textbook is already in stock (added through Add stock)
        db.add(InventoryItem(owner_phone=phone, name="english textbook", quantity=40,
                             selling_price=4000, is_available=True))
        db.flush()
        items = {}
        for name, kind, amount, optional in [
            ("Tuition", "FEE", 45000, False), ("PTA levy", "LEVY", 3000, False),
            ("English textbook", "BOOK", 4000, True), ("Maths textbook", "BOOK", 3500, True),
            ("Basic Science textbook", "BOOK", 3000, True),
        ]:
            fi = FeeItem(owner_phone=phone, name=name, kind=kind, default_amount=amount, is_optional=optional)
            db.add(fi)
            db.flush()
            items[name] = fi.id
        db.commit()
        school.link_all_fee_items(db, phone)          # what opening School fees does
        school.set_fee_schedule(db, phone, terms[0].id, jss1.id, {
            items["Tuition"]: 45000, items["PTA levy"]: 3000, items["English textbook"]: 4000,
            items["Maths textbook"]: 3500, items["Basic Science textbook"]: 3000})
        pupil, _ = school.register_pupil(db, phone, "Ada Obi", class_id=jss1.id,
                                         parent_name="Mrs Obi", parent_phone="08031230000")
        db.commit()
        return {"owner": phone, "term": terms[0].id, "class": jss1.id, "items": items, "pupil": pupil.id}
    finally:
        db.close()


def _inv(db, owner, name):
    return db.query(InventoryItem).filter_by(owner_phone=owner, name=name).one()


def test_every_fee_item_is_a_stock_item(setup):
    db = SessionLocal()
    try:
        o = setup["owner"]
        tuition, pta = _inv(db, o, "tuition"), _inv(db, o, "pta levy")
        # Services: tagged "service" — the same rule the whole app uses
        assert tuition.category == "service" and not school._is_goods(tuition)
        assert pta.category == "service" and not school._is_goods(pta)
        maths = _inv(db, o, "maths textbook")
        assert maths.quantity == 0 and maths.category != "service"              # goods
        english = db.query(InventoryItem).filter_by(owner_phone=o, name="english textbook").all()
        assert len(english) == 1 and english[0].quantity == 40                   # linked, not duplicated
    finally:
        db.close()


def test_a_pupil_buys_some_books_and_they_leave_stock(setup):
    db = SessionLocal()
    try:
        o, items = setup["owner"], setup["items"]
        listed = school.books_for_pupil(db, o, setup["pupil"], setup["term"])
        assert {b["name"] for b in listed if b["for_class"]} == {
            "English textbook", "Maths textbook", "Basic Science textbook"}       # all ticked
        # Ada takes English only (2 copies) — Maths and Basic Science unticked
        inv = school.charge_items(db, o, setup["pupil"], setup["term"],
                                  [{"fee_item_id": items["English textbook"], "quantity": 2}])
        assert inv.total == 8000
        assert _inv(db, o, "english textbook").quantity == 38
        assert _inv(db, o, "maths textbook").quantity == 0                       # not touched

        # Voiding the charge puts the books back
        tx = db.get(Transaction, inv.transaction_id)
        tx.is_voided = True
        restore_inventory_for_voided_sale(db, o, tx.id)
        db.commit()
        assert _inv(db, o, "english textbook").quantity == 40
    finally:
        db.close()


def test_opening_the_term_charges_services_without_touching_stock(setup):
    db = SessionLocal()
    try:
        o = setup["owner"]
        res = school.open_term(db, o, setup["term"])
        assert res["charged"] == 1 and res["total"] == 48000                    # tuition + PTA; books optional
        assert _inv(db, o, "english textbook").quantity == 40
    finally:
        db.close()


def test_selling_a_book_at_select_product_is_on_the_school_bill(setup):
    db = SessionLocal()
    try:
        o = setup["owner"]
        eng = _inv(db, o, "english textbook")
        r = save_pos_sale(db, o, None, setup["pupil"],
                          [{"inventory_item_id": eng.id, "name": "english textbook", "qty": 1, "unit_price": 4000}], 0)
        tx = db.get(Transaction, r["receipt_id"])
        assert school.record_till_sale_for_pupil(db, o, tx) is not None
        db.commit()
        assert _inv(db, o, "english textbook").quantity == 39                   # stock once
        bills = db.query(FeeInvoice).filter_by(owner_phone=o, transaction_id=tx.id).all()
        assert len(bills) == 1 and bills[0].term_id == setup["term"]           # school fees once
        summary = school.term_summary(db, o, setup["term"])
        assert summary["expected"] == 4000 and summary["outstanding"] == 4000
        assert school.record_till_sale_for_pupil(db, o, tx) is None             # never twice
    finally:
        db.close()


def test_a_book_paid_for_at_the_till_counts_as_collected(setup):
    db = SessionLocal()
    try:
        o = setup["owner"]
        eng = _inv(db, o, "english textbook")
        r = save_pos_sale(db, o, None, setup["pupil"],
                          [{"inventory_item_id": eng.id, "name": "english textbook", "qty": 1, "unit_price": 4000}], 4000)
        school.record_till_sale_for_pupil(db, o, db.get(Transaction, r["receipt_id"]))
        db.commit()
        summary = school.term_summary(db, o, setup["term"])
        assert summary["expected"] == 4000 and summary["collected"] == 4000 and summary["outstanding"] == 0
    finally:
        db.close()


def test_a_parent_who_is_not_a_pupil_is_not_put_on_the_school_bill(setup):
    db = SessionLocal()
    try:
        o = setup["owner"]
        parent = Customer(owner_phone=o, name="Mr Bello", balance=0)
        db.add(parent); db.commit()
        eng = _inv(db, o, "english textbook")
        r = save_pos_sale(db, o, None, parent.id,
                          [{"inventory_item_id": eng.id, "name": "english textbook", "qty": 1, "unit_price": 4000}], 0)
        assert school.record_till_sale_for_pupil(db, o, db.get(Transaction, r["receipt_id"])) is None
    finally:
        db.close()


def test_renaming_or_repricing_a_fee_item_keeps_stock_in_step(setup):
    db = SessionLocal()
    try:
        o, items = setup["owner"], setup["items"]
        school.update_fee_item(db, o, items["Maths textbook"], name="Mathematics textbook", default_amount=3800)
        inv = _inv(db, o, "mathematics textbook")
        assert inv.selling_price == 3800
    finally:
        db.close()


def test_the_school_price_list_adds_books_and_uniforms_as_goods():
    from business_templates import GOODS_IN_PRICE_LISTS, SERVICE_PRICE_CATALOG
    names = {n for n, _v, _p in SERVICE_PRICE_CATALOG["school"]}
    assert {"books / supplies", "uniform"} <= names & GOODS_IN_PRICE_LISTS
    assert "tuition" not in GOODS_IN_PRICE_LISTS
