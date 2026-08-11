"""
Supplier payment-due reminders: the proactive scheduler notifies owners (web
owners included) when a supplier purchase is due and still owing, and stays
quiet once the supplier balance is settled.
"""
import os
from datetime import datetime, timezone, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import User, Supplier, SupplierPurchase, SupplierPayment, AppNotification
import proactive_scheduler


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _today_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_web_owner_gets_supplier_due_reminder(monkeypatch):
    monkeypatch.setattr(proactive_scheduler, "send_whatsapp_message", lambda *a, **k: True, raising=False)
    db = _db()
    db.add(User(id="o1", phone="2348002220001", name="WebOwner", role="owner", parent_id=None))
    sup = Supplier(name="dangote", owner_phone="2348002220001")
    db.add(sup); db.commit()
    db.add(SupplierPurchase(
        supplier_id=sup.id, owner_phone="2348002220001", product="cement",
        quantity=10, total=100000, paid_amount=0, due_date=_today_naive(),
    ))
    db.commit()

    proactive_scheduler._check_supplier_due(db)

    notes = db.query(AppNotification).filter(
        AppNotification.owner_phone == "2348002220001",
        AppNotification.event_type.like("supplier_due_%"),
    ).all()
    assert len(notes) == 1, "owner should get a supplier-due reminder"
    assert "Dangote" in notes[0].body
    db.close()


def test_settled_supplier_gets_no_reminder(monkeypatch):
    monkeypatch.setattr(proactive_scheduler, "send_whatsapp_message", lambda *a, **k: True, raising=False)
    db = _db()
    db.add(User(id="o2", phone="2348002220002", name="Owner2", role="owner", parent_id=None))
    sup = Supplier(name="bua", owner_phone="2348002220002")
    db.add(sup); db.commit()
    db.add(SupplierPurchase(
        supplier_id=sup.id, owner_phone="2348002220002", product="cement",
        quantity=10, total=100000, paid_amount=0, due_date=_today_naive(),
    ))
    # A later payment clears the whole balance.
    db.add(SupplierPayment(supplier_id=sup.id, owner_phone="2348002220002", amount=100000))
    db.commit()

    proactive_scheduler._check_supplier_due(db)

    assert db.query(AppNotification).filter(
        AppNotification.owner_phone == "2348002220002").count() == 0
    db.close()


def test_far_future_due_not_yet_reminded(monkeypatch):
    monkeypatch.setattr(proactive_scheduler, "send_whatsapp_message", lambda *a, **k: True, raising=False)
    db = _db()
    db.add(User(id="o3", phone="2348002220003", name="Owner3", role="owner", parent_id=None))
    sup = Supplier(name="ayo", owner_phone="2348002220003")
    db.add(sup); db.commit()
    db.add(SupplierPurchase(
        supplier_id=sup.id, owner_phone="2348002220003", product="rice",
        quantity=5, total=50000, paid_amount=0, due_date=_today_naive() + timedelta(days=10),
    ))
    db.commit()

    proactive_scheduler._check_supplier_due(db)

    assert db.query(AppNotification).filter(
        AppNotification.owner_phone == "2348002220003").count() == 0
    db.close()
