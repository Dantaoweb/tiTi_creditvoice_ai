"""
Enterprise ("Let's talk") for large businesses, and the homepage that says
who CreditVoice is for: every size, swipeable reviews, an Enterprise card.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-enterprise-00000000000000000")
ADMIN_PHONE = "2348090033000"

import pytest
from fastapi.testclient import TestClient

import main
import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, EnterpriseEnquiry

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    import web_pay_link_routes
    web_pay_link_routes._hits.clear()
    main._LANDING_CACHE["blocks"] = None
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    main._LANDING_CACHE["blocks"] = None


def _login(phone, name):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


ENQ = {"name": "Mrs Okon", "business": "Grand Mall Ltd", "phone": "0803 444 5555",
       "email": "it@grandmall.ng", "branches": "6", "message": "POS in 6 stores, 20,000 products"}


def test_enquiry_reaches_the_admins_and_their_tab():
    admin = _login(ADMIN_PHONE, "App Admin")
    r = client.post("/app/api/public/enterprise-enquiry", json=ENQ)          # no account needed
    assert r.status_code == 200 and r.json()["ok"]
    db = SessionLocal()
    try:
        e = db.query(EnterpriseEnquiry).filter(EnterpriseEnquiry.business == "Grand Mall Ltd").one()
        assert e.phone == "08034445555" and e.status == "NEW" and e.source == "landing"
        n = db.query(AppNotification).filter(AppNotification.owner_phone == ADMIN_PHONE,
                                             AppNotification.event_type == "enterprise_enquiry").one()
        assert "Grand Mall Ltd" in n.title and n.link == "/admin?tab=Enquiries"
    finally:
        db.close()
    assert client.get("/app/api/admin/pending-counts", cookies=admin).json()["enquiries"] >= 1
    lst = client.get("/app/api/admin/enquiries?status=NEW", cookies=admin).json()
    row = next(x for x in lst["enquiries"] if x["business"] == "Grand Mall Ltd")
    up = client.patch(f"/app/api/admin/enquiries/{row['id']}", cookies=admin,
                      json={"status": "CONTACTED", "admin_note": "Called, demo Friday"}).json()
    assert up["status"] == "CONTACTED" and up["admin_note"] == "Called, demo Friday"
    # not for ordinary users
    shop = _login("2348090033101", "Shop")
    assert client.get("/app/api/admin/enquiries", cookies=shop).status_code == 403


def test_bad_enquiries_are_refused():
    for bad in ({**ENQ, "phone": "123"}, {**ENQ, "business": "x"}, {**ENQ, "email": "nope"}):
        assert client.post("/app/api/public/enterprise-enquiry", json=bad).status_code == 400


def test_homepage_says_every_size_and_shows_enterprise():
    body = client.get("/").text
    assert "Run your <span class=\"hl\">whole business</span>" in body
    assert 'id="for-you"' in body and "Shops &amp; supermarkets" in body and "Schools" in body
    assert "Thrift" not in body and "Ajo" not in body                  # not until Monnify is ready
    assert 'id="enterprise"' in body and "Let&rsquo;s talk" in body and "data-enquiry" in body
    assert "small businesses" not in body
