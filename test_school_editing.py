"""
Correcting what was entered.

Anything typed into a school's screens can be typed again — names get
misspelled, a pupil sits in the wrong class, a parent changes number, fees are
set wrong. The only limit is money already recorded: a pupil who has been
charged, a class that has been invoiced and a fee already on a bill are closed
or retired rather than deleted, because removing them would quietly change what
a term collected. Each refusal has to say so rather than failing silently.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-school-editing-000000")

import pytest

import school_service as school
from database import Base, SessionLocal, engine
from models import Customer, FeeItem, SchoolClass, StudentEnrolment, User

Base.metadata.create_all(engine)
_seq = iter(range(100, 900))


@pytest.fixture
def setup():
    phone = f"23480901201{next(_seq)}"
    db = SessionLocal()
    try:
        db.add(User(phone=phone, name="Bright Star School",
                    business_type="private_school"))
        db.commit()
        session, terms = school.start_session(db, phone, "2025/2026")
        jss2 = SchoolClass(owner_phone=phone, name="JSS 2")
        pry4 = SchoolClass(owner_phone=phone, name="Primary 4")
        tuition = FeeItem(owner_phone=phone, name="Tuition", kind="FEE")
        db.add_all([jss2, pry4, tuition])
        db.commit()
        return {"owner": phone, "session": session.id, "term": terms[0].id,
                "jss2": jss2.id, "pry4": pry4.id, "tuition": tuition.id}
    finally:
        db.close()


def _register(setup, name="Aisha Bello", class_id=None, **kw):
    db = SessionLocal()
    try:
        customer, _ = school.register_pupil(
            db, setup["owner"], name, class_id=class_id or setup["jss2"],
            parent_name="Mr Bello", parent_phone="08031112222",
            details={"sex": "Female"}, **kw)
        return customer.id
    finally:
        db.close()


def _charge_the_term(setup):
    db = SessionLocal()
    try:
        school.set_fee_schedule(db, setup["owner"], setup["term"], setup["jss2"],
                                {setup["tuition"]: 45_000})
        return school.open_term(db, setup["owner"], setup["term"])
    finally:
        db.close()


def _pupil(customer_id):
    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        enrolment = (db.query(StudentEnrolment)
                     .filter(StudentEnrolment.customer_id == customer_id)
                     .order_by(StudentEnrolment.enrolled_at.desc()).first())
        return customer, enrolment
    finally:
        db.close()


# ── Pupils ───────────────────────────────────────────────────────────────────

def test_a_misspelled_name_can_be_corrected(setup):
    customer_id = _register(setup, "Aisah Bello")
    db = SessionLocal()
    try:
        school.update_pupil(db, setup["owner"], customer_id, name="Aisha Bello")
    finally:
        db.close()
    assert _pupil(customer_id)[0].name == "Aisha Bello"


def test_a_pupil_can_be_moved_to_another_class(setup):
    customer_id = _register(setup)
    db = SessionLocal()
    try:
        school.update_pupil(db, setup["owner"], customer_id, class_id=setup["pry4"])
    finally:
        db.close()
    assert _pupil(customer_id)[1].class_id == setup["pry4"]


def test_a_parents_new_number_replaces_the_old_one(setup):
    customer_id = _register(setup)
    db = SessionLocal()
    try:
        school.update_pupil(db, setup["owner"], customer_id,
                            parent_name="Mrs Bello", parent_phone="08099998888")
    finally:
        db.close()
    customer, enrolment = _pupil(customer_id)
    assert customer.customer_phone == "08099998888"
    assert enrolment.parent_name == "Mrs Bello"


def test_an_edit_leaves_untouched_fields_alone(setup):
    customer_id = _register(setup)
    db = SessionLocal()
    try:
        school.update_pupil(db, setup["owner"], customer_id, name="Aisha B Bello")
    finally:
        db.close()
    customer, enrolment = _pupil(customer_id)
    assert customer.customer_phone == "08031112222"      # not blanked
    assert enrolment.parent_name == "Mr Bello"
    assert enrolment.class_id == setup["jss2"]


def test_the_schools_own_answers_can_be_corrected(setup):
    db = SessionLocal()
    try:
        school.add_pupil_field(db, setup["owner"], "Best colour")
    finally:
        db.close()
    customer_id = _register(setup)

    db = SessionLocal()
    try:
        school.update_pupil(db, setup["owner"], customer_id,
                            details={"best_colour": "Blue"})
        school.update_pupil(db, setup["owner"], customer_id,
                            details={"best_colour": "Green"})
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        details = {d["key"]: d["value"] for d in
                   school.pupil_details(db, setup["owner"], customer)}
    finally:
        db.close()
    assert details["best_colour"] == "Green"
    assert details["sex"] == "Female"                    # the rest survives


def test_two_pupils_cannot_be_given_the_same_name(setup):
    _register(setup, "Aisha Bello")
    other = _register(setup, "Tunde Okoro")
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="already called"):
            school.update_pupil(db, setup["owner"], other, name="Aisha Bello")
    finally:
        db.close()


def test_a_pupil_with_no_fees_can_be_removed_outright(setup):
    customer_id = _register(setup)
    db = SessionLocal()
    try:
        result = school.remove_pupil(db, setup["owner"], customer_id)
        assert result["deleted"] is True
        assert db.query(Customer).filter(Customer.id == customer_id).first() is None
    finally:
        db.close()


def test_a_pupil_who_has_been_charged_is_marked_left_not_deleted(setup):
    customer_id = _register(setup)
    _charge_the_term(setup)

    db = SessionLocal()
    try:
        result = school.remove_pupil(db, setup["owner"], customer_id)
    finally:
        db.close()
    assert result["deleted"] is False and result["marked_left"] is True
    assert "term collected" in result["reason"]
    customer, enrolment = _pupil(customer_id)
    assert customer is not None                          # the money stays on the books
    assert enrolment.status == "LEFT"


def test_a_pupil_who_left_is_off_the_class_list(setup):
    customer_id = _register(setup)
    _charge_the_term(setup)
    db = SessionLocal()
    try:
        school.remove_pupil(db, setup["owner"], customer_id)
        assert school.pupils_in_class(db, setup["owner"], setup["jss2"],
                                      setup["session"]) == []
    finally:
        db.close()


# ── Classes ──────────────────────────────────────────────────────────────────

def test_a_class_can_be_renamed(setup):
    db = SessionLocal()
    try:
        school.update_class(db, setup["owner"], setup["jss2"], name="JSS 2A")
        row = db.query(SchoolClass).filter(SchoolClass.id == setup["jss2"]).first()
        assert row.name == "JSS 2A"
    finally:
        db.close()


def test_an_empty_class_can_be_deleted(setup):
    db = SessionLocal()
    try:
        assert school.delete_class(db, setup["owner"], setup["pry4"])["deleted"] is True
        assert db.query(SchoolClass).filter(
            SchoolClass.id == setup["pry4"]).first() is None
    finally:
        db.close()


def test_a_class_pupils_have_sat_in_is_closed_not_deleted(setup):
    _register(setup)
    db = SessionLocal()
    try:
        result = school.delete_class(db, setup["owner"], setup["jss2"])
        row = db.query(SchoolClass).filter(SchoolClass.id == setup["jss2"]).first()
    finally:
        db.close()
    assert result["deleted"] is False and result["closed"] is True
    assert "1 pupil(s)" in result["reason"]
    assert row is not None and row.is_active is False


# ── Fee items and what a class owes ──────────────────────────────────────────

def test_a_fee_item_can_be_renamed_and_repriced(setup):
    db = SessionLocal()
    try:
        school.update_fee_item(db, setup["owner"], setup["tuition"],
                               name="Tuition fee", default_amount=50_000)
        row = db.query(FeeItem).filter(FeeItem.id == setup["tuition"]).first()
        assert row.name == "Tuition fee" and row.default_amount == 50_000
    finally:
        db.close()


def test_what_a_class_owes_can_be_changed(setup):
    db = SessionLocal()
    try:
        school.set_fee_schedule(db, setup["owner"], setup["term"], setup["jss2"],
                                {setup["tuition"]: 45_000})
        school.set_fee_schedule(db, setup["owner"], setup["term"], setup["jss2"],
                                {setup["tuition"]: 50_000})
        rows = school.schedule_for(db, setup["owner"], setup["term"], setup["jss2"])
        assert rows[0]["amount"] == 50_000
    finally:
        db.close()


def test_an_item_left_out_of_the_schedule_is_removed_from_the_bill(setup):
    db = SessionLocal()
    try:
        pta = FeeItem(owner_phone=setup["owner"], name="PTA levy", kind="LEVY")
        db.add(pta)
        db.commit()
        school.set_fee_schedule(db, setup["owner"], setup["term"], setup["jss2"],
                                {setup["tuition"]: 45_000, pta.id: 2_000})
        school.set_fee_schedule(db, setup["owner"], setup["term"], setup["jss2"],
                                {setup["tuition"]: 45_000})
        rows = school.schedule_for(db, setup["owner"], setup["term"], setup["jss2"])
        assert [r["name"] for r in rows] == ["Tuition"]
    finally:
        db.close()


def test_an_uncharged_fee_item_can_be_deleted(setup):
    db = SessionLocal()
    try:
        assert school.delete_fee_item(db, setup["owner"], setup["tuition"])["deleted"] is True
    finally:
        db.close()


def test_a_fee_already_on_a_bill_is_retired_not_deleted(setup):
    _register(setup)
    _charge_the_term(setup)
    db = SessionLocal()
    try:
        result = school.delete_fee_item(db, setup["owner"], setup["tuition"])
        row = db.query(FeeItem).filter(FeeItem.id == setup["tuition"]).first()
    finally:
        db.close()
    assert result["deleted"] is False and result["retired"] is True
    assert "already been charged" in result["reason"]
    assert row is not None and row.is_active is False


# ── The school's own questions ───────────────────────────────────────────────

def test_a_question_can_be_renamed(setup):
    db = SessionLocal()
    try:
        field = school.add_pupil_field(db, setup["owner"], "Best colour")
        school.update_pupil_field(db, setup["owner"], field.id, label="Favourite colour")
        labels = {f.label for f in school.pupil_fields(db, setup["owner"])}
        assert "Favourite colour" in labels
    finally:
        db.close()


def test_a_question_the_school_added_can_be_deleted(setup):
    db = SessionLocal()
    try:
        field = school.add_pupil_field(db, setup["owner"], "Best colour")
        assert school.delete_pupil_field(db, setup["owner"], field.id)["deleted"] is True
        assert "best_colour" not in {f.key for f in school.pupil_fields(db, setup["owner"])}
    finally:
        db.close()


def test_a_standard_question_is_switched_off_rather_than_deleted(setup):
    db = SessionLocal()
    try:
        sex = next(f for f in school.pupil_fields(db, setup["owner"]) if f.key == "sex")
        result = school.delete_pupil_field(db, setup["owner"], sex.id)
        assert result["deleted"] is False and result["hidden"] is True
        assert "sex" not in {f.key for f in school.pupil_fields(db, setup["owner"])}
        assert "sex" in {f.key for f in school.pupil_fields(db, setup["owner"],
                                                           include_inactive=True)}
    finally:
        db.close()


def test_answers_already_given_survive_the_question_being_removed(setup):
    db = SessionLocal()
    try:
        field_id = school.add_pupil_field(db, setup["owner"], "Best colour").id
    finally:
        db.close()
    customer_id = _register(setup)
    db = SessionLocal()
    try:
        school.update_pupil(db, setup["owner"], customer_id,
                            details={"best_colour": "Blue"})
        school.delete_pupil_field(db, setup["owner"], field_id)
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        assert "Blue" in (customer.profile_json or "")      # kept, just not asked
    finally:
        db.close()
