"""
Reading the failures as a work queue.

Two tables have been collecting what tiTi got wrong and nothing read them. The
test of this layer is whether it turns five thousand raw messages into a short
list worth acting on: the same question asked different ways must land in one
group, and the ranking must favour "many businesses asked this" over "one
person asked twenty times".
"""
import os
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-parse-gaps-0000000000")

import pytest

import parse_gaps
from database import Base, SessionLocal, engine
from models import FailedParse, ParseLog, utcnow

Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def _clean():
    db = SessionLocal()
    try:
        db.query(FailedParse).delete()
        db.query(ParseLog).delete()
        db.commit()
    finally:
        db.close()
    yield


def _missed(text, owner="2348090088001", days_ago=1):
    db = SessionLocal()
    try:
        db.add(FailedParse(phone=owner, owner_phone=owner, text=text,
                           created_at=utcnow() - timedelta(days=days_ago)))
        db.commit()
    finally:
        db.close()


def _corrected(said, meant, owner="2348090088001", parsed_type="TRANSACTION"):
    db = SessionLocal()
    try:
        db.add(ParseLog(phone=owner, owner_phone=owner, raw_input=said,
                        parsed_type=parsed_type, was_confirmed=False,
                        correction_input=meant, created_at=utcnow() - timedelta(days=1)))
        db.commit()
    finally:
        db.close()


def _gaps(**kw):
    db = SessionLocal()
    try:
        return parse_gaps.unanswered(db, **kw)
    finally:
        db.close()


# ── Grouping: the same question, asked differently ───────────────────────────

def test_the_same_question_worded_differently_is_one_row():
    _missed("how much do I pay for rice")
    _missed("what do I pay for rice?")
    _missed("abeg how much I dey pay for rice")
    groups = _gaps()
    assert len(groups) == 1
    assert groups[0]["count"] == 3
    assert len(groups[0]["examples"]) == 3


def test_amounts_do_not_split_one_question_into_many():
    _missed("sold 3 bags of rice for 180000")
    _missed("sold 5 bags of rice for 300000")
    _missed("sold 2 bags of rice for 120,000")
    groups = _gaps()
    assert len(groups) == 1
    assert groups[0]["count"] == 3


def test_different_questions_stay_apart():
    _missed("how much do I pay for rice")
    _missed("which customers have not paid me")
    assert len(_gaps()) == 2


# ── Ranking: what is worth fixing first ──────────────────────────────────────

def test_many_businesses_outrank_one_person_repeating_themselves():
    for i in range(20):
        _missed("when is my subscription expiring", owner="2348090088009")
    for i in range(5):
        _missed("how much profit did I make", owner=f"234809008810{i}")

    groups = _gaps()
    assert groups[0]["businesses"] == 5          # five businesses beats twenty messages
    assert "profit" in groups[0]["signature"]
    assert groups[1]["count"] == 20


def test_a_question_is_told_apart_from_a_recording():
    _missed("how many customers owe me money")
    _missed("sold 3 bags rice 180000 to ade")
    shapes = {g["shape"] for g in _gaps()}
    assert "question" in shapes
    assert "transaction" in shapes


def test_only_the_window_asked_for_is_read():
    _missed("how much do I pay for rice", days_ago=200)
    _missed("which customers owe me", days_ago=2)
    assert len(_gaps(days=30)) == 1
    assert len(_gaps(days=365)) == 2


def test_empty_messages_are_ignored():
    _missed("   ")
    _missed("?")
    assert _gaps() == []


# ── Corrections: the right answer written next to the wrong one ──────────────

def test_corrections_are_paired_with_what_was_said():
    _corrected("ade collect 2 bag rice", "ade bought 2 bags rice 160000")
    _corrected("tunde collect 1 bag rice", "tunde bought 1 bag rice 80000")

    db = SessionLocal()
    try:
        rows = parse_gaps.misreadings(db)
    finally:
        db.close()
    # One shape, both examples — the customer's name must not split the group.
    assert len(rows) == 1
    assert rows[0]["count"] == 2
    said = {p["said"] for p in rows[0]["pairs"]}
    assert said == {"ade collect 2 bag rice", "tunde collect 1 bag rice"}
    assert all("bought" in p["meant"] for p in rows[0]["pairs"])


def test_a_confirmed_parse_is_not_a_correction():
    db = SessionLocal()
    try:
        db.add(ParseLog(phone="2348090088001", owner_phone="2348090088001",
                        raw_input="sold rice 5000", was_confirmed=True,
                        created_at=utcnow() - timedelta(days=1)))
        db.commit()
        assert parse_gaps.misreadings(db) == []
    finally:
        db.close()


# ── The headline ─────────────────────────────────────────────────────────────

def test_the_summary_counts_what_matters():
    _missed("how much profit did I make", owner="2348090088001")
    _missed("how much profit did i make", owner="2348090088002")
    _missed("sold 3 bags rice 180000", owner="2348090088003")

    db = SessionLocal()
    try:
        s = parse_gaps.summary(db)
    finally:
        db.close()
    assert s["messages"] == 3
    assert s["distinct_questions"] == 2
    assert s["businesses_affected"] == 3
    assert s["questions"] >= 2
