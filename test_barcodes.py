"""
Selling by scan.

A scanner is a keyboard — it types the code and presses Enter — so the work is
not hardware, it is making one code mean exactly one product and finding it
fast. Two rules carry the feature:

A code points at one product only. Two products answering the same scan means
the till charges the wrong price and nobody notices until stock-take.

And scanning stays optional. A shop selling rice by the congo has nothing to
scan and must be no worse off than it is today.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-barcodes-00000000000")

import pytest
from fastapi.testclient import TestClient

import barcodes
import web_auth
from database import SessionLocal
from main import app
from models import InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 900))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


@pytest.fixture
def shop():
    phone = f"23480901401{next(_seq)}"
    client.post("/app/api/auth/register",
                json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login",
                          json={"phone": phone, "pin": "5678"}).cookies
    return {"phone": phone, "cookies": cookies}


def _add(shop, name, barcode=None, price=1_000, qty=10):
    body = {"owner_phone": shop["phone"], "name": name, "unit": "piece",
            "quantity": qty, "selling_price": price, "cost_price": 700}
    if barcode:
        body["barcode"] = barcode
    r = client.post("/app/api/inventory", cookies=shop["cookies"], json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _scan(shop, code):
    r = client.get("/app/api/pos/scan", cookies=shop["cookies"], params={"code": code})
    assert r.status_code == 200, r.text
    return r.json()


# ── A code means one product ─────────────────────────────────────────────────

def test_a_scan_finds_the_product(shop):
    _add(shop, "Peak Milk 400g", barcode="6151100012345", price=4_500)
    result = _scan(shop, "6151100012345")
    assert result["found"] is True
    assert result["product"]["name"] == "peak milk 400g"
    assert result["product"]["selling_price"] == 4_500
    assert result["product"]["sellable"] is True


def test_a_scanner_pads_the_code_and_it_still_matches(shop):
    _add(shop, "Indomie", barcode="6001234567890")
    assert _scan(shop, "  6001234567890\n")["found"] is True


def test_two_products_cannot_answer_the_same_scan(shop):
    _add(shop, "Peak Milk 400g", barcode="6151100012345")
    r = client.post("/app/api/inventory", cookies=shop["cookies"], json={
        "owner_phone": shop["phone"], "name": "Peak Milk 900g",
        "unit": "tin", "quantity": 5, "selling_price": 9_000,
        "barcode": "6151100012345",
    })
    assert r.status_code == 400
    assert "already on peak milk 400g" in r.json()["detail"].lower()


def test_a_code_can_be_moved_to_the_right_product(shop):
    first = _add(shop, "Peak Milk 400g", barcode="6151100012345")
    second = _add(shop, "Peak Milk 900g")

    # Clear it from the wrong product, then attach it to the right one.
    assert client.put(f"/app/api/inventory/{first}", cookies=shop["cookies"],
                      json={"barcode": ""}).status_code == 200
    r = client.post("/app/api/pos/scan/attach", cookies=shop["cookies"],
                    json={"item_id": second, "code": "6151100012345"})
    assert r.status_code == 200
    assert _scan(shop, "6151100012345")["product"]["id"] == second


def test_moving_a_code_without_clearing_it_first_is_refused(shop):
    _add(shop, "Peak Milk 400g", barcode="6151100012345")
    second = _add(shop, "Peak Milk 900g")
    r = client.post("/app/api/pos/scan/attach", cookies=shop["cookies"],
                    json={"item_id": second, "code": "6151100012345"})
    assert r.status_code == 400
    assert "already on" in r.json()["detail"].lower()


def test_a_near_match_is_not_a_match(shop):
    """A barcode is an identifier, not a search term — a near miss at the till
    is a wrong price."""
    _add(shop, "Peak Milk", barcode="6151100012345")
    assert _scan(shop, "615110001234")["found"] is False
    assert _scan(shop, "61511000123456")["found"] is False


# ── The unknown code, which is how a shop builds its list ────────────────────

def test_an_unknown_code_is_reported_not_guessed(shop):
    _add(shop, "Peak Milk")
    result = _scan(shop, "6151100099999")
    assert result["found"] is False
    assert result["code"] == "6151100099999"       # handed back, ready to attach


def test_attaching_at_the_till_teaches_the_product(shop):
    item_id = _add(shop, "Peak Milk")
    assert _scan(shop, "6151100012345")["found"] is False

    r = client.post("/app/api/pos/scan/attach", cookies=shop["cookies"],
                    json={"item_id": item_id, "code": "6151100012345"})
    assert r.status_code == 200
    assert _scan(shop, "6151100012345")["product"]["id"] == item_id


def test_rubbish_is_not_accepted_as_a_barcode(shop):
    item_id = _add(shop, "Peak Milk")
    for bad in ("", "ab", "two words"):
        r = client.post("/app/api/pos/scan/attach", cookies=shop["cookies"],
                        json={"item_id": item_id, "code": bad})
        assert r.status_code == 400


# ── Scanning stays optional ──────────────────────────────────────────────────

def test_a_shop_that_scans_nothing_is_unaffected(shop):
    _add(shop, "Rice", price=68_000)
    _add(shop, "Beans", price=50_000)
    catalogue = client.get("/app/api/pos/products", cookies=shop["cookies"]).json()
    assert len(catalogue["products"]) == 2
    assert all(p["barcode"] is None for p in catalogue["products"])


def test_the_catalogue_carries_the_code_so_a_scan_works_offline(shop):
    """The POS preloads the catalogue and matches on the phone — the till must
    keep selling when the connection drops."""
    _add(shop, "Peak Milk", barcode="6151100012345")
    catalogue = client.get("/app/api/pos/products", cookies=shop["cookies"]).json()
    assert catalogue["products"][0]["barcode"] == "6151100012345"


def test_one_shops_codes_are_invisible_to_another(shop):
    _add(shop, "Peak Milk", barcode="6151100012345")
    other_phone = f"23480901402{next(_seq)}"
    client.post("/app/api/auth/register",
                json={"name": "Other Shop", "phone": other_phone, "pin": "5678"})
    other = {"phone": other_phone,
             "cookies": client.post("/app/api/auth/login",
                                    json={"phone": other_phone, "pin": "5678"}).cookies}
    assert _scan(other, "6151100012345")["found"] is False

    # And the same code may be used by both shops for their own product.
    _add(other, "Something Else", barcode="6151100012345")
    assert _scan(other, "6151100012345")["product"]["name"] == "something else"


def test_an_unpriced_product_is_found_but_flagged_not_sellable(shop):
    r = client.post("/app/api/inventory", cookies=shop["cookies"], json={
        "owner_phone": shop["phone"], "name": "Draft Item", "unit": "piece",
        "quantity": 3, "barcode": "6151100077777",
    })
    assert r.status_code == 200, r.text
    result = _scan(shop, "6151100077777")
    assert result["found"] is True
    assert result["product"]["sellable"] is False


# ── The helpers themselves ───────────────────────────────────────────────────

@pytest.mark.parametrize("code,ok", [
    ("6151100012345", True), ("1234", True), ("ABC-123_x.1", True),
    ("", False), ("abc", False), ("has space", False), ("x" * 49, False),
])
def test_what_counts_as_a_barcode(code, ok):
    assert barcodes.is_plausible(code) is ok


def test_stock_added_without_a_barcode_can_be_given_one_by_editing(shop):
    """Stock added before barcodes (or without one) gets its code from Edit,
    the same way Add takes one — and the till then finds it by scan."""
    item = _add(shop, "Golden Penny Spaghetti")
    r = client.put(f"/app/api/inventory/{item}", cookies=shop["cookies"],
                   json={"barcode": "6154000123456"})
    assert r.status_code == 200, r.text
    assert _scan(shop, "6154000123456")["product"]["id"] == item

    other = _add(shop, "Dangote Spaghetti")
    r = client.put(f"/app/api/inventory/{other}", cookies=shop["cookies"],
                   json={"barcode": "6154000123456"})
    assert r.status_code == 400                     # one code, one product


def test_a_12_digit_scan_finds_a_13_digit_code_and_back(shop):
    """UPC-A (12 digits, what a phone camera reads) is EAN-13 with a leading
    0 (what a USB scanner or a person often types). Same packet, same code."""
    typed_13 = _add(shop, "Pringles Original", barcode="0038000138416")
    assert _scan(shop, "038000138416")["product"]["id"] == typed_13

    # A code saved as 12 digits before this fix is still found by the 13.
    db = SessionLocal()
    try:
        from models import InventoryItem
        legacy = InventoryItem(owner_phone=shop["phone"], name="Oreo", quantity=5,
                               selling_price=500, barcode="044000032029")
        db.add(legacy); db.commit()
        legacy_id = legacy.id
    finally:
        db.close()
    assert _scan(shop, "0044000032029")["product"]["id"] == legacy_id


def test_the_two_forms_count_as_one_code_for_clashes(shop):
    _add(shop, "Pringles Original", barcode="038000138416")
    r = client.post("/app/api/inventory", cookies=shop["cookies"], json={
        "owner_phone": shop["phone"], "name": "Pringles Sour Cream", "unit": "can",
        "quantity": 1, "selling_price": 900, "barcode": "0038000138416"})
    assert r.status_code == 400
