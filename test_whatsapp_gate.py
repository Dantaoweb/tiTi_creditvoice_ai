"""
WhatsApp is built but not yet approved by Meta.

Until it is, nothing may promise it and nothing may try to deliver through it:
the homepage says "coming soon", the buttons and the footer icon are gone, and a
login code goes by email, because a code sent to an unapproved number never
arrives and the person is simply locked out. One switch decides all of it.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-whatsapp-gate-000000000")
ADMIN_PHONE = "2348090033000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
os.environ["TITI_WHATSAPP"] = "2347048101876"

import pytest
from fastapi.testclient import TestClient

import feature_flags
import main
import web_auth
from database import SessionLocal
from main import app
from models import SiteSetting, User

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    monkeypatch.delenv("WHATSAPP_LIVE", raising=False)
    db = SessionLocal()
    try:
        db.query(SiteSetting).delete()
        db.commit()
    finally:
        db.close()
    feature_flags.clear_cache()
    main._LANDING_CACHE["blocks"] = None
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    feature_flags.clear_cache()
    main._LANDING_CACHE["blocks"] = None
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register(phone, name="Shop", **extra):
    body = {"name": name, "phone": phone, "pin": "5678"}
    body.update(extra)
    client.post("/app/api/auth/register", json=body)
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _go_live():
    """Turn it on the way an admin would, through the setting."""
    db = SessionLocal()
    try:
        db.add(SiteSetting(key="whatsapp_live", value="yes"))
        db.commit()
    finally:
        db.close()
    feature_flags.clear_cache()
    main._LANDING_CACHE["blocks"] = None


# ── The homepage ─────────────────────────────────────────────────────────────

def test_homepage_says_coming_soon_and_promises_nothing():
    body = client.get("/").text
    assert "coming soon" in body.lower()
    assert "Message tiTi on WhatsApp" not in body
    assert "Works on WhatsApp" not in body
    assert "wa.me" not in body                     # no link, not even in the footer
    assert 'aria-label="WhatsApp"' not in body     # the footer icon is gone
    # The structured data must not advertise it either.
    assert '"operatingSystem": "Web, Android"' in body
    assert "WhatsApp" not in body.split('"FAQPage"')[1].split("</script>")[0]


def test_homepage_still_reads_as_finished_english():
    body = client.get("/").text
    assert "Works in any phone browser" in body
    assert "Open the web app in your browser" in body
    assert "<!--WA_" not in body                   # every slot was filled


def test_paid_plans_do_not_sell_a_reminder_we_cannot_send():
    body = client.get("/").text
    assert "Reminders sent for you" not in body
    assert "Due dates and who to chase" in body

    _go_live()
    body = client.get("/").text
    assert "Reminders sent for you" in body


def test_homepage_promises_whatsapp_once_it_is_live():
    _go_live()
    body = client.get("/").text
    assert "Message tiTi on WhatsApp" in body
    assert "https://wa.me/2347048101876" in body
    assert "Works on WhatsApp" in body
    assert 'aria-label="WhatsApp"' in body
    assert '"operatingSystem": "Web, Android, WhatsApp"' in body
    assert "coming soon" not in body.lower()


def test_env_var_pins_it_regardless_of_the_setting(monkeypatch):
    _go_live()
    monkeypatch.setenv("WHATSAPP_LIVE", "0")
    feature_flags.clear_cache()
    main._LANDING_CACHE["blocks"] = None
    assert "Message tiTi on WhatsApp" not in client.get("/").text


def test_a_broken_database_does_not_make_the_page_promise_it(monkeypatch):
    def boom():
        raise RuntimeError("database is down")
    monkeypatch.setattr("web_site_routes.SessionLocal", boom)
    main._LANDING_CACHE["blocks"] = None
    body = client.get("/").text
    assert body.count("<!--WA_") == 0
    assert "Message tiTi on WhatsApp" not in body


# ── What the app tells its own screens ───────────────────────────────────────

def test_config_withholds_the_number_until_it_is_live():
    cfg = client.get("/app/api/auth/config").json()
    assert cfg["whatsapp_live"] is False
    assert cfg["titi_whatsapp"] == ""          # so no screen can build a wa.me link

    _go_live()
    cfg = client.get("/app/api/auth/config").json()
    assert cfg["whatsapp_live"] is True
    assert cfg["titi_whatsapp"] == "2347048101876"


# ── Login codes: the part that locks people out ──────────────────────────────

def test_whatsapp_is_not_offered_as_a_code_channel():
    phone = "2348090033101"
    _register(phone)
    r = client.get("/app/api/auth/otp-channels", params={"phone": phone})
    assert r.status_code == 200, r.text
    assert r.json()["has_whatsapp"] is False

    _go_live()
    assert client.get("/app/api/auth/otp-channels", params={"phone": phone}).json()["has_whatsapp"] is True


def test_a_user_without_an_email_is_told_to_add_one_not_left_waiting():
    phone = "2348090033102"
    _register(phone)
    r = client.post("/app/api/auth/request-otp", json={"phone": phone})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "email" in detail.lower()
    # Not a 500 blaming delivery, and no suggestion to message tiTi first.
    assert "24 hours" not in detail


def test_an_email_given_at_the_time_is_used(monkeypatch):
    phone = "2348090033103"
    _register(phone)
    sent = {}
    monkeypatch.setattr("email_service.send_otp_email",
                        lambda to, code: sent.update(to=to, code=code) or True)
    r = client.post("/app/api/auth/request-otp",
                    json={"phone": phone, "email": "owner@example.com"})
    assert r.status_code == 200, r.text
    assert sent["to"] == "owner@example.com"

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.phone == phone).first().email == "owner@example.com"
    finally:
        db.close()


def test_nothing_is_sent_to_whatsapp_while_it_is_off(monkeypatch):
    phone = "2348090033104"
    _register(phone, email="has@example.com")
    calls = []
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr("email_service.send_otp_email", lambda *a, **k: True)
    r = client.post("/app/api/auth/request-otp", json={"phone": phone})
    assert r.status_code == 200, r.text
    assert calls == []


# ── The switch itself ────────────────────────────────────────────────────────

def test_admin_can_flip_it_without_a_deploy():
    admin = _register(ADMIN_PHONE, "App Admin")
    assert "coming soon" in client.get("/").text.lower()

    r = client.post("/app/api/admin/site-settings", cookies=admin,
                    json={"settings": {"whatsapp_live": "yes"}})
    assert r.status_code == 200, r.text
    # No cache to wait out: the claim changes on the next request.
    assert "Message tiTi on WhatsApp" in client.get("/").text

    client.post("/app/api/admin/site-settings", cookies=admin,
                json={"settings": {"whatsapp_live": "no"}})
    assert "Message tiTi on WhatsApp" not in client.get("/").text
