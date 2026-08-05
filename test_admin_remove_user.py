"""
App-admin soft-remove / restore of a business:
  - removed owner (and staff) are signed out and blocked from logging in;
  - existing sessions stop working;
  - restore re-enables login;
  - non-admins can't remove, admin can't remove themselves.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-admin-remove-0000000000")
os.environ["APP_ADMIN_PHONES"] = "2348190000001"

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    # app_admin_phones() reads env live; another test module may have overwritten
    # APP_ADMIN_PHONES at import, so restore ours before each test (whole suite
    # runs in one process on CI).
    os.environ["APP_ADMIN_PHONES"] = "2348190000001"
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register(name, phone, pin="5678"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": pin})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def _admin_cookies():
    return _register("Admin", "2348190000001")


def test_remove_blocks_login_and_sessions_then_restore():
    admin = _admin_cookies()
    owner_phone = "2348190000010"
    owner_cookies = _register("Shop", owner_phone)

    # Owner's session works before removal.
    assert client.get("/app/api/auth/me", cookies=owner_cookies).status_code == 200

    # Find the owner id.
    db = SessionLocal()
    oid = db.query(User).filter(User.phone == owner_phone).first().id
    db.close()

    # Admin removes the business.
    r = client.delete(f"/app/api/admin/users/{oid}", cookies=admin)
    assert r.status_code == 200, r.text

    # Existing session is now dead, fresh login is blocked.
    assert client.get("/app/api/auth/me", cookies=owner_cookies).status_code == 401
    relog = client.post("/app/api/auth/login", json={"phone": owner_phone, "pin": "5678"})
    assert relog.status_code == 401

    # It shows as REMOVED in the admin directory.
    listing = client.get("/app/api/admin/users?q=2348190000010", cookies=admin).json()
    row = next(u for u in listing["users"] if u["phone"] == owner_phone)
    assert row["deleted_at"] is not None

    # Restore re-enables login.
    r = client.post(f"/app/api/admin/users/{oid}/restore", cookies=admin)
    assert r.status_code == 200, r.text
    relog2 = client.post("/app/api/auth/login", json={"phone": owner_phone, "pin": "5678"})
    assert relog2.status_code == 200


def test_remove_cascades_to_staff():
    admin = _admin_cookies()
    owner_phone = "2348190000020"
    owner_cookies = _register("Biz", owner_phone)
    staff_phone = "2348190000021"
    code = client.post("/app/api/staff/invite", cookies=owner_cookies,
                       json={"name": "Sade", "phone": staff_phone}).json()
    # Owner needs a plan for staff invite? invite may 403 without PRO; make owner PRO.
    db = SessionLocal()
    o = db.query(User).filter(User.phone == owner_phone).first()
    o.subscription_plan = "PRO"; o.subscription_status = "ACTIVE"; db.commit()
    oid = o.id
    db.close()
    code = client.post("/app/api/staff/invite", cookies=owner_cookies,
                       json={"name": "Sade", "phone": staff_phone}).json()["invite_code"]
    client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": code, "new_pin": "4321"})

    r = client.delete(f"/app/api/admin/users/{oid}", cookies=admin)
    assert r.status_code == 200, r.text
    assert r.json().get("staff_removed", 0) >= 1

    # Staff can no longer log in.
    relog = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "4321"})
    assert relog.status_code == 401


def test_non_admin_cannot_remove():
    _admin_cookies()
    victim_phone = "2348190000030"
    _register("Victim", victim_phone)
    attacker = _register("Attacker", "2348190000031")
    db = SessionLocal()
    vid = db.query(User).filter(User.phone == victim_phone).first().id
    db.close()
    r = client.delete(f"/app/api/admin/users/{vid}", cookies=attacker)
    assert r.status_code == 403


def test_admin_cannot_remove_self():
    admin = _admin_cookies()
    db = SessionLocal()
    aid = db.query(User).filter(User.phone == "2348190000001").first().id
    db.close()
    r = client.delete(f"/app/api/admin/users/{aid}", cookies=admin)
    assert r.status_code == 400
