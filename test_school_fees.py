"""
A school's books, from registering a pupil to paying for a textbook.

The thing worth proving here is that fees go through the same machinery as
every other debt: a charge raises the pupil's balance, a payment clears it, and
the debtors list picks it up — because a pupil is a Customer and a charge is an
ordinary credit transaction. The school-specific part is the term: fees are
owed per term, the school knows the amounts before anyone pays, and opening a
term twice must not charge anybody twice.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-school-fees-000000000")

import pytest

import school_service as school
from database import Base, SessionLocal, engine
from models import Customer, FeeInvoice, FeeItem, SchoolClass, Transaction, User

Base.metadata.create_all(engine)
_seq = iter(range(100, 900))


@pytest.fixture
def owner():
    phone = f"23480900991{next(_seq)}"
    db = SessionLocal()
    try:
        db.add(User(phone=phone, name="Bright Star School",
                    business_type="private_school"))
        db.commit()
        return phone
    finally:
        db.close()


@pytest.fixture
def school_setup(owner):
    """A school year, two classes, and the things it charges for."""
    db = SessionLocal()
    try:
        session, terms = school.start_session(db, owner, "2025/2026")
        jss2 = SchoolClass(owner_phone=owner, name="JSS 2", level_order=2)
        pry4 = SchoolClass(owner_phone=owner, name="Primary 4", level_order=1)
        tuition = FeeItem(owner_phone=owner, name="Tuition", kind="FEE")
        pta = FeeItem(owner_phone=owner, name="PTA levy", kind="LEVY")
        book = FeeItem(owner_phone=owner, name="Mathematics textbook", kind="BOOK",
                       default_amount=3_500, is_optional=True)
        db.add_all([jss2, pry4, tuition, pta, book])
        db.commit()
        return {
            "owner": owner, "session": session.id,
            "term1": terms[0].id, "term2": terms[1].id,
            "jss2": jss2.id, "pry4": pry4.id,
            "tuition": tuition.id, "pta": pta.id, "book": book.id,
        }
    finally:
        db.close()


def _schedule(setup, class_id, tuition, pta=2_000, book=None):
    db = SessionLocal()
    try:
        amounts = {setup["tuition"]: tuition, setup["pta"]: pta}
        if book is not None:
            amounts[setup["book"]] = book
        school.set_fee_schedule(db, setup["owner"], setup["term1"], class_id, amounts)
    finally:
        db.close()


def _register(setup, name, class_id, parent="Mr Bello", phone="08031112222"):
    db = SessionLocal()
    try:
        customer, enrolment = school.register_pupil(
            db, setup["owner"], name, class_id=class_id,
            parent_name=parent, parent_phone=phone)
        return customer.id, enrolment.admission_no
    finally:
        db.close()


def _balance(customer_id):
    db = SessionLocal()
    try:
        return int(db.query(Customer.balance).filter(
            Customer.id == customer_id).scalar() or 0)
    finally:
        db.close()


def _open_term(setup, term_key="term1"):
    db = SessionLocal()
    try:
        return school.open_term(db, setup["owner"], setup[term_key])
    finally:
        db.close()


# ── Registering a pupil ──────────────────────────────────────────────────────

def test_a_pupil_is_registered_with_an_admission_number(school_setup):
    customer_id, admission_no = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    assert admission_no.startswith("2025/")
    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        assert customer.name == "Aisha Bello"
        assert customer.customer_phone == "08031112222"     # the parent is reachable
    finally:
        db.close()


def test_admission_numbers_do_not_repeat(school_setup):
    _, first = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _, second = _register(school_setup, "Tunde Okoro", school_setup["jss2"])
    assert first != second


def test_registering_the_same_child_twice_moves_them_rather_than_duplicating(school_setup):
    first_id, admission = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    second_id, again = _register(school_setup, "aisha bello", school_setup["pry4"])
    assert first_id == second_id
    assert again == admission

    db = SessionLocal()
    try:
        assert db.query(Customer).filter(
            Customer.owner_phone == school_setup["owner"]).count() == 1
        enrolments = school.pupils_in_class(db, school_setup["owner"],
                                            school_setup["pry4"], school_setup["session"])
        assert len(enrolments) == 1
    finally:
        db.close()


# ── What a class owes ────────────────────────────────────────────────────────

def test_the_schedule_reads_as_the_whole_bill(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000, book=3_500)
    db = SessionLocal()
    try:
        rows = school.schedule_for(db, school_setup["owner"], school_setup["term1"],
                                   school_setup["jss2"])
        assert {r["name"] for r in rows} == {"Tuition", "PTA levy", "Mathematics textbook"}
        assert rows[-1]["is_optional"] is True        # optional items sort last
    finally:
        db.close()


def test_removing_an_item_from_the_schedule_removes_the_charge(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    db = SessionLocal()
    try:
        school.set_fee_schedule(db, school_setup["owner"], school_setup["term1"],
                                school_setup["jss2"], {school_setup["tuition"]: 45_000})
        rows = school.schedule_for(db, school_setup["owner"], school_setup["term1"],
                                   school_setup["jss2"])
        assert [r["name"] for r in rows] == ["Tuition"]
    finally:
        db.close()


# ── Opening a term ───────────────────────────────────────────────────────────

def test_opening_a_term_charges_every_pupil_what_their_class_owes(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    _schedule(school_setup, school_setup["pry4"], tuition=30_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    tunde, _ = _register(school_setup, "Tunde Okoro", school_setup["pry4"])

    result = _open_term(school_setup)
    assert result["charged"] == 2
    assert result["total"] == 47_000 + 32_000
    assert _balance(aisha) == 47_000           # the balance machinery, unchanged
    assert _balance(tunde) == 32_000


def test_a_textbook_is_not_charged_just_because_the_class_has_one(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000, book=3_500)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _open_term(school_setup)
    assert _balance(aisha) == 47_000           # the optional book is not owed yet


def test_opening_a_term_twice_charges_nobody_twice(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])

    first = _open_term(school_setup)
    second = _open_term(school_setup)
    assert first["charged"] == 1
    assert second["charged"] == 0
    assert second["already_charged"] == 1
    assert _balance(aisha) == 47_000


def test_a_pupil_registered_after_the_term_opened_is_picked_up_next_run(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _open_term(school_setup)

    late, _ = _register(school_setup, "Late Arrival", school_setup["jss2"])
    result = _open_term(school_setup)
    assert result["charged"] == 1
    assert _balance(late) == 47_000


def test_the_charge_is_itemised(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _open_term(school_setup)

    db = SessionLocal()
    try:
        statement = school.student_statement(db, school_setup["owner"], aisha)
        charge = statement["entries"][0]
        assert charge["kind"] == "charge"
        assert {i["name"] for i in charge["items"]} == {"Tuition", "PTA levy"}
    finally:
        db.close()


# ── Textbooks taken during the term ──────────────────────────────────────────

def test_a_textbook_is_charged_when_the_pupil_takes_it(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000, book=3_500)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _open_term(school_setup)

    db = SessionLocal()
    try:
        invoice = school.charge_items(db, school_setup["owner"], aisha,
                                      school_setup["term1"],
                                      [{"fee_item_id": school_setup["book"], "quantity": 2}])
        assert invoice.total == 7_000
        assert invoice.kind == "EXTRA"
    finally:
        db.close()
    assert _balance(aisha) == 47_000 + 7_000


def test_an_item_with_no_price_anywhere_is_not_charged(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    db = SessionLocal()
    try:
        unpriced = FeeItem(owner_phone=school_setup["owner"], name="Excursion",
                           kind="OTHER", is_optional=True)
        db.add(unpriced)
        db.commit()
        assert school.charge_items(db, school_setup["owner"], aisha,
                                   school_setup["term1"],
                                   [{"fee_item_id": unpriced.id}]) is None
    finally:
        db.close()


# ── Paying ───────────────────────────────────────────────────────────────────

def test_a_payment_clears_the_balance_like_any_other_debt(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _open_term(school_setup)

    db = SessionLocal()
    try:
        school.record_payment(db, school_setup["owner"], aisha, 30_000)
    finally:
        db.close()
    assert _balance(aisha) == 17_000


def test_a_paid_up_pupil_is_off_the_defaulters_list(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    tunde, _ = _register(school_setup, "Tunde Okoro", school_setup["jss2"])
    _open_term(school_setup)

    db = SessionLocal()
    try:
        school.record_payment(db, school_setup["owner"], aisha, 47_000)
        owing = school.defaulters(db, school_setup["owner"], school_setup["term1"])
        assert [d["name"] for d in owing] == ["Tunde Okoro"]
        assert owing[0]["outstanding"] == 47_000
        assert owing[0]["class_name"] == "JSS 2"
    finally:
        db.close()


# ── What the bursar sees ─────────────────────────────────────────────────────

def test_the_term_summary_shows_expected_against_outstanding(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    _schedule(school_setup, school_setup["pry4"], tuition=30_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _register(school_setup, "Tunde Okoro", school_setup["pry4"])
    _open_term(school_setup)

    db = SessionLocal()
    try:
        school.record_payment(db, school_setup["owner"], aisha, 47_000)
        summary = school.term_summary(db, school_setup["owner"], school_setup["term1"])
        assert summary["expected"] == 79_000
        assert summary["outstanding"] == 32_000
        assert summary["collected"] == 47_000
        assert summary["collection_rate"] == 59       # 47,000 of 79,000
        worst = summary["classes"][0]
        assert worst["class_name"] == "Primary 4"     # the class that owes most
    finally:
        db.close()


def test_a_statement_reads_as_the_parent_would_expect(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000, book=3_500)
    aisha, admission = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _open_term(school_setup)

    db = SessionLocal()
    try:
        school.charge_items(db, school_setup["owner"], aisha, school_setup["term1"],
                            [{"fee_item_id": school_setup["book"]}])
        school.record_payment(db, school_setup["owner"], aisha, 20_000)
        statement = school.student_statement(db, school_setup["owner"], aisha)
    finally:
        db.close()

    assert statement["admission_no"] == admission
    assert statement["class_name"] == "JSS 2"
    assert statement["parent_name"] == "Mr Bello"
    assert statement["balance"] == 47_000 + 3_500 - 20_000
    kinds = [e["kind"] for e in statement["entries"]]
    assert kinds.count("charge") == 2 and kinds.count("payment") == 1


# ── Terms and promotion ──────────────────────────────────────────────────────

def test_each_term_is_charged_separately(school_setup):
    _schedule(school_setup, school_setup["jss2"], tuition=45_000, pta=2_000)
    aisha, _ = _register(school_setup, "Aisha Bello", school_setup["jss2"])
    _open_term(school_setup, "term1")

    db = SessionLocal()
    try:
        school.set_fee_schedule(db, school_setup["owner"], school_setup["term2"],
                                school_setup["jss2"], {school_setup["tuition"]: 45_000})
        result = school.open_term(db, school_setup["owner"], school_setup["term2"])
    finally:
        db.close()
    assert result["charged"] == 1
    assert _balance(aisha) == 47_000 + 45_000


def test_promotion_keeps_the_old_record(school_setup):
    aisha, admission = _register(school_setup, "Aisha Bello", school_setup["pry4"])
    db = SessionLocal()
    try:
        new_session, _terms = school.start_session(db, school_setup["owner"], "2026/2027")
        school.promote(db, school_setup["owner"], aisha, school_setup["jss2"],
                       new_session.id)
        old = school.pupils_in_class(db, school_setup["owner"], school_setup["pry4"],
                                     school_setup["session"])
        new = school.pupils_in_class(db, school_setup["owner"], school_setup["jss2"],
                                     new_session.id)
        assert len(old) == 1 and len(new) == 1          # last year's record survives
        assert new[0].admission_no == admission         # same child, same number
    finally:
        db.close()


def test_a_class_with_no_schedule_charges_nobody(school_setup):
    _register(school_setup, "Aisha Bello", school_setup["jss2"])
    assert _open_term(school_setup)["charged"] == 0
