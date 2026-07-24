"""
Regression: app admins can manage opportunities (#5).

Admin-ness across the app is is_app_admin() (APP_ADMIN_PHONES / AppAdminRole),
and the Admin UI is only shown to those users. The opportunities admin routes
instead required user.role == "admin", so a real admin got 403 — they could not
create opportunities (so users saw none) nor list the ones added earlier.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-opps-admin-tests-000000000000")
ADMIN_PHONE = "2348099990001"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    # Set here (not just at import) so a sibling admin test module that also sets
    # APP_ADMIN_PHONES can't clobber ours — app_admin_phones() reads env live.
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _login(phone):
    client.post("/app/api/auth/register", json={"name": "U", "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_app_admin_can_create_and_see_opportunities():
    cookies = _login(ADMIN_PHONE)

    created = client.post("/app/api/admin/opportunities", cookies=cookies,
                          json={"title": "Grant X", "description": "A grant", "category": "grant"})
    assert created.status_code == 200, created.text

    admin_list = client.get("/app/api/admin/opportunities", cookies=cookies)
    assert admin_list.status_code == 200, admin_list.text
    assert any(o["title"] == "Grant X" for o in admin_list.json()["opportunities"])

    # And it is visible to ordinary users (is_active defaults True)
    public = client.get("/app/api/opportunities")
    assert any(o["title"] == "Grant X" for o in public.json()["opportunities"])


def test_non_admin_is_forbidden():
    cookies = _login("2348099990002")   # not in APP_ADMIN_PHONES
    assert client.get("/app/api/admin/opportunities", cookies=cookies).status_code == 403


def test_application_questions_reach_users():
    import json
    cookies = _login(ADMIN_PHONE)
    fields = json.dumps([{"label": "Years in business", "type": "text", "required": True}])
    created = client.post("/app/api/admin/opportunities", cookies=cookies,
                          json={"title": "Loan Offer", "description": "d", "category": "finance",
                                "application_fields": fields})
    assert created.status_code == 200, created.text

    # The questions must reach an ordinary user's apply form
    pub = client.get("/app/api/opportunities").json()["opportunities"]
    offer = next(o for o in pub if o["title"] == "Loan Offer")
    parsed = json.loads(offer["application_fields"])
    assert parsed and parsed[0]["label"] == "Years in business"

    # And the admin list round-trips them for editing
    adm = client.get("/app/api/admin/opportunities", cookies=cookies).json()["opportunities"]
    offer_a = next(o for o in adm if o["title"] == "Loan Offer")
    assert json.loads(offer_a["application_fields"])[0]["required"] is True
