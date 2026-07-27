"""
#10: an app admin can send in-app notifications to one user or all owners.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-admin-notify-0000000000000")
ADMIN_PHONE = "2348090001000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _login(phone, pin="5678"):
    client.post("/app/api/auth/register", json={"name": "U", "phone": phone, "pin": pin})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def _notifs(cook):
    return client.get("/app/api/notifications", cookies=cook).json()["notifications"]


def test_admin_broadcast_reaches_all_owners():
    admin = _login(ADMIN_PHONE)
    u1 = _login(f"234801000{next(_seq):04d}")
    u2 = _login(f"234801000{next(_seq):04d}")
    r = client.post("/app/api/admin/notifications", cookies=admin,
                    json={"title": "Heads up", "body": "New invoices feature is live", "target": "all"})
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] >= 2
    for cook in (u1, u2):
        assert any(n["event_type"] == "admin" and n["title"] == "Heads up" for n in _notifs(cook))


def test_admin_notify_single_user():
    admin = _login(ADMIN_PHONE)
    target_phone = f"234802000{next(_seq):04d}"
    other_phone = f"234802000{next(_seq):04d}"
    u_target = _login(target_phone)
    u_other = _login(other_phone)
    r = client.post("/app/api/admin/notifications", cookies=admin,
                    json={"title": "Just you", "body": "Please verify your details", "target": "phone", "phone": target_phone})
    assert r.status_code == 200 and r.json()["recipients"] == 1
    assert any(n["title"] == "Just you" for n in _notifs(u_target))
    assert not any(n["title"] == "Just you" for n in _notifs(u_other))


def test_non_admin_cannot_broadcast():
    cook = _login(f"234803000{next(_seq):04d}")
    r = client.post("/app/api/admin/notifications", cookies=cook,
                    json={"title": "x", "body": "y", "target": "all"})
    assert r.status_code == 403
