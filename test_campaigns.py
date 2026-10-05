"""
In-app campaign cards: who sees one, how often, and when it stops.

The targeting is the feature. A card shown to someone who signed up yesterday
is noise; one that keeps coming back after they did what it asked is worse. So
these tests pin the rules rather than the copy: qualification, the frequency
cap, the snooze, the goal that ends it, and the quiet delivery through the bell
that reaches people who never open the dashboard.
"""
import os
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-campaigns-0000000000000")
ADMIN_PHONE = "2348090055000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

import campaigns as camp
import feature_flags
import web_auth
from database import SessionLocal
from main import app
from models import (
    AppNotification, Campaign, CampaignView, Customer, SiteSetting, Testimonial,
    Transaction, User, utcnow,
)

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 900))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    monkeypatch.delenv("WHATSAPP_LIVE", raising=False)
    db = SessionLocal()
    try:
        db.query(CampaignView).delete()
        db.query(Campaign).delete()
        db.query(SiteSetting).delete()
        db.commit()
    finally:
        db.close()
    feature_flags.clear_cache()
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(entries=0, days_old=40, plan="BASIC"):
    """A business with a history, as the targeting rules expect to find one."""
    phone = f"23480900551{next(_seq)}"
    db = SessionLocal()
    try:
        user = User(phone=phone, name=f"Shop {phone[-3:]}", subscription_plan=plan)
        user.created_at = utcnow() - timedelta(days=days_old)
        db.add(user)
        db.flush()
        customer = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(customer)
        db.flush()
        for i in range(entries):
            db.add(Transaction(customer_id=customer.id, type="SALE", amount=5_000,
                               recorded_by_id=user.id,
                               created_at=utcnow() - timedelta(days=1)))
        db.commit()
        return phone
    finally:
        db.close()


def _campaign(**over):
    body = dict(
        key="review-ask", title="Your shop, on our homepage",
        body="Tell other owners what CreditVoice does for you.",
        cta_label="Write my review", cta_link="/profile", goal="review",
        owners_only=True, min_transactions=30, min_days_active=14,
        is_active=True, max_shows=3, snooze_days=14, priority=10,
    )
    body.update(over)
    db = SessionLocal()
    try:
        row = Campaign(**body)
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _user(phone):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.phone == phone).first()
    finally:
        db.close()


def _next_for(phone):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        return camp.next_for_user(db, user)
    finally:
        db.close()


# ── Who qualifies ────────────────────────────────────────────────────────────

def test_a_business_that_has_used_the_app_sees_the_card():
    _campaign()
    phone = _owner(entries=40, days_old=30)
    assert _next_for(phone) is not None


def test_a_brand_new_account_is_left_alone():
    _campaign()
    assert _next_for(_owner(entries=40, days_old=2)) is None       # too new
    assert _next_for(_owner(entries=3, days_old=60)) is None       # barely used


def test_staff_are_not_asked_to_speak_for_the_business():
    _campaign()
    owner_phone = _owner(entries=40, days_old=30)
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == owner_phone).first()
        staff = User(phone="2348090055901", name="Staff", parent_id=owner.id)
        staff.created_at = utcnow() - timedelta(days=30)
        db.add(staff)
        db.commit()
        assert camp.next_for_user(db, staff) is None
    finally:
        db.close()


def test_a_plan_filter_is_respected():
    _campaign(plans="GO,PRO", min_transactions=0, min_days_active=0, goal=None)
    assert _next_for(_owner(plan="BASIC")) is None
    assert _next_for(_owner(plan="GO")) is not None


def test_a_paused_or_expired_campaign_shows_nothing():
    cid = _campaign(is_active=False)
    phone = _owner(entries=40, days_old=30)
    assert _next_for(phone) is None

    db = SessionLocal()
    try:
        row = db.query(Campaign).filter(Campaign.id == cid).first()
        row.is_active = True
        row.ends_at = utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    assert _next_for(phone) is None


def test_only_one_card_at_a_time_and_priority_decides():
    _campaign(key="low", priority=1, goal=None, min_transactions=0, min_days_active=0)
    _campaign(key="high", priority=99, goal=None, min_transactions=0, min_days_active=0)
    assert _next_for(_owner()).key == "high"


# ── How often ────────────────────────────────────────────────────────────────

def test_it_stops_after_the_allowed_number_of_shows():
    _campaign(max_shows=2, goal=None)
    phone = _owner(entries=40, days_old=30)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        for _ in range(2):
            card = camp.next_for_user(db, user)
            assert card is not None
            camp.mark_shown(db, card, user)
        assert camp.next_for_user(db, user) is None
    finally:
        db.close()


def test_closing_it_buys_quiet_but_not_silence_forever():
    _campaign(max_shows=5, snooze_days=14, goal=None)
    phone = _owner(entries=40, days_old=30)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        card = camp.next_for_user(db, user)
        camp.mark_shown(db, card, user)
        camp.mark_dismissed(db, card, user)
        assert camp.next_for_user(db, user) is None

        later = utcnow() + timedelta(days=15)
        assert camp.next_for_user(db, user, now=later) is not None
    finally:
        db.close()


# ── When it stops for good ───────────────────────────────────────────────────

