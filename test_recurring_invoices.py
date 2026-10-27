"""
Repeat invoices: an invoice set to repeat makes a new, ordinary invoice on
each date — sent to the customer, or left for the owner to check — until it is
paused, stopped, or reaches its end.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-repeat-invoices-000000000000")

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, Customer, Invoice, RecurringInvoice

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
sent = []


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sent.clear()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda to, m, *a, **k: sent.append((to, m)) or True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _landlord(cust_phone="2348036666666"):
    phone = f"2348107{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Properties", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        c = Customer(owner_phone=phone, name="tenant bola", customer_phone=cust_phone, balance=0)
        db.add(c); db.commit()
        cid = c.id
    finally:
        db.close()
    inv = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cid, "items": [{"name": "Shop rent", "qty": 1, "unit_price": 150000}],
        "note": "Shop 4"}).json()
    return phone, cook, cid, inv


def test_step_keeps_the_day_of_the_month():
    from recurring_invoices import step
    assert step(date(2026, 1, 31), "month", 31) == date(2026, 2, 28)
    assert step(date(2026, 2, 28), "month", 31) == date(2026, 3, 31)
    assert step(date(2026, 11, 15), "quarter") == date(2027, 2, 15)
    assert step(date(2026, 11, 15), "week") == date(2026, 11, 22)
    assert step(date(2028, 2, 29), "year", 29) == date(2029, 2, 28)


def test_repeat_makes_and_sends_and_ends():
    phone, cook, cid, inv = _landlord()
    from recurring_invoices import lagos_today
    today = lagos_today()
    r = client.post(f"/app/api/invoices/doc/{inv['id']}/repeat", cookies=cook, json={
        "every": "month", "start": today.isoformat(), "stop_after": 2}).json()
    assert (r["every_label"], r["total"], r["status"], r["made_count"]) == ("every month", 150000, "active", 0)
    assert client.get(f"/app/api/invoices/doc/{inv['id']}", cookies=cook).json()["repeat"]["every_label"] == "every month"
    # one repeat per invoice
    assert client.post(f"/app/api/invoices/doc/{inv['id']}/repeat", cookies=cook, json={
        "every": "month", "start": today.isoformat()}).status_code == 400

    from proactive_scheduler import _check_repeat_invoices
    db = SessionLocal()
    _check_repeat_invoices(db); _check_repeat_invoices(db)       # once only on the day
    db.close()
    db = SessionLocal()
    try:
        made = db.query(Invoice).filter(Invoice.owner_phone == phone, Invoice.recurring_id == r["id"]).all()
        assert len(made) == 1 and made[0].total == 150000 and made[0].note == "Shop 4" and made[0].sent_at
        assert made[0].number == inv["number"] + 1
        rep = db.query(RecurringInvoice).get(r["id"])
        assert rep.made_count == 1 and rep.next_date.date() > today and rep.status == "active"
        note = db.query(AppNotification).filter(AppNotification.owner_phone == phone,
                                                AppNotification.event_type == "repeat_invoice").one()
        assert "sent" in note.title and note.link == f"/invoices/{made[0].id}"
        # second (last) one: pretend the next date has come
        rep.next_date = rep.next_date - timedelta(days=40); db.commit()
    finally:
        db.close()
    assert [to for to, _m in sent] == ["2348036666666"]
    db = SessionLocal()
    _check_repeat_invoices(db)
    db.close()
    lst = client.get("/app/api/recurring-invoices", cookies=cook).json()["repeats"]
    assert lst[0]["made_count"] == 2 and lst[0]["status"] == "ended"


def test_check_first_pause_resume_and_edit():
    phone, cook, cid, inv = _landlord()
    from recurring_invoices import lagos_today
    today = lagos_today()
    r = client.post(f"/app/api/invoices/doc/{inv['id']}/repeat", cookies=cook, json={
        "every": "week", "start": today.isoformat(), "auto_send": False}).json()
    assert client.post(f"/app/api/recurring-invoices/{r['id']}/status", cookies=cook,
                       json={"action": "pause"}).json()["status"] == "paused"
    from proactive_scheduler import _check_repeat_invoices
    db = SessionLocal(); _check_repeat_invoices(db); db.close()
    assert client.get("/app/api/recurring-invoices", cookies=cook).json()["repeats"][0]["made_count"] == 0
    client.post(f"/app/api/recurring-invoices/{r['id']}/status", cookies=cook, json={"action": "resume"})
    # new price from now on
    up = client.put(f"/app/api/recurring-invoices/{r['id']}", cookies=cook, json={
        "every": "week", "start": today.isoformat(), "auto_send": False,
        "items": [{"name": "Shop rent", "qty": 1, "unit_price": 175000}]}).json()
    assert up["total"] == 175000
    db = SessionLocal(); _check_repeat_invoices(db); db.close()
    db = SessionLocal()
    try:
        made = db.query(Invoice).filter(Invoice.recurring_id == r["id"]).one()
        assert made.total == 175000 and made.sent_at is None             # left for the owner to check
        n = db.query(AppNotification).filter(AppNotification.owner_phone == phone,
                                             AppNotification.event_type == "repeat_invoice").one()
        assert "ready to send" in n.title
    finally:
        db.close()
    assert sent == []
    assert client.post(f"/app/api/recurring-invoices/{r['id']}/status", cookies=cook,
                       json={"action": "stop"}).json()["status"] == "ended"


def test_bad_input_and_other_business():
    _p, cook, _c, inv = _landlord()
    _p2, cook2, _c2, _inv2 = _landlord()
    from recurring_invoices import lagos_today
    today = lagos_today()
    for bad in ({"every": "daily", "start": today.isoformat()},
                {"every": "month", "start": (today - timedelta(days=1)).isoformat()},
                {"every": "month", "start": today.isoformat(), "stop_on": (today - timedelta(days=1)).isoformat()}):
        assert client.post(f"/app/api/invoices/doc/{inv['id']}/repeat", cookies=cook, json=bad).status_code == 400
    assert client.post(f"/app/api/invoices/doc/{inv['id']}/repeat", cookies=cook2, json={
        "every": "month", "start": today.isoformat()}).status_code == 404
    r = client.post(f"/app/api/invoices/doc/{inv['id']}/repeat", cookies=cook, json={
        "every": "month", "start": today.isoformat()}).json()
    assert client.post(f"/app/api/recurring-invoices/{r['id']}/status", cookies=cook2,
                       json={"action": "stop"}).status_code == 404
    assert client.get("/app/api/recurring-invoices", cookies=cook2).json()["repeats"] == []


@pytest.mark.parametrize("text", [
    "how do I bill a tenant every month?", "can I make a recurring invoice", "how to send the same invoice every week",
])
def test_titi_explains_repeat_invoices(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    p = parse_message(text) or {}
    assert (p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "repeat_invoice"
    a = build_app_guide_message("repeat_invoice")
    assert "Make it repeat" in a and "Send it for me" in a and "Repeating" in a


def test_plain_invoice_question_still_goes_to_invoices():
    from faq import detect_faq
    assert detect_faq("how do I send an invoice") == "invoices"
