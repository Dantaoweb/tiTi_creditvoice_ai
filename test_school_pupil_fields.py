"""
The details each school decides to keep about a pupil.

Every school asks for name, sex and age; after that they diverge — blood group
and allergies in one, best colour and school house in another, who may collect
the child in a creche. So the registration form is built by the school, and
these tests pin the two things that makes it safe: an answer to a question the
school does not ask is dropped rather than stored, and a required answer that
is missing refuses the registration instead of half-writing it.
"""
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pupil-fields-00000000")

import pytest

import school_service as school
from database import Base, SessionLocal, engine
from models import Customer, PupilField, User

Base.metadata.create_all(engine)
_seq = iter(range(100, 900))


@pytest.fixture
def owner():
    phone = f"23480901101{next(_seq)}"
    db = SessionLocal()
    try:
        db.add(User(phone=phone, name="Bright Star School",
                    business_type="private_school"))
        db.commit()
        return phone
    finally:
        db.close()


def _fields(owner_phone, **kw):
    db = SessionLocal()
    try:
        return [school.field_dict(f) for f in school.pupil_fields(db, owner_phone, **kw)]
    finally:
        db.close()


def _register(owner_phone, name="Aisha Bello", **kw):
    db = SessionLocal()
    try:
        customer, _enrolment = school.register_pupil(db, owner_phone, name, **kw)
        return customer.id
    finally:
        db.close()


def _stored(customer_id):
    db = SessionLocal()
    try:
        raw = db.query(Customer.profile_json).filter(
            Customer.id == customer_id).scalar()
        return json.loads(raw) if raw else {}
    finally:
        db.close()


# ── The form a school starts with ────────────────────────────────────────────

def test_a_new_school_can_register_before_configuring_anything(owner):
    fields = _fields(owner)
    assert {f["key"] for f in fields} >= {"sex", "date_of_birth", "age", "address"}
    assert next(f for f in fields if f["key"] == "sex")["is_required"] is True


def test_the_standard_fields_are_seeded_once(owner):
    _fields(owner)
    _fields(owner)
    db = SessionLocal()
    try:
        assert db.query(PupilField).filter(
            PupilField.owner_phone == owner,
            PupilField.key == "sex").count() == 1
    finally:
        db.close()


def test_a_school_can_drop_a_standard_field(owner):
    fields = _fields(owner)
    age = next(f for f in fields if f["key"] == "age")
    db = SessionLocal()
    try:
        school.update_pupil_field(db, owner, age["id"], is_active=False)
    finally:
        db.close()
    assert "age" not in {f["key"] for f in _fields(owner)}


# ── A school's own questions ─────────────────────────────────────────────────

def test_a_school_adds_the_details_it_cares_about(owner):
    db = SessionLocal()
    try:
        school.add_pupil_field(db, owner, "Best colour")
        school.add_pupil_field(db, owner, "Best food")
        school.add_pupil_field(db, owner, "Hobby")
        school.add_pupil_field(db, owner, "Blood group", "choice",
                               options=["A+", "O+", "AB-"])
    finally:
        db.close()

    keys = {f["key"] for f in _fields(owner)}
    assert {"best_colour", "best_food", "hobby", "blood_group"} <= keys

    customer_id = _register(owner, details={
        "sex": "Female", "best_colour": "Blue", "best_food": "Jollof rice",
        "hobby": "Singing", "blood_group": "O+",
    })
    assert _stored(customer_id)["best_food"] == "Jollof rice"


def test_adding_the_same_field_twice_does_not_make_two(owner):
    db = SessionLocal()
    try:
        first = school.add_pupil_field(db, owner, "Best colour")
        second = school.add_pupil_field(db, owner, "Best Colour")
        assert first.id == second.id
    finally:
        db.close()


def test_a_dropped_field_comes_back_rather_than_duplicating(owner):
    db = SessionLocal()
    try:
        field = school.add_pupil_field(db, owner, "Hobby")
        school.update_pupil_field(db, owner, field.id, is_active=False)
        again = school.add_pupil_field(db, owner, "Hobby")
        assert again.id == field.id and again.is_active is True
    finally:
        db.close()


# ── What is accepted ─────────────────────────────────────────────────────────

def test_an_answer_to_a_question_this_school_does_not_ask_is_dropped(owner):
    customer_id = _register(owner, details={"sex": "Female",
                                            "favourite_football_team": "Chelsea"})
    assert "favourite_football_team" not in _stored(customer_id)


def test_a_required_answer_that_is_missing_refuses_the_registration(owner):
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="Sex is required"):
            school.register_pupil(db, owner, "No Sex Given", details={"age": "9"})
        assert db.query(Customer).filter(Customer.owner_phone == owner).count() == 0
    finally:
        db.close()


def test_a_number_field_refuses_words(owner):
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="Age must be a number"):
            school.register_pupil(db, owner, "Aisha",
                                  details={"sex": "Female", "age": "nine"})
    finally:
        db.close()


def test_a_date_is_stored_the_same_way_however_it_is_typed(owner):
    first = _register(owner, "Aisha Bello",
                      details={"sex": "Female", "date_of_birth": "23/04/2015"})
    second = _register(owner, "Tunde Okoro",
                       details={"sex": "Male", "date_of_birth": "2015-04-23"})
    assert _stored(first)["date_of_birth"] == _stored(second)["date_of_birth"] == "2015-04-23"


def test_a_choice_must_be_one_of_the_choices(owner):
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="Sex must be one of"):
            school.register_pupil(db, owner, "Aisha", details={"sex": "Maybe"})
    finally:
        db.close()


def test_a_choice_is_accepted_however_it_is_capitalised(owner):
    customer_id = _register(owner, details={"sex": "female"})
    assert _stored(customer_id)["sex"] == "Female"      # stored as defined


# ── Editing ──────────────────────────────────────────────────────────────────

def test_updating_one_detail_keeps_the_rest(owner):
    db = SessionLocal()
    try:
        school.add_pupil_field(db, owner, "Best food")
        school.add_pupil_field(db, owner, "Hobby")
    finally:
        db.close()

    customer_id = _register(owner, details={"sex": "Female", "best_food": "Jollof rice",
                                            "hobby": "Singing"})
    _register(owner, details={"hobby": "Dancing"})       # same child, one change
    stored = _stored(customer_id)
    assert stored["hobby"] == "Dancing"
    assert stored["best_food"] == "Jollof rice"          # not wiped


def test_the_details_read_back_labelled_and_in_order(owner):
    db = SessionLocal()
    try:
        school.add_pupil_field(db, owner, "Best colour")
    finally:
        db.close()
    customer_id = _register(owner, details={"sex": "Female", "best_colour": "Blue"})

    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        details = school.pupil_details(db, owner, customer)
    finally:
        db.close()
    assert {"key": "sex", "label": "Sex", "value": "Female"} in details
    assert {"key": "best_colour", "label": "Best colour", "value": "Blue"} in details


def test_a_school_sees_only_its_own_questions(owner):
    db = SessionLocal()
    try:
        school.add_pupil_field(db, owner, "School house")
        other = f"23480901102{next(_seq)}"
        db.add(User(phone=other, name="Other School"))
        db.commit()
        assert "house" not in {f.key for f in school.pupil_fields(db, other)}
        assert "school_house" not in {f.key for f in school.pupil_fields(db, other)}
    finally:
        db.close()