def test_writing_the_review_ends_the_campaign_that_asked_for_it():
    _campaign(goal="review")
    phone = _owner(entries=40, days_old=30)
    assert _next_for(phone) is not None

    db = SessionLocal()
    try:
        db.add(Testimonial(owner_phone=phone, business_name="Shop",
                           quote="It works.", consent_public=True))
        db.commit()
    finally:
        db.close()
    assert _next_for(phone) is None


def test_leaving_the_free_plan_ends_the_upgrade_campaign():
    _campaign(key="upgrade", goal="upgrade", min_transactions=0, min_days_active=0)
    phone = _owner(plan="BASIC")
    assert _next_for(phone) is not None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        user.subscription_plan = "GO"
        db.commit()
    finally:
        db.close()
    assert _next_for(phone) is None


# ── The quiet channel ────────────────────────────────────────────────────────

def test_the_bell_reaches_people_who_never_open_the_dashboard():
    _campaign(also_notify=True, goal=None)
    phone = _owner(entries=40, days_old=30)

    db = SessionLocal()
    try:
        sent = camp.deliver_notifications(db)
        assert sent
        note = (db.query(AppNotification)
                .filter(AppNotification.owner_phone == phone,
                        AppNotification.event_type == "campaign").first())
        assert note is not None
        assert note.link == "/profile"          # the card's button, in the bell

        # Told once, not every cycle.
        camp.deliver_notifications(db)
        assert db.query(AppNotification).filter(
            AppNotification.owner_phone == phone,
            AppNotification.event_type == "campaign").count() == 1
    finally:
        db.close()


def test_nobody_is_notified_who_would_not_see_the_card():
    _campaign(also_notify=True)
    too_new = _owner(entries=40, days_old=1)
    db = SessionLocal()
    try:
        camp.deliver_notifications(db)
        assert db.query(AppNotification).filter(
            AppNotification.owner_phone == too_new).count() == 0
    finally:
        db.close()


def test_whatsapp_is_not_attempted_until_meta_approves(monkeypatch):
    _campaign(also_notify=True, also_whatsapp=True, goal=None)
    _owner(entries=40, days_old=30)
    calls = []
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda *a, **k: calls.append(a) or True)
    db = SessionLocal()
    try:
        camp.deliver_notifications(db)
    finally:
        db.close()
    assert calls == []


# ── The API the app and the admin screen use ─────────────────────────────────

def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_the_app_is_told_what_to_draw_and_nothing_more():
    _campaign(min_transactions=0, min_days_active=0, goal=None)
    cookies = _register("2348090055801", "Fresh Shop")
    r = client.get("/app/api/campaigns/next", cookies=cookies)
    assert r.status_code == 200, r.text
    card = r.json()["campaign"]
    assert card["title"] and card["cta_link"] == "/profile"
    # Targeting rules are not the app's business.
    for hidden in ("min_transactions", "plans", "max_shows", "priority"):
        assert hidden not in card


def test_asking_for_the_card_counts_as_a_show():
    cid = _campaign(min_transactions=0, min_days_active=0, goal=None, max_shows=1)
    cookies = _register("2348090055802", "Counted Shop")
    assert client.get("/app/api/campaigns/next", cookies=cookies).json()["campaign"]
    assert client.get("/app/api/campaigns/next", cookies=cookies).json()["campaign"] is None

    db = SessionLocal()
    try:
        view = db.query(CampaignView).filter(CampaignView.campaign_id == cid).first()
        assert view.shown_count == 1
    finally:
        db.close()


def test_dismissing_and_clicking_are_recorded():
    cid = _campaign(min_transactions=0, min_days_active=0, goal=None)
    cookies = _register("2348090055803", "Acting Shop")
    client.get("/app/api/campaigns/next", cookies=cookies)
    assert client.post(f"/app/api/campaigns/{cid}/clicked", cookies=cookies).status_code == 200
    assert client.post(f"/app/api/campaigns/{cid}/dismissed", cookies=cookies).status_code == 200
    assert client.post(f"/app/api/campaigns/{cid}/nonsense", cookies=cookies).status_code == 404

    db = SessionLocal()
    try:
        view = db.query(CampaignView).filter(CampaignView.campaign_id == cid).first()
        assert view.clicked_at and view.dismissed_at and view.snooze_until
    finally:
        db.close()


def test_admin_only_and_the_counts_are_reported():
    cid = _campaign(min_transactions=0, min_days_active=0, goal=None)
    owner = _register("2348090055804", "Nosy Shop")
    assert client.get("/app/api/admin/campaigns", cookies=owner).status_code == 403

    client.get("/app/api/campaigns/next", cookies=owner)
    client.post(f"/app/api/campaigns/{cid}/clicked", cookies=owner)

    admin = _register(ADMIN_PHONE, "App Admin")
    rows = client.get("/app/api/admin/campaigns", cookies=admin).json()["campaigns"]
    row = next(r for r in rows if r["id"] == cid)
    assert row["stats"]["shows"] >= 1
    assert row["stats"]["clicked"] == 1
    assert row["stats"]["people"] >= 1


def test_a_bad_button_link_is_refused():
    admin = _register(ADMIN_PHONE, "App Admin")
    body = {"title": "Hi", "body": "There", "cta_link": "profile"}
    r = client.post("/app/api/admin/campaigns", cookies=admin, json=body)
    assert r.status_code == 400
    assert "in-app path" in r.json()["detail"]

    body["cta_link"] = "/profile"
    assert client.post("/app/api/admin/campaigns", cookies=admin, json=body).status_code == 200
