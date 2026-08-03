"""
Notification delete (single + clear) and the retention purge that keeps the
app_notifications table bounded.
"""
import os
from datetime import datetime, timezone, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-notif-delete-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, AppNotification

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(7000, 8000))


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234833{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _seed(owner_phone, n, is_read=0, age_days=0, event_type="test"):
    db = SessionLocal()
    try:
        for i in range(n):
            db.add(AppNotification(
                owner_phone=owner_phone, event_type=event_type,
                title=f"t{i}", body="b", is_read=is_read,
                created_at=_now() - timedelta(days=age_days),
            ))
        db.commit()
    finally:
        db.close()


def test_delete_single_notification():
    phone, cook = _owner()
    _seed(phone, 3)
    listed = client.get("/app/api/notifications", cookies=cook).json()["notifications"]
    assert len(listed) == 3
    nid = listed[0]["id"]
    r = client.delete(f"/app/api/notifications/{nid}", cookies=cook)
    assert r.status_code == 200 and r.json()["deleted"] == 1
    after = client.get("/app/api/notifications", cookies=cook).json()["notifications"]
    assert len(after) == 2 and all(x["id"] != nid for x in after)


def test_clear_all_and_only_read():
    phone, cook = _owner()
    _seed(phone, 2, is_read=1)
    _seed(phone, 3, is_read=0)
    # only_read clears the 2 read
    r = client.post("/app/api/notifications/clear", cookies=cook, params={"only_read": "true"})
    assert r.status_code == 200 and r.json()["deleted"] == 2
    left = client.get("/app/api/notifications", cookies=cook).json()["notifications"]
    assert len(left) == 3
    # clear all removes the rest
    r2 = client.post("/app/api/notifications/clear", cookies=cook)
    assert r2.status_code == 200 and r2.json()["deleted"] == 3
    assert client.get("/app/api/notifications", cookies=cook).json()["notifications"] == []


def test_cannot_delete_other_owners_notification():
    p1, cook1 = _owner()
    _seed(p1, 1)
    nid = client.get("/app/api/notifications", cookies=cook1).json()["notifications"][0]["id"]
    _p2, cook2 = _owner()
    r = client.delete(f"/app/api/notifications/{nid}", cookies=cook2)
    assert r.status_code == 200 and r.json()["deleted"] == 0  # scoped out, nothing deleted
    # still there for owner 1
    assert len(client.get("/app/api/notifications", cookies=cook1).json()["notifications"]) == 1


def test_purge_removes_old_read_and_caps():
    from proactive_scheduler import _purge_old_notifications, _NOTIF_KEEP_MAX
    phone, _cook = _owner()
    _seed(phone, 5, is_read=1, age_days=40)   # old + read -> purged
    _seed(phone, 5, is_read=0, age_days=40)   # old but unread -> kept
    _seed(phone, 3, is_read=1, age_days=1)    # recent read -> kept
    db = SessionLocal()
    try:
        _purge_old_notifications(db)
        remaining = db.query(AppNotification).filter(
            AppNotification.owner_phone == phone).count()
        assert remaining == 8, remaining  # 5 old-read removed, 8 kept
    finally:
        db.close()


def test_purge_caps_to_keep_max():
    from proactive_scheduler import _purge_old_notifications, _NOTIF_KEEP_MAX
    phone, _cook = _owner()
    _seed(phone, _NOTIF_KEEP_MAX + 20, is_read=0, age_days=1)  # recent, unread, over cap
    db = SessionLocal()
    try:
        _purge_old_notifications(db)
        remaining = db.query(AppNotification).filter(
            AppNotification.owner_phone == phone).count()
        assert remaining == _NOTIF_KEEP_MAX, remaining
    finally:
        db.close()


def test_purge_never_deletes_notes():
    """Notes are business records — the automatic purge must leave them alone,
    even when old + read and even past the row cap."""
    from proactive_scheduler import _purge_old_notifications, _NOTIF_KEEP_MAX
    phone, _cook = _owner()
    _seed(phone, 10, is_read=1, age_days=40, event_type="note")          # old + read notes
    _seed(phone, _NOTIF_KEEP_MAX + 50, is_read=1, age_days=1, event_type="note")  # over cap
    db = SessionLocal()
    try:
        _purge_old_notifications(db)
        notes = db.query(AppNotification).filter(
            AppNotification.owner_phone == phone,
            AppNotification.event_type == "note").count()
        assert notes == 10 + _NOTIF_KEEP_MAX + 50, notes  # every note preserved
    finally:
        db.close()
