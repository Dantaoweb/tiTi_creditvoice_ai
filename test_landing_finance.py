"""
The financing section — the claim no competitor on this market can make.

QuickBooks sells bookkeeping and Bumpa sells an online store; neither turns a
trader's records into something a financier will act on. So the section has to
be accurate about two things: what the scorecard actually measures (read from
the live config, never typed into the page), and who decides — we do not lend,
and nothing is shared until the business applies.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-landing-finance-000000")

import pytest
from fastapi.testclient import TestClient

import main
from business_scorecard import DEFAULT_CONFIG
from database import SessionLocal
from main import app
from models import FinancePartner

client = TestClient(app, raise_server_exceptions=True)


_MINE = []


@pytest.fixture(autouse=True)
def _reset():
    # Partners made by other test modules are left alone — they are referenced
    # by applications and scorecard configs, so emptying the table fails on the
    # foreign key. These tests count relative to whatever is already there.
    main._LANDING_CACHE["blocks"] = None
    yield
    db = SessionLocal()
    try:
        for pid in _MINE:
            row = db.query(FinancePartner).filter(FinancePartner.id == pid).first()
            if row:
                db.delete(row)
        db.commit()
    finally:
        db.close()
    _MINE.clear()
    main._LANDING_CACHE["blocks"] = None


def _landing():
    main._LANDING_CACHE["blocks"] = None
    return client.get("/").text


def _active_partners():
    db = SessionLocal()
    try:
        return (db.query(FinancePartner)
                .filter(FinancePartner.is_active == True)      # noqa: E712
                .count())
    finally:
        db.close()


def _partner(name="Gigmile", active=True):
    db = SessionLocal()
    try:
        row = FinancePartner(name=name, is_active=active)
        db.add(row)
        db.commit()
        _MINE.append(row.id)
    finally:
        db.close()


def _expected_line(n):
    return f'{n} financing partner{"s" if n != 1 else ""} reviewing applications'


def test_the_section_is_on_the_page():
    body = _landing()
    assert 'id="financing"' in body
    assert "Records today. Financing tomorrow." in body
    assert "See your business score" in body
    assert "<!--FINANCE-->" not in body


def test_it_says_who_decides_and_that_we_do_not_lend():
    body = _landing()
    assert "does not lend money" in body
    assert "does not decide who is approved" in body
    assert "only shared with a partner when you apply" in body


def test_the_scorecard_components_come_from_the_live_config():
    body = _landing()
    heaviest = sorted(DEFAULT_CONFIG["components"].values(),
                      key=lambda c: -c["weight"])[:5]
    for component in heaviest:
        assert component["label"] in body
        assert f'{component["weight"]}%' in body
    # The lightest components are left out rather than crowding the card.
    assert len([c for c in DEFAULT_CONFIG["components"].values()
                if c["label"] in body]) <= 6


def test_an_admin_change_to_the_rules_shows_on_the_page(monkeypatch):
    """The page must not drift from the product when the rules are edited."""
    config = {
        "components": {
            "sales_volume": {"label": "Monthly sales", "metric": "avg_monthly_sales",
                             "weight": 40, "zero": 0, "full": 1_000_000},
            "tenure": {"label": "Years trading", "metric": "months_recorded",
                       "weight": 25, "zero": 1, "full": 12},
        },
    }
    monkeypatch.setattr("business_scorecard.config_for_partner",
                        lambda db, p=None: ("v9", config, []))
    body = _landing()
    assert "Years trading" in body
    assert "40%" in body and "25%" in body


def test_a_broken_config_still_renders_the_section(monkeypatch):
    def boom(db, partner=None):
        raise RuntimeError("scorecard config unreadable")
    monkeypatch.setattr("business_scorecard.config_for_partner", boom)
    body = _landing()
    assert "Records today. Financing tomorrow." in body
    assert "Monthly sales" in body          # fell back to the defaults


def test_partners_are_counted_and_only_shown_when_there_are_some():
    start = _active_partners()
    body = _landing()
    if start:
        assert _expected_line(start) in body
    else:
        assert "reviewing applications" not in body

    _partner("Gigmile")
    assert _expected_line(start + 1) in _landing()

    _partner("Moove")
    assert _expected_line(start + 2) in _landing()


def test_an_inactive_partner_is_not_counted():
    start = _active_partners()
    _partner("Retired Co", active=False)
    body = _landing()
    if start:
        assert _expected_line(start) in body
    else:
        assert "reviewing applications" not in body
