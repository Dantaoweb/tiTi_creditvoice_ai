"""
Reviews written by businesses, and the admin-editable public-site settings.

Two things matter here. A review carries a real phone number onto a page anyone
can read, so it must not appear without both the owner's consent and an admin's
approval — and an edit after approval must go back for approval. The other is
that prices, reviews and social links reach the landing page from settings, not
from the HTML file, so they can change without a deploy.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-site-reviews-0000000000")
ADMIN_PHONE = "2348090022000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

import main
import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, SiteSetting, Testimonial

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    db = SessionLocal()
    try:
        db.query(Testimonial).delete()
        db.query(SiteSetting).delete()
        db.commit()
    finally:
        db.close()
    # The landing page caches its database blocks; tests must see their own data.
    main._LANDING_CACHE["blocks"] = None
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    main._LANDING_CACHE["blocks"] = None
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


@pytest.fixture
def admin():
    return _register(ADMIN_PHONE, "App Admin")


@pytest.fixture
def owner():
    return _register("2348090022101", "Ade Stores")


REVIEW = {
    "business_name": "Ade Stores",
    "business_type": "Provisions shop",
    "location": "Osogbo, Osun",
    "quote": "I now know who owes me without checking my book.",
    "contact_phone": "0803 111 2222",
    "consent_public": True,
}


def _write(owner, **over):
    body = dict(REVIEW)
    body.update(over)
    return client.post("/app/api/my-review", cookies=owner, json=body)


def _feature(admin, review_id):
    client.patch(f"/app/api/admin/reviews/{review_id}", cookies=admin, json={"status": "APPROVED"})
    return client.patch(f"/app/api/admin/reviews/{review_id}", cookies=admin,
                        json={"is_featured": True})


# ── Writing a review ─────────────────────────────────────────────────────────

def test_review_starts_pending_and_is_not_public(owner):
    r = _write(owner)
    assert r.status_code == 200, r.text
    assert r.json()["review"]["status"] == "PENDING"
    assert r.json()["review"]["is_featured"] is False
    assert REVIEW["quote"] not in client.get("/").text


def test_consent_is_required(owner):
    r = _write(owner, consent_public=False)
    assert r.status_code == 400
    assert "publicly" in r.json()["detail"]


def test_empty_quote_rejected(owner):
    assert _write(owner, quote="   ").status_code == 400


def test_contact_link_must_be_a_url(owner):
    assert _write(owner, contact_link="ade-stores.ng").status_code == 400
    assert _write(owner, contact_link="https://ade-stores.ng").status_code == 200


def test_rewriting_replaces_rather_than_piling_up(owner):
    _write(owner)
    _write(owner, quote="Second try at saying it.")
    rows = client.get("/app/api/my-review", cookies=owner).json()["review"]
    assert rows["quote"] == "Second try at saying it."
    db = SessionLocal()
    try:
        assert db.query(Testimonial).count() == 1
    finally:
        db.close()


def test_owner_can_withdraw(owner, admin):
    rid = _write(owner).json()["review"]["id"]
    _feature(admin, rid)
    main._LANDING_CACHE["blocks"] = None
    assert REVIEW["quote"] in client.get("/").text

    assert client.delete("/app/api/my-review", cookies=owner).json()["deleted"] == 1
    assert client.get("/app/api/my-review", cookies=owner).json()["review"] is None
    main._LANDING_CACHE["blocks"] = None
    assert REVIEW["quote"] not in client.get("/").text


# ── Moderation ───────────────────────────────────────────────────────────────

def test_the_admins_are_told_when_a_review_arrives(owner, admin):
    """A review nobody is told about sits unapproved for weeks."""
    db = SessionLocal()
    try:
        db.query(AppNotification).filter(
            AppNotification.owner_phone == ADMIN_PHONE).delete()
        db.commit()
    finally:
        db.close()

    _write(owner)

    db = SessionLocal()
    try:
        note = (db.query(AppNotification)
                .filter(AppNotification.owner_phone == ADMIN_PHONE,
                        AppNotification.event_type == "review")
                .order_by(AppNotification.created_at.desc()).first())
        assert note is not None
        assert "Ade Stores" in note.body
        assert REVIEW["quote"][:30] in note.body      # what they actually said
        assert note.link == "/admin"                  # one tap to go and approve
    finally:
        db.close()


def test_a_failed_notification_does_not_lose_the_review(owner, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("bell is broken")
    monkeypatch.setattr("web_common._add_notification", boom)
    assert _write(owner).status_code == 200
    assert client.get("/app/api/my-review", cookies=owner).json()["review"] is not None


def test_the_waiting_count_is_what_an_admin_is_chasing(owner, admin):
    db = SessionLocal()
    try:
        db.query(Testimonial).delete()
        db.commit()
    finally:
        db.close()

    assert client.get("/app/api/admin/pending-counts",
                      cookies=admin).json()["reviews"] == 0

    review_id = _write(owner).json()["review"]["id"]
    assert client.get("/app/api/admin/pending-counts",
                      cookies=admin).json()["reviews"] == 1

    # It clears when the work is done, not when the page is opened.
    client.patch(f"/app/api/admin/reviews/{review_id}", cookies=admin,
                 json={"status": "APPROVED"})
    assert client.get("/app/api/admin/pending-counts",
                      cookies=admin).json()["reviews"] == 0


def test_the_count_tells_a_non_admin_nothing(owner):
    _write(owner)
    r = client.get("/app/api/admin/pending-counts", cookies=owner)
    assert r.status_code == 200          # quiet, not an error — the menu asks often
    assert r.json()["reviews"] == 0


def test_featuring_requires_approval_first(owner, admin):
    rid = _write(owner).json()["review"]["id"]
    r = client.patch(f"/app/api/admin/reviews/{rid}", cookies=admin, json={"is_featured": True})
    assert r.status_code == 400
    assert "Approve" in r.json()["detail"]


def test_admin_only(owner):
    rid = _write(owner).json()["review"]["id"]
    assert client.get("/app/api/admin/reviews", cookies=owner).status_code == 403
    assert client.patch(f"/app/api/admin/reviews/{rid}", cookies=owner,
                        json={"status": "APPROVED"}).status_code == 403


def test_approved_and_featured_review_shows_on_landing_page(owner, admin):
    rid = _write(owner).json()["review"]["id"]
    _feature(admin, rid)
    main._LANDING_CACHE["blocks"] = None
    body = client.get("/").text
    assert REVIEW["quote"] in body
    assert "Ade Stores" in body
    assert "Osogbo, Osun" in body
    # The free-advert part: their own number, dialable.
    assert "0803 111 2222" in body
    assert 'href="tel:08031112222"' in body


def test_editing_an_approved_review_sends_it_back_for_approval(owner, admin):
    rid = _write(owner).json()["review"]["id"]
    _feature(admin, rid)
    after = _write(owner, quote="Changed my words after approval.").json()["review"]
    assert after["status"] == "PENDING"
    assert after["is_featured"] is False
    main._LANDING_CACHE["blocks"] = None
    assert "Changed my words after approval." not in client.get("/").text


def test_rejecting_unfeatures(owner, admin):
    rid = _write(owner).json()["review"]["id"]
    _feature(admin, rid)
    r = client.patch(f"/app/api/admin/reviews/{rid}", cookies=admin, json={"status": "REJECTED"})
    assert r.json()["is_featured"] is False
    main._LANDING_CACHE["blocks"] = None
    assert REVIEW["quote"] not in client.get("/").text


def test_review_markup_is_escaped(owner, admin):
    rid = _write(owner, quote="<script>alert(1)</script> good app").json()["review"]["id"]
    _feature(admin, rid)
    main._LANDING_CACHE["blocks"] = None
    body = client.get("/").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_featured_count_is_a_setting(owner, admin):
    for i, phone in enumerate(["2348090022201", "2348090022202", "2348090022203"]):
        cookies = _register(phone, f"Shop {i}")
        rid = _write(cookies, business_name=f"Shop {i}", quote=f"Words number {i}.").json()["review"]["id"]
        _feature(admin, rid)

    main._LANDING_CACHE["blocks"] = None
    body = client.get("/").text
    assert all(f"Words number {i}." in body for i in range(3))

    client.post("/app/api/admin/site-settings", cookies=admin, json={"settings": {"featured_reviews": "1"}})
    main._LANDING_CACHE["blocks"] = None
    body = client.get("/").text
    assert sum(f"Words number {i}." in body for i in range(3)) == 1


def test_no_reviews_invites_one_instead_of_inventing_words():
    body = client.get("/").text
    assert "Write yours" in body


# ── Site settings ────────────────────────────────────────────────────────────

def test_social_links_come_from_settings(admin):
    r = client.post("/app/api/admin/site-settings", cookies=admin, json={"settings": {
        "facebook_url": "https://facebook.com/creditvoiceai",
        "instagram_url": "https://instagram.com/creditvoiceai",
        "tiktok_url": "https://tiktok.com/@creditvoiceai",
    }})
    assert r.status_code == 200, r.text
    main._LANDING_CACHE["blocks"] = None
    body = client.get("/").text
    assert 'href="https://facebook.com/creditvoiceai"' in body
    assert 'href="https://instagram.com/creditvoiceai"' in body
    assert 'href="https://tiktok.com/@creditvoiceai"' in body
    assert 'aria-label="TikTok"' in body


def test_social_url_must_be_absolute(admin):
    r = client.post("/app/api/admin/site-settings", cookies=admin,
                    json={"settings": {"facebook_url": "facebook.com/creditvoiceai"}})
    assert r.status_code == 400
    assert "http" in r.json()["detail"]


def test_unknown_settings_are_ignored(admin):
    r = client.post("/app/api/admin/site-settings", cookies=admin,
                    json={"settings": {"nonsense_key": "x"}})
    assert r.status_code == 200
    assert "nonsense_key" not in r.json()["settings"]


def test_settings_admin_only(owner):
    assert client.get("/app/api/admin/site-settings", cookies=owner).status_code == 403
    assert client.post("/app/api/admin/site-settings", cookies=owner,
                       json={"settings": {}}).status_code == 403


# ── Prices on the page are the prices the app charges ────────────────────────

def test_prices_are_injected_not_hardcoded():
    from messages import get_plan_price
    from plans import PLAN_GO, PLAN_PREMIUM, PLAN_PRO

    body = client.get("/").text
    for plan in (PLAN_GO, PLAN_PRO, PLAN_PREMIUM):
        assert f"&#8358;{get_plan_price(plan):,}" in body or f"₦{get_plan_price(plan):,}" in body
    assert "Basic" in body and "Free" in body


def test_price_change_follows_the_env_var(monkeypatch):
    monkeypatch.setenv("PLAN_GO_PRICE", "4500")
    main._LANDING_CACHE["blocks"] = None
    assert "₦4,500" in client.get("/").text


def test_no_placeholders_left_in_the_served_page():
    import re
    body = client.get("/").text
    assert re.findall(r"<!--[A-Z_]+-->", body) == []
