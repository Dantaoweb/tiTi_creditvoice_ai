"""
Cold-customer reminder fallback: when tiTi can't deliver a reminder over WhatsApp
(the customer never messaged the tiTi number), the send endpoint returns a
self-send link instead of silently marking it SENT.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-reminder-selfsend-0000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import whatsapp_client
from database import SessionLocal
from models import User, ReminderQueue

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner_with_reminder(cust_phone="08055550001"):
    n = next(_seq)
    phone = f"234807000{n:04d}"
    client.post("/app/api/auth/register", json={"name": "O", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    r = ReminderQueue(owner_phone=phone, customer_phone=cust_phone, customer_name="Ada",
                      balance=5000, message_text="Hi Ada, you owe N5,000.",
                      status="PENDING_OWNER_CONFIRMATION")
    db.add(r); db.commit(); rid = r.id; db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return rid, cook


def test_undeliverable_reminder_returns_self_send_link(monkeypatch):
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message", lambda to, msg: False)
    rid, cook = _owner_with_reminder(cust_phone="08055550002")
    r = client.post(f"/app/api/reminders/{rid}/send", cookies=cook)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivered"] is False
    assert body["message_text"] == "Hi Ada, you owe N5,000."
    # link targets the customer in international format, with the message prefilled
    assert body["self_send_url"].startswith("https://wa.me/2348055550002?text=")
    # not marked sent — it wasn't delivered
    db = SessionLocal()
    assert db.query(ReminderQueue).filter(ReminderQueue.id == rid).first().status != "SENT"
    db.close()


def test_delivered_reminder_marks_sent(monkeypatch):
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message", lambda to, msg: True)
    rid, cook = _owner_with_reminder()
    r = client.post(f"/app/api/reminders/{rid}/send", cookies=cook)
    assert r.status_code == 200
    assert r.json().get("delivered") is True
    db = SessionLocal()
    assert db.query(ReminderQueue).filter(ReminderQueue.id == rid).first().status == "SENT"
    db.close()
