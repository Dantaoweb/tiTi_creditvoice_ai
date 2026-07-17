"""
Product-before-quantity parsing + variant list display.

Traders phrase sales either way round — "3 crates egg" and "egg 3 crates" —
and the parser must read the product, quantity and unit correctly in both. The
product-first form only claims the trailing word as a unit when it is a real
unit (so "a4 paper" keeps quantity 1), which keeps it from stealing normal
products.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from parser import parse_invoice_item, parse_message
from select_product_commands import build_product_list_message


class _Item:
    def __init__(self, name, unit, price, qty=0):
        self.name, self.unit, self.selling_price, self.quantity = name, unit, price, qty


# ── Product-before-quantity ordering ──────────────────────────────────────────

def test_invoice_item_product_first_with_unit_and_total():
    assert parse_invoice_item("egg 3 crates for 15000") == {
        "product": "egg", "quantity": 3, "unit": "crate",
        "unit_price": 5000, "total": 15000,
    }


def test_invoice_item_product_first_each():
    assert parse_invoice_item("egg 3 crates at 5000 each") == {
        "product": "egg", "quantity": 3, "unit": "crate",
        "unit_price": 5000, "total": 15000,
    }


def test_invoice_item_qty_first_still_works():
    assert parse_invoice_item("3 crates egg for 15000")["product"] == "egg"


def test_product_with_number_is_not_treated_as_quantity():
    # "a4 paper" must not read "4"/"paper" as qty/unit
    r = parse_invoice_item("a4 paper 2000")
    assert r["product"] == "a4 paper" and r["quantity"] == 1


def test_full_sentence_product_first():
    p = parse_message("i sold egg 3 crates to Ayo for 15000")
    assert p["product"] == "egg"
    assert p["quantity"] == 3
    assert p["unit"] == "crate"
    assert p["buy_amount"] == 15000
    assert p["name"].lower() == "ayo"


def test_full_sentence_qty_first_regression():
    p = parse_message("Ayo bought 3 crates of egg at 5000 each")
    assert p["product"] == "egg" and p["quantity"] == 3 and p["unit"] == "crate"


def test_bare_product_amount_regression():
    p = parse_message("olu buy mango 500")
    assert p["product"] == "mango" and p["buy_amount"] == 500


# ── Variant list shows units ──────────────────────────────────────────────────

def test_variant_list_shows_units_to_disambiguate():
    msg = build_product_list_message([
        _Item("sugar", "bag", 5000, 3),
        _Item("sugar", "cube", 300, 0),
        _Item("sugar cube", "pack", 1200, 10),
    ])
    assert "Sugar (bag) - N5,000 (3 in stock)" in msg
    assert "Sugar (cube) - N300" in msg          # no stock tag when qty is 0
    assert "Sugar Cube (pack) - N1,200 (10 in stock)" in msg
    assert "3.0" not in msg                        # REAL quantity rendered clean
