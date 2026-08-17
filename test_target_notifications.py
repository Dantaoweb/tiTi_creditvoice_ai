"""
The proactive scheduler nudges members of a target (shared-goal) thrift group to
keep saving, and celebrates once when the goal is reached.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-target-notify-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import AppNotification, ProactiveLog
import proactive_scheduler as ps

client = TestClient(app)
_seq = iter(range(8600, 8999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _user(name, plan=None):
    n = next(_seq)
    phone = f"234823{n:06d}"
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "9753"})
    if plan:
        db = SessionLocal()
        try:
            from models import User
            u = db.query(User).filter(User.phone == phone).first()
            u.subscription_plan = plan
            db.commit()
        finally:
            db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "9753"}).cookies
    return phone, cook


def _notifs(phone, prefix):
    db = SessionLocal()
    try:
        return db.query(AppNotification).filter(
            AppNotification.owner_phone == phone,
            AppNotification.event_type.like(f"{prefix}%"),
        ).count()
    finally:
        db.close()


def test_members_get_a_savings_nudge_and_no_spam():
    admin_phone, admin = _user("Host", plan="PRO")
    g = client.post("/app/api/thrift/groups", cookies=admin, json={
        "name": "Eid Fund", "group_type": "target", "goal_amount": 100000, "max_members": 10,
        "require_approval": False}).json()
    member_phone, member = _user("Amina")
    client.post(f"/app/api/thrift/join/{g['invite_token']}", cookies=member, json={})

    db = SessionLocal()
    try:
        ps._check_target_savings(db)
    finally:
        db.close()

    # Both linked members are nudged.
    assert _notifs(admin_phone, "target_nudge") == 1
    assert _notifs(member_phone, "target_nudge") == 1

    # Running again immediately does not re-notify (interval guard).
    db = SessionLocal()
    try:
        ps._check_target_savings(db)
    finally:
        db.close()
    assert _notifs(member_phone, "target_nudge") == 1


def test_goal_reached_celebration():
    admin_phone, admin = _user("Host2", plan="PRO")
    g = client.post("/app/api/thrift/groups", cookies=admin, json={
        "name": "Sallah Pool", "group_type": "target", "goal_amount": 10000, "max_members": 10,
        "require_approval": False}).json()
    gid = g["id"]
    admin_id = g["members"][0]["id"]
    # Meet the goal.
    client.post(f"/app/api/thrift/groups/{gid}/contributions", cookies=admin,
                json={"member_id": admin_id, "amount": 10000})

    db = SessionLocal()
    try:
        ps._check_target_savings(db)
    finally:
        db.close()
    assert _notifs(admin_phone, "target_reached") == 1
    assert _notifs(admin_phone, "target_nudge") == 0
