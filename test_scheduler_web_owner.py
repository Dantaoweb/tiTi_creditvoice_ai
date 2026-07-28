"""
Regression: proactive alerts/reminders reach WEB-registered owners (role
"owner"), not just WhatsApp ones (role "user"). The scheduler used to filter
owners by role == "user", excluding every web owner.
"""
import os
from datetime import datetime, timezone, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import User, Customer, AppNotification
import proactive_scheduler


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _overdue_customer(db, owner_phone):
    # _check_overdue_debt reads the denormalised Customer columns directly, so
    # set them (a Transaction insert would reset last_transaction_at to now).
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    c = Customer(name="Debtor", owner_phone=owner_phone, balance=5000, last_transaction_at=old)
    db.add(c); db.commit()
    return c


def test_web_owner_role_owner_gets_overdue_alert(monkeypatch):
    # Don't actually hit WhatsApp
    monkeypatch.setattr(proactive_scheduler, "send_whatsapp_message", lambda *a, **k: True, raising=False)
    db = _db()
    db.add(User(id="o1", phone="2348001110001", name="WebOwner", role="owner", parent_id=None))
    db.commit()
    _overdue_customer(db, "2348001110001")

    proactive_scheduler._check_overdue_debt(db)

    notes = db.query(AppNotification).filter(
        AppNotification.owner_phone == "2348001110001",
        AppNotification.event_type == "overdue_debt",
    ).all()
    assert len(notes) == 1, "web owner (role 'owner') should get the overdue-debt alert"
    db.close()


def test_whatsapp_owner_role_user_still_gets_alert(monkeypatch):
    monkeypatch.setattr(proactive_scheduler, "send_whatsapp_message", lambda *a, **k: True, raising=False)
    db = _db()
    db.add(User(id="o2", phone="2348001110002", name="WaOwner", role="user", parent_id=None))
    db.commit()
    _overdue_customer(db, "2348001110002")

    proactive_scheduler._check_overdue_debt(db)
    assert db.query(AppNotification).filter(
        AppNotification.owner_phone == "2348001110002").count() == 1
    db.close()
