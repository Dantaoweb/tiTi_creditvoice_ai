"""
"sell <product>" shortcut into the select-product flow
======================================================
"sell sugar" / "select sugar" / "i want to sell sugar" (no amount) jumps into
the guided select-product flow scoped to that product: one match goes straight
to the quantity step, several variants show a filtered list, no match gets a
helpful pointer. With an amount present ("sell sugar 500") the normal
direct-sale parsing still applies.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from constants import ACTION_SELECT_PRODUCT_LIST, ACTION_SELECT_PRODUCT_QTY
from database import Base
from models import InventoryItem, PendingAction
from parser import parse_message
from select_product_commands import start_select_product

OWNER = "2348001111111"
PHONE = "2348001111111"


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    db.add_all([
        InventoryItem(owner_phone=OWNER, name="sugar", unit="bag",
                      selling_price=55000, quantity=10, is_available=True),
        InventoryItem(owner_phone=OWNER, name="sugar cube", unit="pack",
                      selling_price=800, quantity=30, is_available=True),
        InventoryItem(owner_phone=OWNER, name="rice", unit="bag",
                      selling_price=75000, quantity=5, is_available=True),
    ])
    db.commit()


class Sender:
    def __init__(self):
        self.messages = []

    def __call__(self, phone, text):
        self.messages.append(text)


# ── Parser ────────────────────────────────────────────────────────────────────

def test_parser_sell_product_variants():
    for text in ("sell sugar", "select sugar", "i want to sell sugar", "SELL Sugar"):
        p = parse_message(text)
        assert p and p["type"] == "SELECT_PRODUCT" and p.get("product") == "sugar", text


def test_parser_plain_select_product_unchanged():
    p = parse_message("select product")
    assert p == {"type": "SELECT_PRODUCT"}


def test_parser_sell_with_amount_is_not_shortcut():
    p = parse_message("sell sugar 500")
    assert not (p and p.get("type") == "SELECT_PRODUCT")


# ── Regression: products beyond the alphabetical browse page ─────────────────
def test_product_late_in_alphabet_is_found_by_name():
    """The bug: 'select panadol' searched only the first page, so a product past
    the cut-off (P after 40 'a…' items) could never be selected."""
    db = make_db()
    for i in range(45):
        db.add(InventoryItem(owner_phone=OWNER, name=f"aaa item {i:02d}", unit="pc",
                             selling_price=100, quantity=5, is_available=True))
    db.add(InventoryItem(owner_phone=OWNER, name="panadol", unit="pack",
                         selling_price=200, quantity=10, is_available=True))
    db.commit()

    sender = Sender()
    res = start_select_product(db, PHONE, OWNER, sender, product_query="panadol")
    assert res["status"] == "select_product_qty_asked"
    assert any("Panadol" in m for m in sender.messages)
    pending = db.query(PendingAction).filter(PendingAction.phone == PHONE).first()
    assert pending.action == ACTION_SELECT_PRODUCT_QTY
    assert json.loads(pending.payload_json)["selected_name"] == "panadol"


def test_browse_shows_search_hint_when_truncated():
    db = make_db()
    for i in range(45):
        db.add(InventoryItem(owner_phone=OWNER, name=f"item {i:02d}", unit="pc",
                             selling_price=100, quantity=5, is_available=True))
    db.commit()
    sender = Sender()
    res = start_select_product(db, PHONE, OWNER, sender)
    assert res["status"] == "select_product_list"
    assert any("of 45" in m for m in sender.messages)


def test_parser_bare_sell_is_not_shortcut():
    p = parse_message("sell")
    assert not (p and p.get("type") == "SELECT_PRODUCT" and p.get("product"))


# ── Flow scoping ──────────────────────────────────────────────────────────────

def test_single_match_goes_straight_to_quantity():
    db = make_db()
    seed(db)
    send = Sender()
    r = start_select_product(db, PHONE, OWNER, send, product_query="rice")
    assert r["status"] == "select_product_qty_asked"
    pending = db.query(PendingAction).filter(PendingAction.phone == PHONE).first()
    assert pending.action == ACTION_SELECT_PRODUCT_QTY
    payload = json.loads(pending.payload_json)
    assert payload["selected_name"] == "rice"
    assert len(payload["item_ids"]) == 3          # full list kept for "add another"
    assert "Quantity for Rice?" in send.messages[-1]


def test_variants_show_filtered_list_only():
    db = make_db()
    seed(db)
    send = Sender()
    r = start_select_product(db, PHONE, OWNER, send, product_query="sugar")
    assert r["status"] == "select_product_list"
    pending = db.query(PendingAction).filter(PendingAction.phone == PHONE).first()
    assert pending.action == ACTION_SELECT_PRODUCT_LIST
    payload = json.loads(pending.payload_json)
    assert len(payload["item_ids"]) == 2          # sugar + sugar cube, not rice
    listing = send.messages[-1]
    assert "Sugar" in listing and "Rice" not in listing


def test_no_match_gets_helpful_pointer():
    db = make_db()
    seed(db)
    send = Sender()
    r = start_select_product(db, PHONE, OWNER, send, product_query="cement")
    assert r["status"] == "select_product_no_match"
    assert "No product matching 'cement'" in send.messages[-1]
    assert db.query(PendingAction).filter(PendingAction.phone == PHONE).count() == 0


def test_no_query_lists_everything_as_before():
    db = make_db()
    seed(db)
    send = Sender()
    r = start_select_product(db, PHONE, OWNER, send)
    assert r["status"] == "select_product_list"
    payload = json.loads(
        db.query(PendingAction).filter(PendingAction.phone == PHONE).first().payload_json
    )
    assert len(payload["item_ids"]) == 3
