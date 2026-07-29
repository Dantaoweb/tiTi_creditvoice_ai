"""
Receipt numbers are per-business (1, 2, 3 for each business), not the global
transaction id.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import User
from web_pos import save_pos_sale, get_pos_receipt


def _db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _sale(db, owner_phone, owner_id):
    r = save_pos_sale(db, owner_phone, owner_id, None,
                      [{"name": "x", "qty": 1, "unit_price": 100}], 100)
    rec = get_pos_receipt(db, r["receipt_id"], user=db.query(User).filter(User.phone == owner_phone).first())
    return rec["receipt_number"], r["receipt_id"]


def test_receipt_numbers_are_per_business():
    db = _db()
    db.add(User(id="a", phone="234800000111", name="A", role="owner"))
    db.add(User(id="b", phone="234800000222", name="B", role="owner"))
    db.commit()

    # Business A: three sales → 1, 2, 3
    a_nums = [_sale(db, "234800000111", "a")[0] for _ in range(3)]
    assert a_nums == [1, 2, 3]

    # Business B starts fresh at 1, even though global tx ids continue
    b_num, b_txid = _sale(db, "234800000222", "b")
    assert b_num == 1
    assert b_txid > 3            # global id kept climbing; the receipt # did not
