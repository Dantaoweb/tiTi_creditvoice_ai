"""
Personal savings plan: a saver sets a frequency (required) and an optional goal;
the summary tracks total saved, progress toward the goal, and when the next save
is due.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-savings-00000000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth

client = TestClient(app)
_seq = iter(range(8200, 8999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _user():
    n = next(_seq)
    phone = f"234821{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Saver", "phone": phone, "pin": "2468"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "2468"}).cookies


def test_plan_tracks_goal_progress_and_frequency():
    cook = _user()
    assert client.get("/app/api/savings/plan", cookies=cook).json()["has_plan"] is False

    p = client.post("/app/api/savings/plan", cookies=cook,
                    json={"frequency": "weekly", "goal_amount": 100000}).json()
    assert p["has_plan"] is True
    assert p["frequency"] == "weekly"
    assert p["goal_amount"] == 100000

    client.post("/app/api/thrift/save", cookies=cook, json={"amount": 20000})
    s = client.get("/app/api/savings/plan", cookies=cook).json()
    assert s["total_saved"] == 20000
    assert s["goal_pct"] == 20
    assert s["deposits"] == 1
    assert s["next_due_at"] is not None


def test_frequency_is_required_and_validated():
    cook = _user()
    r = client.post("/app/api/savings/plan", cookies=cook, json={"frequency": "yearly"})
    assert r.status_code == 400
