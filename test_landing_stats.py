"""
The numbers on the homepage, and the yearly price switch.

Both exist because of what the competition gets wrong. Bumpa's homepage ships
"Trusted by over 0 SMEs" — their counter only runs in JavaScript, so crawlers,
link previews and slow phones see a zero. Ours is counted on the server and
printed into the HTML, and a figure that would read as zero is left out rather
than shown. The price switch is a checkbox the CSS reads, for the same reason:
no JavaScript, no empty page.
"""
import os
import re

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-landing-stats-00000000")
ADMIN_PHONE = "2348090044000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

import main
import web_site_routes as site
from database import SessionLocal
from main import app
from models import Customer, SiteSetting, Transaction, User

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    db = SessionLocal()
    try:
        db.query(SiteSetting).delete()
        db.commit()
    finally:
        db.close()
    main._LANDING_CACHE["blocks"] = None
    yield
    main._LANDING_CACHE["blocks"] = None


def _landing():
    main._LANDING_CACHE["blocks"] = None
    return client.get("/").text


# ── Formatting: a trader reads these at a glance ─────────────────────────────

@pytest.mark.parametrize("amount,shown", [
    (0, "₦0"), (5_200, "₦5,200"), (99_999, "₦99,999"),
    (340_000, "₦340k"), (3_100_000, "₦3.1m"), (2_000_000, "₦2m"),
    (2_400_000_000, "₦2.4b"),
])
def test_money_is_compact(amount, shown):
    assert site._compact_money(amount) == shown


@pytest.mark.parametrize("n,shown", [
    (0, "0"), (248, "248"), (1_706, "1,706"), (12_400, "12k"), (2_300_000, "2.3m"),
])
def test_counts_are_compact(n, shown):
    assert site._compact_count(n) == shown


# ── The figures are real ─────────────────────────────────────────────────────

def test_the_numbers_are_counted_from_the_database():
    db = SessionLocal()
    try:
        before = site._stats(db)
        db.add(User(phone="2348090044101", name="Counted Shop"))
        db.add(Transaction(type="SALE", amount=25_000))
        db.add(Customer(owner_phone="2348090044101", name="Owing", balance=40_000))
        db.commit()
        after = site._stats(db)
    finally:
        db.close()
    assert after["businesses"] == before["businesses"] + 1
    assert after["records"] == before["records"] + 1
    assert after["credit_tracked"] == before["credit_tracked"] + 40_000


def test_staff_accounts_are_not_counted_as_businesses():
    db = SessionLocal()
    try:
        owner = User(phone="2348090044102", name="Owner")
        db.add(owner)
        db.commit()
        before = site._stats(db)["businesses"]
        db.add(User(phone="2348090044103", name="Staff", parent_id=owner.id))
        db.commit()
        assert site._stats(db)["businesses"] == before
    finally:
        db.close()


def test_the_figure_is_in_the_html_not_only_in_a_script():
    """The Bumpa failure: a number that only exists once JavaScript runs."""
    db = SessionLocal()
    try:
        db.add(User(phone="2348090044104", name="Visible Shop"))
        db.commit()
        expected = site._compact_count(
            db.query(func.count(User.id)).filter(User.parent_id.is_(None)).scalar()
        )
    finally:
        db.close()

    body = _landing()
    assert f'data-to="{expected}">{expected}</span>' in body
    assert "businesses keeping their records" in body
    # Nothing on the page reads as zero.
    assert not re.search(r'class="stat-n"[^>]*>0<', body)


def test_a_zero_figure_is_left_out_rather_than_shown(monkeypatch):
    monkeypatch.setattr(site, "_stats", lambda db: {
        "businesses": 12, "records": 0, "credit_tracked": 0,
    })
    body = _landing()
    assert "businesses keeping their records" in body
    assert "sales and payments recorded" not in body
    assert "in customer credit being tracked" not in body


def test_an_empty_platform_shows_no_band_at_all(monkeypatch):
    monkeypatch.setattr(site, "_stats", lambda db: {
        "businesses": 0, "records": 0, "credit_tracked": 0,
    })
    body = _landing()
    assert 'class="stat-n"' not in body
    assert "<!--STATS-->" not in body          # the slot was still filled


def test_a_failed_count_does_not_break_the_page(monkeypatch):
    def boom(db):
        raise RuntimeError("count timed out")
    monkeypatch.setattr(site, "_stats", boom)
    body = _landing()
    assert 'class="stat-n"' not in body
    assert "Know" in body and "<h1" in body


def test_admin_can_hide_the_band():
    admin_cookies = client.post("/app/api/auth/register",
                                json={"name": "App Admin", "phone": ADMIN_PHONE, "pin": "5678"}) and \
        client.post("/app/api/auth/login", json={"phone": ADMIN_PHONE, "pin": "5678"}).cookies
    assert 'class="stat-n"' in _landing()
    r = client.post("/app/api/admin/site-settings", cookies=admin_cookies,
                    json={"settings": {"show_stats": "no"}})
    assert r.status_code == 200, r.text
    assert 'class="stat-n"' not in _landing()


# ── Pricing switch ───────────────────────────────────────────────────────────

def test_both_prices_are_rendered_so_the_switch_needs_no_javascript():
    from messages import get_plan_price
    from plans import PLAN_GO

    body = _landing()
    assert f"₦{get_plan_price(PLAN_GO):,}<small> /month</small>" in body
    assert f"₦{get_plan_price(PLAN_GO, 'YEARLY'):,}<small> /year</small>" in body
    assert 'type="checkbox" id="yearly-toggle"' in body
    assert "Two months free" in body


def test_the_yearly_price_is_two_months_free():
    from messages import get_plan_price
    from plans import PLAN_GO, PLAN_PREMIUM, PLAN_PRO

    for plan in (PLAN_GO, PLAN_PRO, PLAN_PREMIUM):
        assert get_plan_price(plan, "YEARLY") == get_plan_price(plan) * 10
