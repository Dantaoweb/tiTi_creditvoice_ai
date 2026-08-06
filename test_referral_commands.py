"""
WhatsApp referral commands: parse "set my referral code X" / "my referral code"
in varied phrasings, and the set/view handlers (validation, uniqueness, share).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-ref-commands-0000000000")

import pytest

import main  # noqa: F401  -- triggers table creation on the in-memory DB
from parser import parse_message
from database import SessionLocal
from models import User
from referral_commands import handle_set_referral_code, handle_show_referral_code


def _sent():
    box = []
    return box, (lambda phone, msg: box.append(msg))


# ── parsing ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,code", [
    ("set my referral code DANSHOP", "DANSHOP"),
    ("set referral code danshop", "DANSHOP"),
    ("create referral code Shop123", "SHOP123"),
    ("change my referral code to BIGMAN", "BIGMAN"),
    ("my referral code is ADA22", "ADA22"),
    ("i want my referral code to be KING", "KING"),
    ("referral code TUNDE", "TUNDE"),
])
def test_parse_set_referral_code(text, code):
    p = parse_message(text)
    assert p and p.get("type") == "SET_REFERRAL_CODE" and p.get("code") == code


@pytest.mark.parametrize("text", [
    "my referral code", "show my referral code", "what is my referral code",
    "my referral link",
])
def test_parse_show_referral_code(text):
    p = parse_message(text)
    assert p and p.get("type") == "SHOW_REFERRAL_CODE"


def test_bare_referral_code_question_is_not_a_set():
    # No code argument -> not a set command (falls through to the FAQ answer).
    p = parse_message("referral code")
    assert not (p and p.get("type") == "SET_REFERRAL_CODE")


# ── handlers ────────────────────────────────────────────────────────────────
def _mk_user(phone):
    db = SessionLocal()
    try:
        u = User(phone=phone, name="Owner", role="owner")
        db.add(u); db.commit()
    finally:
        db.close()


def test_set_and_show_referral_code():
    _mk_user("2348250000001")
    box, send = _sent()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == "2348250000001").first()
        r = handle_set_referral_code(db, u, "DANSHOP", send, u.phone)
        assert r["status"] == "referral_code_set"
        assert db.query(User).filter(User.phone == "2348250000001").first().referral_code == "DANSHOP"
        assert "DANSHOP" in box[-1] and "join DANSHOP" in box[-1]

        handle_show_referral_code(db, u, send, u.phone)
        assert "DANSHOP" in box[-1]
    finally:
        db.close()


def test_invalid_code_rejected():
    _mk_user("2348250000002")
    box, send = _sent()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == "2348250000002").first()
        r = handle_set_referral_code(db, u, "no", send, u.phone)   # too short
        assert r["status"] == "referral_code_invalid"
        assert db.query(User).filter(User.phone == "2348250000002").first().referral_code in (None, "")
    finally:
        db.close()


def test_duplicate_code_rejected():
    _mk_user("2348250000003")
    _mk_user("2348250000004")
    box, send = _sent()
    db = SessionLocal()
    try:
        u3 = db.query(User).filter(User.phone == "2348250000003").first()
        handle_set_referral_code(db, u3, "SHARED1", send, u3.phone)
        u4 = db.query(User).filter(User.phone == "2348250000004").first()
        r = handle_set_referral_code(db, u4, "SHARED1", send, u4.phone)
        assert r["status"] == "referral_code_taken"
        assert "taken" in box[-1].lower()
    finally:
        db.close()


def test_show_when_unset_prompts_to_set():
    _mk_user("2348250000005")
    box, send = _sent()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == "2348250000005").first()
        r = handle_show_referral_code(db, u, send, u.phone)
        assert r["status"] == "referral_code_unset"
        assert "set my referral code" in box[-1].lower()
    finally:
        db.close()
