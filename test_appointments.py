"""
Appointments: book a time for a customer and service, warn on clashes for
the same staff, mark arrived / no-show / done (done records the sale), and
remind the customer the evening before and the owner each morning.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-appointments-0000000000000")

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Appointment, AppNotification, Customer, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
sent = []


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sent.clear()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda to, m, *a, **k: sent.append((to, m)) or True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _salon():
    phone = f"2348106{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Salon", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        cut = InventoryItem(owner_phone=phone, name="haircut", quantity=None, category="service",
                            selling_price=3000, is_available=True)
        ada = Customer(owner_phone=phone, name="ada", customer_phone="2348035555555", balance=0)
        db.add_all([cut, ada]); db.commit()
        return phone, cook, cut.id, ada.id
    finally:
        db.close()


def _book(cook, ada, cut, time="10:30", day="2026-11-03", staff="Musa"):
    return client.post("/app/api/appointments", cookies=cook, json={
        "date": day, "time": time, "duration_min": 45, "customer_id": ada,
        "services": [{"inventory_item_id": cut}], "staff_name": staff, "note": "Low cut"})


def test_book_list_clash_and_done():
    phone, cook, cut, ada = _salon()
    r = _book(cook, ada, cut)
    assert r.status_code == 200, r.text
    a = r.json()
    assert (a["time"], a["end"], a["total"], a["status"], a["clashes"]) == ("10:30", "11:15", 3000, "booked", [])
    assert a["services"][0]["name"] == "haircut" and a["staff_name"] == "Musa"

    clash = _book(cook, ada, cut, time="11:00").json()          # overlaps Musa's 10:30–11:15
    assert clash["clashes"] == [{"time": "10:30", "customer": "Ada"}]
    assert _book(cook, ada, cut, time="11:00", staff="Tunde").json()["clashes"] == []

    day = client.get("/app/api/appointments?day=2026-11-03", cookies=cook).json()
    assert [x["time"] for x in day["appointments"]] == ["10:30", "11:00", "11:00"]

    client.post(f"/app/api/appointments/{a['id']}/status", cookies=cook, json={"status": "arrived"})
    done = client.post(f"/app/api/appointments/{a['id']}/done", cookies=cook, json={"paid": 2000}).json()
    assert done["status"] == "done" and done["receipt_id"]
    db = SessionLocal()
    try:
        assert db.query(Customer).get(ada).balance == 1000                 # unpaid part is debt
    finally:
        db.close()
    assert client.post(f"/app/api/appointments/{a['id']}/status", cookies=cook,
                       json={"status": "cancelled"}).status_code == 400


def test_no_shows_are_counted_and_moving_resets_the_reminder():
    _p, cook, cut, ada = _salon()
    a = _book(cook, ada, cut).json()
    client.post(f"/app/api/appointments/{a['id']}/status", cookies=cook, json={"status": "no_show"})
    b = _book(cook, ada, cut, day="2026-11-04").json()
    assert b["no_shows"] == 1
    db = SessionLocal()
    try:
        db.query(Appointment).get(b["id"]).reminded_at = datetime.utcnow(); db.commit()
    finally:
        db.close()
    moved = client.put(f"/app/api/appointments/{b['id']}", cookies=cook, json={
        "date": "2026-11-05", "time": "09:00", "duration_min": 30, "customer_id": ada,
        "services": [{"inventory_item_id": cut}]}).json()
    assert moved["date"] == "2026-11-05" and moved["reminded"] is False


def test_reminders_evening_before_and_owner_morning_list():
    phone, cook, cut, ada = _salon()
    from appointments import due_reminders, lagos_now
    tomorrow = (lagos_now() + timedelta(days=1)).date().isoformat()
    _book(cook, ada, cut, day=tomorrow, time="10:30")
    db = SessionLocal()
    try:
        evening = datetime.combine(lagos_now().date(), datetime.min.time()) + timedelta(hours=18)
        morning = evening - timedelta(hours=10)
        assert due_reminders(db, now=morning) == []                 # not before 5pm
        assert len([a for a in due_reminders(db, now=evening) if a.owner_phone == phone]) == 1
    finally:
        db.close()

    import appointments
    from proactive_scheduler import _check_appointments
    real_now = appointments.lagos_now
    appointments.lagos_now = lambda: evening
    try:
        db = SessionLocal()
        _check_appointments(db); _check_appointments(db)          # once only
        db.close()
    finally:
        appointments.lagos_now = real_now
    mine = [m for to, m in sent if to == "2348035555555"]
    assert len(mine) == 1 and "Bello Salon" in mine[0] and "10:30 AM" in mine[0] and "haircut" in mine[0]

    # Next morning the owner gets the day's list
    appointments.lagos_now = lambda: datetime.combine(lagos_now().date() + timedelta(days=1), datetime.min.time()) + timedelta(hours=8)
    try:
        db = SessionLocal()
        _check_appointments(db)
        note = db.query(AppNotification).filter(AppNotification.owner_phone == phone,
                                                AppNotification.event_type == "appointments_today").one()
        assert "1 appointment" in note.title and "Ada" in note.body
        db.close()
    finally:
        appointments.lagos_now = real_now


def test_bad_input_and_other_business():
    _p, cook, cut, ada = _salon()
    _p2, cook2, _c2, _a2 = _salon()
    assert client.post("/app/api/appointments", cookies=cook, json={
        "date": "2026-11-03", "time": "25:99", "customer_id": ada}).status_code == 400
    a = _book(cook, ada, cut).json()
    assert client.post(f"/app/api/appointments/{a['id']}/status", cookies=cook2,
                       json={"status": "arrived"}).status_code == 404


@pytest.mark.parametrize("text", [
    "how do I book an appointment?", "how can I book customers for a time", "how do appointments work",
    "how can customers book online with a booking link",
])
def test_titi_explains_appointments(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    p = parse_message(text) or {}
    assert (p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "appointment"
    a = build_app_guide_message("appointment")
    assert "Arrived" in a and "evening before" in a and "Settings" in a


# ── The customer booking link ────────────────────────────────────────────────
def _link(cook, phone, **settings):
    from booking_link import make_token
    from models import User
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"booking_link": True, **settings}})
    db = SessionLocal()
    try:
        return make_token(db.query(User).filter(User.phone == phone).first())
    finally:
        db.close()


def _next_open_day():
    from appointments import lagos_now
    d = lagos_now().date() + timedelta(days=2)
    while d.weekday() == 6:                                   # closed on Sunday by default
        d += timedelta(days=1)
    return d.isoformat()


def test_booking_link_request_confirm_and_decline():
    phone, cook, cut, ada = _salon()
    from booking_link import make_token
    from models import User
    db = SessionLocal()
    tok = make_token(db.query(User).filter(User.phone == phone).first()); db.close()
    assert client.get(f"/app/api/public/book/{tok}").status_code == 404     # off until switched on
    tok = _link(cook, phone)
    assert client.get("/app/api/public/book/b1-badsig").status_code == 404

    pg = client.get(f"/app/api/public/book/{tok}").json()
    assert pg["services"] == [{"id": cut, "name": "haircut", "price": 3000}] and pg["confirm"] is True
    day = _next_open_day()
    times = client.get(f"/app/api/public/book/{tok}/times?date={day}").json()["times"]
    assert times[0] == "08:00" and times[-1] == "17:30"

    r = client.post(f"/app/api/public/book/{tok}", json={
        "date": day, "time": "10:00", "service_ids": [cut], "name": "kemi obi", "phone": "08031112222"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "requested"
    # one person (the owner) does the work, so 10:00 is no longer free
    assert "10:00" not in client.get(f"/app/api/public/book/{tok}/times?date={day}").json()["times"]
    assert client.post(f"/app/api/public/book/{tok}", json={
        "date": day, "time": "10:00", "service_ids": [cut], "name": "Bayo", "phone": "08034443333"}).status_code == 400

    lst = client.get(f"/app/api/appointments?day={day}", cookies=cook).json()
    req = lst["requests"][0]
    assert req["customer"] == {"id": None, "name": "Kemi Obi", "phone": "2348031112222"} and req["status"] == "requested"
    assert client.post(f"/app/api/appointments/{req['id']}/done", cookies=cook, json={"paid": 0}).status_code == 400
    db = SessionLocal()
    try:
        n = db.query(AppNotification).filter(AppNotification.owner_phone == phone,
                                             AppNotification.event_type == "booking_request").one()
        assert "Kemi Obi" in n.title and n.link == "/appointments"
    finally:
        db.close()

    ok = client.post(f"/app/api/appointments/{req['id']}/confirm", cookies=cook).json()
    assert ok["status"] == "booked" and ok["customer"]["id"]
    assert any(to == "2348031112222" and "you're booked" in m for to, m in sent)

    r2 = client.post(f"/app/api/public/book/{tok}", json={
        "date": day, "time": "11:00", "service_ids": [cut], "name": "Kemi Obi", "phone": "2348031112222"}).json()
    req2 = client.get(f"/app/api/appointments?day={day}", cookies=cook).json()["requests"][0]
    assert r2["status"] == "requested"
    d = client.post(f"/app/api/appointments/{req2['id']}/decline", cookies=cook, json={"reason": "We're full."}).json()
    assert d["status"] == "declined"
    assert any("can't take your booking" in m and "We're full." in m for _to, m in sent)
    # the second request reused Kemi's customer record on confirm? — declined, so no new customer
    db = SessionLocal()
    try:
        assert db.query(Customer).filter(Customer.owner_phone == phone, Customer.name.ilike("kemi obi")).count() == 1
    finally:
        db.close()


def test_booking_link_auto_confirm_staff_and_limits():
    phone, cook, cut, ada = _salon()
    tok = _link(cook, phone, booking_auto_confirm=True, booking_pick_staff=True, booking_slot_min=60,
                booking_hours={"mon": ["09:00", "12:00"], "tue": ["09:00", "12:00"], "wed": ["09:00", "12:00"],
                               "thu": ["09:00", "12:00"], "fri": ["09:00", "12:00"], "sat": ["09:00", "12:00"],
                               "sun": None})
    pg = client.get(f"/app/api/public/book/{tok}").json()
    assert pg["confirm"] is False and len(pg["staff"]) == 1
    day = _next_open_day()
    assert client.get(f"/app/api/public/book/{tok}/times?date={day}").json()["times"] == ["09:00", "10:00", "11:00"]
    r = client.post(f"/app/api/public/book/{tok}", json={
        "date": day, "time": "09:00", "service_ids": [cut], "name": "Tola", "phone": "08035550000",
        "staff_user_id": pg["staff"][0]["id"]}).json()
    assert r["status"] == "booked"
    assert any(to == "2348035550000" and "you're booked" in m for to, m in sent)
    # junk guard: bad phone, no service, too far ahead
    bad = {"date": day, "time": "10:00", "service_ids": [cut], "name": "X", "phone": "123"}
    assert client.post(f"/app/api/public/book/{tok}", json=bad).status_code == 400
    assert client.post(f"/app/api/public/book/{tok}", json={**bad, "name": "Yemi", "phone": "08030000001",
                                                           "service_ids": []}).status_code == 400
    far = (datetime.fromisoformat(day) + timedelta(days=60)).date().isoformat()
    assert client.post(f"/app/api/public/book/{tok}", json={**bad, "name": "Yemi", "phone": "08030000001",
                                                           "date": far}).status_code == 400
    assert client.put("/app/api/settings/business", cookies=cook,
                      json={"values": {"booking_hours": {"mon": ["18:00", "09:00"]}}}).status_code == 400
