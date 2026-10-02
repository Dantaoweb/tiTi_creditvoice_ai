"""
/resources and /events: public, crawlable, admin-editable.

The point of these pages is that a search engine can read them — the app sits
behind a login, so a link there is worth nothing to a partner or to us. How each
link is marked is the other thing that matters: paid or exchanged links must not
pass authority.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-public-pages-00000000000")
ADMIN_PHONE = "2348090011000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import PublicListing, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 3000))


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    db = SessionLocal()
    try:
        db.query(PublicListing).delete()
        db.commit()
    finally:
        db.close()
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


@pytest.fixture
def admin():
    return _register(ADMIN_PHONE, "App Admin")


def _add(admin, **over):
    body = {"page": "resources", "title": "A Thing", "url": "https://example.com",
            "blurb": "Short write up.", "link_rel": "EDITORIAL", "sort_order": 0,
            "is_active": True}
    body.update(over)
    r = client.post("/app/api/admin/public-listings", cookies=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── The pages are real HTML, crawlable, with the right head ──────────────────

def test_resources_page_is_server_rendered_and_indexable():
    r = client.get("/resources")
    assert r.status_code == 200
    body = r.text
    assert "<h1>Resources &amp; sponsors</h1>" in body
    assert 'name="robots" content="index, follow"' in body
    assert '<link rel="canonical" href="https://creditvoiceai.com/resources" />' in body
    assert "Nothing listed yet" in body          # empty is honest, not broken


def test_the_content_is_in_the_html_not_fetched_by_javascript(admin):
    _add(admin, title="Investorlist.com",
         blurb="Downloadable, curated lists of active startup investors, angels, VCs and family offices.",
         url="https://www.investorlist.com", link_rel="SPONSORED", section="Sponsors")
    body = client.get("/resources").text
    # A crawler sees the link and the write-up without running any script.
    assert "Investorlist.com" in body
    assert "family offices" in body
    assert "https://www.investorlist.com" in body
    assert "<h2>Sponsors</h2>" in body


# ── How links are marked ─────────────────────────────────────────────────────

def test_a_sponsor_link_is_marked_sponsored_and_an_editorial_one_is_not(admin):
    _add(admin, title="Paid Partner", url="https://paid.example", link_rel="SPONSORED",
         section="Sponsors")
    _add(admin, title="We Rate This", url="https://good.example", link_rel="EDITORIAL",
         section="Resources", sort_order=1)
    _add(admin, title="Just Listed", url="https://meh.example", link_rel="NOFOLLOW",
         section="Resources", sort_order=2)
    body = client.get("/resources").text

    paid = next(line for line in body.splitlines() if "paid.example" in line) \
        if "\n" in body else body
    assert 'href="https://paid.example" rel="noopener sponsored nofollow"' in body
    assert 'href="https://good.example" rel="noopener"' in body      # dofollow
    assert 'href="https://meh.example" rel="noopener nofollow"' in body
    # And it says so on the page, so a reader isn't misled.
    assert "sponsored" in body.lower()


def test_an_unknown_link_marking_is_refused(admin):
    r = client.post("/app/api/admin/public-listings", cookies=admin, json={
        "page": "resources", "title": "X", "url": "https://x.example", "link_rel": "DOFOLLOW"})
    assert r.status_code == 400 and "link_rel" in r.json()["detail"]


def test_a_bad_url_or_page_is_refused(admin):
    assert client.post("/app/api/admin/public-listings", cookies=admin, json={
        "page": "resources", "title": "X", "url": "javascript:alert(1)"}).status_code == 400
    assert client.post("/app/api/admin/public-listings", cookies=admin, json={
        "page": "nowhere", "title": "X"}).status_code == 400


def test_admin_typed_markup_cannot_reach_the_page(admin):
    _add(admin, title="<script>alert(1)</script>", blurb="<b>bold</b>", url=None)
    body = client.get("/resources").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    assert "<b>bold</b>" not in body


# ── Events ───────────────────────────────────────────────────────────────────

def test_events_split_into_coming_up_and_past(admin):
    soon = (utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")
    gone = (utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    _add(admin, page="events", title="Osogbo Traders Workshop", event_date=soon,
         event_venue="Osogbo", url="https://example.com/register")
    _add(admin, page="events", title="Last Year Meetup", event_date=gone, event_venue="Lagos",
         url=None)

    body = client.get("/events").text
    assert "<h2>Coming up</h2>" in body and "<h2>Past events</h2>" in body
    assert body.index("Coming up") < body.index("Past events")
    assert "Osogbo Traders Workshop" in body and "Osogbo" in body
    # A registration link where there is one; no empty link where there isn't.
    assert 'href="https://example.com/register"' in body
    assert "Last Year Meetup" in body
    # Structured data so the date can show in search results.
    assert '"@type": "Event"' in body and '"startDate"' in body


def test_an_event_without_a_link_still_lists(admin):
    _add(admin, page="events", title="Walk-in clinic", url=None,
         event_date=(utcnow() + timedelta(days=3)).strftime("%Y-%m-%d"))
    body = client.get("/events").text
    assert "Walk-in clinic" in body
    assert "<h3>Walk-in clinic</h3>" in body     # plain text, not a broken anchor


def test_a_bad_event_date_is_refused(admin):
    r = client.post("/app/api/admin/public-listings", cookies=admin, json={
        "page": "events", "title": "X", "event_date": "soon"})
    assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["detail"]


# ── Admin control ────────────────────────────────────────────────────────────

def test_entries_can_be_edited_reordered_hidden_and_deleted(admin):
    first = _add(admin, title="Second", sort_order=2)
    second = _add(admin, title="First", sort_order=1)
    body = client.get("/resources").text
    assert body.index("First") < body.index("Second")      # sort order respected

    hidden = client.put(f"/app/api/admin/public-listings/{first['id']}", cookies=admin, json={
        "page": "resources", "title": "Second", "url": "https://example.com",
        "link_rel": "EDITORIAL", "is_active": False})
    assert hidden.status_code == 200
    assert "Second" not in client.get("/resources").text

    assert client.delete(f"/app/api/admin/public-listings/{second['id']}",
                         cookies=admin).status_code == 200
    assert "First" not in client.get("/resources").text


def test_sections_are_free_text_so_new_groupings_need_no_code(admin):
    _add(admin, section="Tools we like", title="Tool A")
    _add(admin, section="Communities", title="Group B", sort_order=1)
    body = client.get("/resources").text
    assert "<h2>Tools we like</h2>" in body and "<h2>Communities</h2>" in body


def test_only_admins_can_change_what_the_public_sees():
    _phone = f"234867{next(_seq):06d}"
    cook = _register(_phone, "Ordinary Business")
    assert client.get("/app/api/admin/public-listings", cookies=cook).status_code == 403
    assert client.post("/app/api/admin/public-listings", cookies=cook,
                       json={"page": "resources", "title": "Mine"}).status_code == 403
    # …but anyone, logged in or not, can read the pages.
    assert client.get("/resources").status_code == 200
    assert client.get("/events").status_code == 200
