"""
Excusing a child from what their class is charged.

A fee schedule is a default, not a rule. Schools carry staff children,
scholarship pupils, siblings on a discount and families having a hard term —
and without a way to say so, the only way to be fair is to leave the child off
the register, which loses them from the school's own records.

So: set the class fee for everyone, then excuse whoever needs excusing, in
whatever shape the arrangement actually took — nothing at all, a percentage
off, an amount off, or an agreed figure.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-exemptions-000000000")

import pytest

import school_service as school
from database import Base, SessionLocal, engine
from models import Customer, FeeItem, SchoolClass, User

Base.metadata.create_all(engine)
_seq = iter(range(100, 900))


@pytest.fixture
def setup():
    phone = f"23480901301{next(_seq)}"
    db = SessionLocal()
    try:
        db.add(User(phone=phone, name="Bright Star School",
                    business_type="private_school"))
        db.commit()
        session, terms = school.start_session(db, phone, "2025/2026")
        jss2 = SchoolClass(owner_phone=phone, name="JSS 2")
        tuition = FeeItem(owner_phone=phone, name="Tuition", kind="FEE")
        pta = FeeItem(owner_phone=phone, name="PTA levy", kind="LEVY")
        book = FeeItem(owner_phone=phone, name="Maths textbook", kind="BOOK",
                       default_amount=3_500, is_optional=True)
        db.add_all([jss2, tuition, pta, book])
        db.commit()
        school.set_fee_schedule(db, phone, terms[0].id, jss2.id,
                                {tuition.id: 45_000, pta.id: 2_000, book.id: 3_500})
        return {"owner": phone, "session": session.id, "term": terms[0].id,
                "term2": terms[1].id, "jss2": jss2.id, "tuition": tuition.id,
                "pta": pta.id, "book": book.id}
    finally:
        db.close()


def _pupil(setup, name):
    db = SessionLocal()
    try:
        customer, _ = school.register_pupil(db, setup["owner"], name,
                                            class_id=setup["jss2"],
                                            details={"sex": "Female"})
        return customer.id
    finally:
        db.close()


def _excuse(setup, customer_id, **kw):
    db = SessionLocal()
    try:
        return school.set_exemption(db, setup["owner"], customer_id, **kw).id
    finally:
        db.close()


def _open_term(setup, term_key="term"):
    db = SessionLocal()
    try:
        return school.open_term(db, setup["owner"], setup[term_key])
    finally:
        db.close()


def _balance(customer_id):
    db = SessionLocal()
    try:
        return int(db.query(Customer.balance).filter(
            Customer.id == customer_id).scalar() or 0)
    finally:
        db.close()


def _preview(setup, customer_id, term_key="term"):
    db = SessionLocal()
    try:
        return school.fee_preview(db, setup["owner"], customer_id, setup[term_key])
    finally:
        db.close()


# ── The default still applies to everyone else ───────────────────────────────

def test_a_pupil_with_no_arrangement_pays_the_class_fee(setup):
    pupil = _pupil(setup, "Aisha Bello")
    _open_term(setup)
    assert _balance(pupil) == 47_000


def test_excusing_one_child_leaves_the_others_alone(setup):
    staff_child = _pupil(setup, "Staff Child")
    ordinary = _pupil(setup, "Ordinary Pupil")
    _excuse(setup, staff_child, kind="EXEMPT", reason="Staff child")

    result = _open_term(setup)
    assert _balance(staff_child) == 0
    assert _balance(ordinary) == 47_000
    assert result["charged"] == 1              # nothing to charge the staff child
    assert result["excused_pupils"] == 1
    assert result["excused_total"] == 47_000


# ── The shapes an arrangement actually takes ─────────────────────────────────

def test_a_full_scholarship_pays_nothing(setup):
    pupil = _pupil(setup, "Scholar")
    _excuse(setup, pupil, kind="EXEMPT", reason="Scholarship")
    _open_term(setup)
    assert _balance(pupil) == 0


def test_a_percentage_discount(setup):
    pupil = _pupil(setup, "Sibling")
    _excuse(setup, pupil, kind="PERCENT", value=50, reason="Second child")
    _open_term(setup)
    assert _balance(pupil) == 23_500           # half of 47,000


def test_an_amount_off(setup):
    pupil = _pupil(setup, "Hardship")
    _excuse(setup, pupil, kind="AMOUNT", value=10_000, reason="Hardship this term")
    _open_term(setup)
    assert _balance(pupil) == 37_000


def test_an_agreed_figure_replaces_the_class_fee(setup):
    pupil = _pupil(setup, "Agreed")
    _excuse(setup, pupil, kind="FIXED", value=20_000, fee_item_id=setup["tuition"],
            reason="Agreed with the head")
    _open_term(setup)
    assert _balance(pupil) == 20_000 + 2_000   # agreed tuition, PTA levy unchanged


def test_one_item_can_be_excused_on_its_own(setup):
    pupil = _pupil(setup, "No PTA")
    _excuse(setup, pupil, kind="EXEMPT", fee_item_id=setup["pta"], reason="PTA waived")
    _open_term(setup)
    assert _balance(pupil) == 45_000           # tuition still owed


# ── Scope ────────────────────────────────────────────────────────────────────

def test_an_exemption_for_one_term_does_not_follow_into_the_next(setup):
    pupil = _pupil(setup, "This Term Only")
    _excuse(setup, pupil, kind="EXEMPT", term_id=setup["term"], reason="Hard term")
    _open_term(setup)
    assert _balance(pupil) == 0

    db = SessionLocal()
    try:
        school.set_fee_schedule(db, setup["owner"], setup["term2"], setup["jss2"],
                                {setup["tuition"]: 45_000})
    finally:
        db.close()
    _open_term(setup, "term2")
    assert _balance(pupil) == 45_000           # back to the class fee


def test_an_ongoing_exemption_carries_across_terms(setup):
    pupil = _pupil(setup, "Staff Child")
    _excuse(setup, pupil, kind="EXEMPT", reason="Staff child")
    _open_term(setup)
    db = SessionLocal()
    try:
        school.set_fee_schedule(db, setup["owner"], setup["term2"], setup["jss2"],
                                {setup["tuition"]: 45_000})
    finally:
        db.close()
    _open_term(setup, "term2")
    assert _balance(pupil) == 0


def test_the_narrower_arrangement_wins(setup):
    """Half fees always, but no PTA levy this term — the specific one decides
    the levy, the general one decides the rest."""
    pupil = _pupil(setup, "Both Rules")
    _excuse(setup, pupil, kind="PERCENT", value=50, reason="Half fees")
    _excuse(setup, pupil, kind="EXEMPT", fee_item_id=setup["pta"],
            term_id=setup["term"], reason="PTA waived")
    _open_term(setup)
    assert _balance(pupil) == 22_500           # half of tuition, no levy


# ── Textbooks and other extras ───────────────────────────────────────────────

def test_a_scholarship_covers_the_textbook_too(setup):
    pupil = _pupil(setup, "Scholar")
    _excuse(setup, pupil, kind="EXEMPT", reason="Scholarship")
    _open_term(setup)
    db = SessionLocal()
    try:
        assert school.charge_items(db, setup["owner"], pupil, setup["term"],
                                   [{"fee_item_id": setup["book"]}]) is None
    finally:
        db.close()
    assert _balance(pupil) == 0


def test_a_tuition_only_arrangement_still_charges_for_the_book(setup):
    pupil = _pupil(setup, "Tuition Only")
    _excuse(setup, pupil, kind="EXEMPT", fee_item_id=setup["tuition"])
    _open_term(setup)
    db = SessionLocal()
    try:
        school.charge_items(db, setup["owner"], pupil, setup["term"],
                            [{"fee_item_id": setup["book"]}])
    finally:
        db.close()
    assert _balance(pupil) == 2_000 + 3_500    # PTA levy and the book


# ── Seeing and undoing it ────────────────────────────────────────────────────

def test_the_preview_shows_the_class_fee_beside_what_this_pupil_pays(setup):
    pupil = _pupil(setup, "Sibling")
    _excuse(setup, pupil, kind="PERCENT", value=50, reason="Second child")
    preview = _preview(setup, pupil)
    assert preview["class_total"] == 47_000
    assert preview["pupil_total"] == 23_500
    assert preview["excused"] == 23_500
    tuition_line = next(l for l in preview["lines"] if l["name"] == "Tuition")
    assert tuition_line["class_amount"] == 45_000
    assert tuition_line["amount"] == 22_500
    assert tuition_line["exempt_reason"] == "Second child"


def test_an_arrangement_can_be_undone(setup):
    pupil = _pupil(setup, "Changed Mind")
    exemption_id = _excuse(setup, pupil, kind="EXEMPT", reason="Scholarship")
    db = SessionLocal()
    try:
        school.remove_exemption(db, setup["owner"], exemption_id)
    finally:
        db.close()
    _open_term(setup)
    assert _balance(pupil) == 47_000


def test_setting_the_same_arrangement_twice_replaces_it(setup):
    pupil = _pupil(setup, "Revised")
    _excuse(setup, pupil, kind="PERCENT", value=50)
    _excuse(setup, pupil, kind="PERCENT", value=25)
    _open_term(setup)
    assert _balance(pupil) == 35_250           # 75% of 47,000


def test_a_nonsense_discount_is_refused(setup):
    pupil = _pupil(setup, "Aisha Bello")
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="between 1 and 100"):
            school.set_exemption(db, setup["owner"], pupil, kind="PERCENT", value=150)
        with pytest.raises(ValueError, match="Kind must be one of"):
            school.set_exemption(db, setup["owner"], pupil, kind="FREEBIE")
    finally:
        db.close()
