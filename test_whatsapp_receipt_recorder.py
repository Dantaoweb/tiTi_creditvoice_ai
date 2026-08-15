"""
The WhatsApp receipt (sent to the customer) credits the staff who recorded the
sale in a "Recorded by:" line, so an owner can see who issued it.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-wa-recorder-00000000")

from main import app  # noqa: F401  — ensures tables/schema exist
from database import SessionLocal
from models import User, Customer, Transaction


def test_reprint_receipt_credits_the_recorder():
    from customer_commands import _build_reprint_receipt
    db = SessionLocal()
    try:
        staff = User(phone="234800000777", name="Staff Ada", role="user")
        db.add(staff); db.flush()
        cust = Customer(name="Bola", owner_phone="234800000777")
        db.add(cust); db.flush()
        tx = Transaction(customer_id=cust.id, type="SALE", amount=5000,
                         product="rice", recorded_by_id=staff.id)
        db.add(tx); db.flush()
        receipt = _build_reprint_receipt(db, "Ada Stores", "234800000777", cust, tx, 0, None)
        assert "Recorded by: Staff Ada" in receipt
    finally:
        db.rollback(); db.close()
