"""
Web Push subscription endpoints: subscribe stores a device, unsubscribe removes
it, and send_web_push no-ops safely when VAPID isn't configured.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-push-0000000000000000")
# Ensure push looks unconfigured for these tests.
os.environ.pop("VAPID_PUBLIC_KEY", None)
os.environ.pop("VAPID_PRIVATE_KEY", None)

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, PushSubscription

client = TestClient(app, raise_server_exceptions=True)
PHONE = "2348270000001"


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _login():
    client.post("/app/api/auth/register", json={"name": "U", "phone": PHONE, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": PHONE, "pin": "5678"}).cookies


SUB = {"endpoint": "https://push.example.com/abc123", "p256dh": "BKp256key", "auth": "authsecret"}


def test_config_reports_push_disabled_when_unconfigured():
    d = client.get("/app/api/auth/config").json()
    assert d["push_enabled"] is False
    assert d["vapid_public_key"] == ""


def test_subscribe_then_unsubscribe():
    cook = _login()
    r = client.post("/app/api/push/subscribe", cookies=cook, json=SUB)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        row = db.query(PushSubscription).filter(PushSubscription.endpoint == SUB["endpoint"]).first()
        assert row and row.owner_phone == PHONE and row.p256dh == "BKp256key"
    finally:
        db.close()

    # Re-subscribing the same endpoint updates, not duplicates.
    client.post("/app/api/push/subscribe", cookies=cook, json={**SUB, "auth": "newauth"})
    db = SessionLocal()
    try:
        rows = db.query(PushSubscription).filter(PushSubscription.endpoint == SUB["endpoint"]).all()
        assert len(rows) == 1 and rows[0].auth == "newauth"
    finally:
        db.close()

    # Unsubscribe removes it.
    r = client.post("/app/api/push/unsubscribe", cookies=cook, json={"endpoint": SUB["endpoint"]})
    assert r.status_code == 200 and r.json()["removed"] == 1
    db = SessionLocal()
    try:
        assert db.query(PushSubscription).filter(PushSubscription.endpoint == SUB["endpoint"]).first() is None
    finally:
        db.close()


def test_subscribe_requires_auth():
    client.cookies.clear()   # TestClient persists login cookies across tests
    assert client.post("/app/api/push/subscribe", json=SUB).status_code in (401, 403)


def test_send_web_push_noop_when_unconfigured():
    from web_push import send_web_push, push_enabled
    assert push_enabled() is False
    # Must not raise even with no config / no subscriptions.
    send_web_push(PHONE, "Title", "Body")
