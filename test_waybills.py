"""
Waybills / loading orders and selling more than is in the store.

Bello has 40 bags of cement. Ade buys 100: 40 go out, 60 are owed (still to
deliver) — not lost the way stock used to just stop at 0. When 100 new bags
arrive the owner decides whether to keep Ade's 60 aside; each waybill takes
out only what is in the store for him, and cancelling one puts it back.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app_settings import set_business_settings
from database import Base
from deliveries import DeliveryError, goods_to_deliver, owed_by_item, reserved_by_item, set_kept_aside
from inventory_suppliers import restore_inventory_for_voided_sale
from invoices import (
    InvoiceError, cancel_invoice, create_invoice, deliver_invoice, update_invoice,
)
from models import Customer, InventoryItem, Transaction, User, Waybill
from waybills import (
    WaybillError, cancel_waybill, create_waybill, sale_waybill_lines, waybill_document,
    waybill_note_text,
)
from web_pos import save_pos_sale

OWNER = "2348007000009"


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    s.add(User(id="owner-1", phone=OWNER, name="Bello Cement"))
    s.add(InventoryItem(owner_phone=OWNER, name="cement", unit="bag", quantity=40,
                        selling_price=9000, cost_price=8000, is_available=True))
    s.add(Customer(owner_phone=OWNER, name="ade", customer_phone="2348031111111"))
    s.add(Customer(owner_phone=OWNER, name="bisi", customer_phone="2348031111112"))
    s.commit()
    yield s
    s.close()


def _cement(db):
    return db.query(InventoryItem).filter_by(owner_phone=OWNER, name="cement").one()


def _cust(db, name="ade"):
    return db.query(Customer).filter_by(owner_phone=OWNER, name=name).one()


def _sell(db, qty, delivered=None, who="ade"):
    item = {"inventory_item_id": _cement(db).id, "name": "cement", "qty": qty,
            "unit": "bag", "unit_price": 9000}
    if delivered is not None:
        item["delivered_qty"] = delivered
    return save_pos_sale(db, OWNER, "owner-1", _cust(db, who).id if who else None, [item], 0)


def _restock(db, n):
    _cement(db).quantity += n
    db.commit()


def _key(db):
    return f"i:{_cement(db).id}"


def test_selling_short_keeps_what_is_owed(db):
    _sell(db, 100, delivered=40)
    assert _cement(db).quantity == 0
    [row] = goods_to_deliver(db, OWNER, _cust(db).id)
    assert (row["remaining"], row["kept"], row["can_send"]) == (60, 0, 0)
    owed = owed_by_item(db, OWNER)[_cement(db).id]
    assert owed["waiting"] == 60 and owed["kept"] == 0
    assert owed["customers"] == [{"name": "Ade", "quantity": 60}]


def test_switched_off_a_short_sale_is_refused(db):
    set_business_settings(db, OWNER, {"allow_negative_stock": False})
    with pytest.raises(ValueError, match="only 40 bag in stock"):
        _sell(db, 100, delivered=40)


def test_new_stock_is_free_until_the_owner_keeps_it_aside(db):
    _sell(db, 100, delivered=40)
    _restock(db, 100)
    assert reserved_by_item(db, OWNER) == {}                 # not forced on anyone
    _sell(db, 10, who="bisi")                                # can still be sold
    assert _cement(db).quantity == 90

    set_kept_aside(db, OWNER, _cust(db).id, _key(db), 60)
    db.commit()
    assert reserved_by_item(db, OWNER) == {_cement(db).id: 60}
    with pytest.raises(ValueError, match="Only 30 bag of Cement can be sold — 60 are kept aside"):
        _sell(db, 31, who="bisi")
    # Release: owed still, sellable again
    set_kept_aside(db, OWNER, _cust(db).id, _key(db), 0)
    assert reserved_by_item(db, OWNER) == {}
    assert goods_to_deliver(db, OWNER)[0]["remaining"] == 60
    # Can't keep aside more than is in the store
    _sell(db, 50, who="bisi")                                    # 40 left
    with pytest.raises(DeliveryError, match="Only 40 bag of Cement in store is free to keep aside"):
        set_kept_aside(db, OWNER, _cust(db).id, _key(db), 60)


def test_waybills_send_only_what_is_in_the_store(db):
    _sell(db, 100, delivered=40)
    with pytest.raises(WaybillError, match="Only 0 bag of Cement can go out now"):
        create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id,
                       lines=[{"key": _key(db), "quantity": 10}])
    db.rollback()
    _restock(db, 25)
    wb = create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id,
                        lines=[{"key": _key(db), "quantity": 25}],
                        details={"driver_name": "Musa", "vehicle": "KJA 123 XY", "loaders": "Sule, Tunde"})
    db.commit()
    assert _cement(db).quantity == 0
    [row] = goods_to_deliver(db, OWNER)
    assert row["remaining"] == 35

    doc = waybill_document(db, wb)
    assert doc["number"] == "WB-0001" and doc["vehicle"] == "KJA 123 XY"
    assert doc["lines"] == [{"product": "Cement", "unit": "bag", "quantity": 25, "handed_over": False}]
    assert doc["still_to_deliver"] == [{"product": "Cement", "unit": "bag", "quantity": 35}]
    assert "price" not in str(doc["lines"]) and "9000" not in waybill_note_text(doc)
    assert "Still to deliver" in waybill_note_text(doc)

    # The rest, in parts, once stock arrives
    _restock(db, 100)
    create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id, lines=[{"key": _key(db), "quantity": 20}])
    wb3 = create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id, lines=[{"key": _key(db), "quantity": 15}])
    db.commit()
    assert goods_to_deliver(db, OWNER) == [] and _cement(db).quantity == 65
    assert "All delivered" in waybill_note_text(waybill_document(db, wb3))


def test_kept_aside_goods_go_first(db):
    _sell(db, 30, delivered=0)                       # 40 in store: 30 kept for Ade
    assert reserved_by_item(db, OWNER) == {_cement(db).id: 30}
    create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id, lines=[{"key": _key(db), "quantity": 10}])
    db.commit()
    assert reserved_by_item(db, OWNER) == {_cement(db).id: 20} and _cement(db).quantity == 30


def test_keep_aside_setting_off(db):
    set_business_settings(db, OWNER, {"keep_aside": False})
    _sell(db, 30, delivered=0)
    assert reserved_by_item(db, OWNER) == {}
    assert goods_to_deliver(db, OWNER)[0]["remaining"] == 30
    _sell(db, 40, who="bisi")                        # all 40 free to sell


def test_cancelling_a_waybill_puts_the_goods_back(db):
    _sell(db, 30, delivered=0)
    wb = create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id, lines=[{"key": _key(db), "quantity": 30}])
    db.commit()
    assert _cement(db).quantity == 10 and goods_to_deliver(db, OWNER) == []
    with pytest.raises(WaybillError, match="Say why"):
        cancel_waybill(db, OWNER, "owner-1", wb, "")
    cancel_waybill(db, OWNER, "owner-1", wb, "Truck broke down")
    db.commit()
    assert _cement(db).quantity == 40
    assert goods_to_deliver(db, OWNER)[0]["remaining"] == 30
    assert reserved_by_item(db, OWNER) == {_cement(db).id: 30}    # kept aside again
    with pytest.raises(WaybillError, match="already cancelled"):
        cancel_waybill(db, OWNER, "owner-1", wb, "again")


def test_voiding_the_sale_returns_waybill_stock_once(db):
    sale = _sell(db, 30, delivered=0)
    wb = create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id, lines=[{"key": _key(db), "quantity": 30}])
    db.commit()
    assert wb.transaction_id == sale["receipt_id"]               # one sale → linked to its receipt
    tx = db.query(Transaction).get(sale["receipt_id"])
    tx.is_voided = True
    restore_inventory_for_voided_sale(db, OWNER, tx.id)
    from deliveries import on_transaction_voided
    on_transaction_voided(db, OWNER, tx, "owner-1")
    db.commit()
    assert _cement(db).quantity == 40
    assert db.query(Waybill).get(wb.id).cancelled_at is not None


def test_cancel_then_void_does_not_return_twice(db):
    sale = _sell(db, 30, delivered=0)
    wb = create_waybill(db, OWNER, "owner-1", customer_id=_cust(db).id, lines=[{"key": _key(db), "quantity": 30}])
    cancel_waybill(db, OWNER, "owner-1", wb, "Wrong truck")
    db.commit()
    restore_inventory_for_voided_sale(db, OWNER, sale["receipt_id"])
    db.commit()
    assert _cement(db).quantity == 40


def test_waybill_for_an_ordinary_sale_is_paperwork(db):
    sale = _sell(db, 20)
    assert _cement(db).quantity == 20
    tx = db.query(Transaction).get(sale["receipt_id"])
    [line] = sale_waybill_lines(db, OWNER, tx)
    assert line["handed_over"] is True and line["max"] == 20
    wb = create_waybill(db, OWNER, "owner-1", tx=tx, lines=[{"line_id": line["line_id"], "quantity": 20}])
    db.commit()
    assert _cement(db).quantity == 20                            # not taken twice
    assert waybill_document(db, wb)["lines"][0]["handed_over"] is True
    cancel_waybill(db, OWNER, "owner-1", wb, "Printed twice")
    db.commit()
    assert _cement(db).quantity == 20


def test_receipt_waybill_loads_what_was_delivered_now(db):
    """10 bags sold, 1 delivered now, 9 to deliver: the waybill carries the 1
    being loaded; the 9 are shown as still to deliver and stay in stock."""
    sale = _sell(db, 10, delivered=1)
    assert _cement(db).quantity == 39
    tx = db.query(Transaction).get(sale["receipt_id"])
    now, later = sale_waybill_lines(db, OWNER, tx)
    assert (now["kind"], now["max"], now["suggest"]) == ("at_sale", 1, 1)
    assert (later["kind"], later["to_deliver"], later["suggest"]) == ("to_deliver", 9, 0)
    wb = create_waybill(db, OWNER, "owner-1", tx=tx,
                        lines=[{"line_id": now["line_id"], "quantity": 1, "kind": "at_sale"}])
    db.commit()
    assert _cement(db).quantity == 39                            # not taken again
    doc = waybill_document(db, wb)
    assert doc["lines"] == [{"product": "Cement", "unit": "bag", "quantity": 1, "handed_over": True}]
    assert doc["still_to_deliver"] == [{"product": "Cement", "unit": "bag", "quantity": 9}]
    assert "Still to deliver" in waybill_note_text(doc)
    # Listed once: the next waybill doesn't suggest it again
    now, _later = sale_waybill_lines(db, OWNER, tx)
    assert (now["suggest"], now["listed"]) == (0, 1)
    with pytest.raises(WaybillError, match="Only 1 Cement went out at the sale"):
        create_waybill(db, OWNER, "owner-1", tx=tx,
                       lines=[{"line_id": now["line_id"], "quantity": 2, "kind": "at_sale"}])
    db.rollback()


def test_receipt_waybill_can_send_what_is_left(db):
    sale = _sell(db, 30, delivered=10)
    tx = db.query(Transaction).get(sale["receipt_id"])
    _now, line = sale_waybill_lines(db, OWNER, tx)
    assert (line["to_deliver"], line["max"]) == (20, 20)
    with pytest.raises(WaybillError, match="Only 20 Cement still to deliver"):
        create_waybill(db, OWNER, "owner-1", tx=tx, lines=[{"line_id": line["line_id"], "quantity": 21}])
    db.rollback()
    with pytest.raises(WaybillError, match="Tick at least one"):
        create_waybill(db, OWNER, "owner-1", tx=tx, lines=[{"line_id": line["line_id"], "quantity": 0}])
    db.rollback()
    create_waybill(db, OWNER, "owner-1", tx=tx,
                   lines=[{"line_id": line["line_id"], "quantity": 20, "kind": "to_deliver"}])
    db.commit()
    assert _cement(db).quantity == 10 and goods_to_deliver(db, OWNER) == []


def test_invoice_goes_out_in_parts(db):
    inv = create_invoice(db, OWNER, "owner-1", _cust(db).id, [
        {"inventory_item_id": _cement(db).id, "name": "cement", "qty": 10, "unit": "bag", "unit_price": 9000}])
    from models import InvoiceItem
    r = db.query(InvoiceItem).filter_by(invoice_id=inv.id).one()
    wb = create_waybill(db, OWNER, "owner-1", inv=inv, lines=[{"line_id": r.id, "quantity": 4}])
    db.commit()
    assert _cement(db).quantity == 36 and inv.delivered_at is None
    assert waybill_document(db, wb)["still_to_deliver"] == [{"product": "Cement", "unit": "bag", "quantity": 6}]
    with pytest.raises(InvoiceError, match="already gone out"):
        update_invoice(db, inv, [{"name": "cement", "qty": 1, "unit_price": 9000}])
    with pytest.raises(InvoiceError, match="already gone out"):
        cancel_invoice(db, inv)
    deliver_invoice(db, inv, "owner-1")                          # the rest
    assert _cement(db).quantity == 30 and inv.delivered_at is not None
    # Cancel the first waybill: 4 back, invoice no longer fully delivered
    cancel_waybill(db, OWNER, "owner-1", wb, "Returned to yard")
    db.commit()
    assert _cement(db).quantity == 34 and inv.delivered_at is None


def test_invoice_waybill_finishing_marks_it_delivered(db):
    inv = create_invoice(db, OWNER, "owner-1", _cust(db).id, [
        {"inventory_item_id": _cement(db).id, "name": "cement", "qty": 10, "unit": "bag", "unit_price": 9000}])
    from models import InvoiceItem
    r = db.query(InvoiceItem).filter_by(invoice_id=inv.id).one()
    _sell(db, 35, delivered=0, who="bisi")                       # 35 of the 40 kept for Bisi
    with pytest.raises(WaybillError, match="Only 5 bag of Cement can go out now"):
        create_waybill(db, OWNER, "owner-1", inv=inv, lines=[{"line_id": r.id, "quantity": 10}])
    db.rollback()
    create_waybill(db, OWNER, "owner-1", inv=inv, lines=[{"line_id": r.id, "quantity": 5}])
    _restock(db, 5)
    create_waybill(db, OWNER, "owner-1", inv=inv, lines=[{"line_id": r.id, "quantity": 5}])
    db.commit()
    assert inv.delivered_at is not None and _cement(db).quantity == 35
