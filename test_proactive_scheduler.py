"""
The proactive scheduler must run every check each cycle. The inactivity check
used Transaction.owner_phone (no such column), so it raised on every cycle with
at least one owner — and because the cycle wasn't isolated, every check after it
(reminders, delivery/supplier/savings due, subscription expiry, balance
reconciliation, purges) silently never ran.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-proactive-sched-0000000000")

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import AppNotification, Customer, ProactiveLog, Transaction, User, utcnow
import proactive_scheduler as ps

client = TestClient(app)
_seq = iter(range(1000, 2000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    phone = f"234849{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ada Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _add_tx(phone, days_ago, with_customer=True):
    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.phone == phone).first().id
        cid = None
        if with_customer:
            c = Customer(owner_phone=phone, name=f"c{next(_seq)}", balance=0)
            db.add(c); db.flush(); cid = c.id
        db.add(Transaction(customer_id=cid, type="SALE", amount=100, recorded_by_id=uid,
                           created_at=utcnow() - timedelta(days=days_ago)))
        db.commit()
    finally:
        db.close()


def _inactivity_notifs(phone):
    db = SessionLocal()
    try:
        return db.query(AppNotification).filter(
            AppNotification.owner_phone == phone, AppNotification.event_type == "inactivity",
        ).count()
    finally:
        db.close()


def _run(check):
    db = SessionLocal()
    try:
        return check(db)
    finally:
        db.close()


def test_inactivity_check_runs_and_nudges_idle_owner():
    idle, _ = _owner()
    _add_tx(idle, days_ago=5)                          # sale to a customer
    idle_direct, _ = _owner()
    _add_tx(idle_direct, days_ago=5, with_customer=False)   # direct sale, no customer
    active, _ = _owner()
    _add_tx(active, days_ago=5)
    _add_tx(active, days_ago=0)                        # recorded today

    _run(ps._check_inactivity)   # used to raise AttributeError

    assert _inactivity_notifs(idle) == 1
    assert _inactivity_notifs(idle_direct) == 1
    assert _inactivity_notifs(active) == 0

    _run(ps._check_inactivity)   # weekly cooldown: no second nudge
    assert _inactivity_notifs(idle) == 1


def test_last_transaction_attributes_staff_sales_to_owner():
    owner, _ = _owner()
    db = SessionLocal()
    try:
        boss = db.query(User).filter(User.phone == owner).first()
        staff = User(phone=f"234850{next(_seq):06d}", name="Staff", parent_id=boss.id)
        db.add(staff); db.flush()
        when = utcnow() - timedelta(days=4)
        db.add(Transaction(customer_id=None, type="SALE", amount=50, recorded_by_id=staff.id, created_at=when))
        db.commit()
        last = ps._last_transaction_by_owner(db)
        assert abs((last[owner] - when).total_seconds()) < 1
    finally:
        db.close()


def test_one_failing_check_does_not_stop_the_rest(monkeypatch):
    ran = []

    def boom(db):
        raise RuntimeError("broken check")

    def ok(db):
        ran.append("ok")

    monkeypatch.setattr(ps, "_CHECKS", (boom, ok))
    failed = _run(ps.run_proactive_cycle)
    assert failed == ["boom"] and ran == ["ok"]


def test_full_cycle_has_no_failures_with_real_owners():
    owner, _ = _owner()
    _add_tx(owner, days_ago=10)
    assert _run(ps.run_proactive_cycle) == []


def test_personal_data_request_works():
    owner, cook = _owner()
    _add_tx(owner, days_ago=1)
    _add_tx(owner, days_ago=1, with_customer=False)
    r = client.get("/app/api/account/personal-data", cookies=cook)
    assert r.status_code == 200, r.text
    assert r.json()["data_held"]["transactions"] == 2
