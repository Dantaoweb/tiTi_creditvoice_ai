"""
Busy shops are never locked out of tiTi on the web.

Only messages that actually need the AI count against the hourly budget;
recording a sale, "yes" and menu numbers never do. When the AI budget is used
up tiTi still answers and says how many minutes are left. WhatsApp owners are
never limited.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-ai-budget-000000000000000")

import pytest
from fastapi.testclient import TestClient

import ai_budget
import web_auth
from main import app

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    ai_budget._reset_for_tests()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    ai_budget._reset_for_tests()


def _owner():
    phone = f"2348099{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Busy Shop", "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_a_busy_hour_of_recording_is_never_blocked():
    cook = _owner()
    # 25 sales + 25 YES = 50 messages: the old limit (30 an hour) locked the shop out
    for n in range(25):
        r = client.post("/app/api/chat/send", cookies=cook, json={"text": f"Ade{n} bought rice 5000"})
        assert r.status_code == 200, (n, r.text)
        r = client.post("/app/api/chat/send", cookies=cook, json={"text": "yes"})
        assert r.status_code == 200, (n, r.text)


def test_only_ai_calls_are_counted_and_the_limit_says_the_real_wait(monkeypatch):
    with ai_budget.for_user("u1"):
        for _ in range(ai_budget.AI_LIMIT):
            assert ai_budget.allow()
        assert not ai_budget.allow() and ai_budget.was_exhausted()
    note = ai_budget.exhausted_note("u1")
    assert "minute" in note and "an hour" not in note and "Ade bought rice 5000" in note


def test_whatsapp_has_no_budget():
    for _ in range(ai_budget.AI_LIMIT * 2):
        assert ai_budget.allow()                      # no person set → not limited


def test_when_the_budget_is_used_up_tiTi_still_answers(monkeypatch):
    cook = _owner()
    me = client.get("/app/api/auth/me", cookies=cook).json()["id"]
    with ai_budget.for_user(me):
        while ai_budget.allow():
            pass
    # A message whose answer needs the AI: the AI is skipped, tiTi still
    # answers, and the reply says when full help is back
    import query_handler

    def needs_ai(db, owner_phone, text, recorded_by_id=None):
        return "Here's what I could read." if not ai_budget.allow() else "AI answer"
    monkeypatch.setattr(query_handler, "handle_natural_language_query", needs_ai)
    r = client.post("/app/api/chat/send", cookies=cook, json={"text": "tell me about my week"})
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert reply.startswith("Here's what I could read.") and "Full help is back in" in reply


def test_the_unregistered_whatsapp_wait_is_the_real_one():
    import rate_limiter
    msg = rate_limiter.rate_limit_exceeded_message(7)
    assert "7 minutes" in msg and "5 minutes" not in msg
    assert "a few minutes" in rate_limiter.rate_limit_exceeded_message()
