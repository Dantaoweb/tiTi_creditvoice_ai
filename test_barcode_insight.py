"""
What a barcode says: valid or not, what it is known as, and whether that
matches the product it is being saved on.

A barcode can't prove a product is genuine, so these only ever warn. Names
from other shops must never leak one shop's private label or typo: a name is
suggested only when two or more OTHER businesses agree.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-barcode-insight-000000000")

import pytest
from fastapi.testclient import TestClient

import barcode_insight
import web_auth
from barcode_insight import check_digit_ok, names_differ
from database import SessionLocal
from main import app
from models import BarcodeLookup, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))

COKE = "5449000000996"          # a real EAN-13 (Coca-Cola 330ml)
BAD = "5449000000997"           # same, last digit wrong


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    calls = []
    monkeypatch.setattr(barcode_insight, "_fetch_off", lambda code: calls.append(code) or None)
    db = SessionLocal()
    try:
        db.query(BarcodeLookup).delete()
        db.query(InventoryItem).filter(InventoryItem.barcode.in_([COKE, BAD])).delete()
        db.commit()
    finally:
        db.close()
    yield calls


def _shop():
    phone = f"2348072{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Shop", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cook


def _stock(phone, name, code):
    db = SessionLocal()
    try:
        db.add(InventoryItem(owner_phone=phone, name=name, quantity=5, selling_price=300, barcode=code))
        db.commit()
    finally:
        db.close()


def _insight(cook, code, name=None):
    params = {"code": code}
    if name:
        params["name"] = name
    r = client.get("/app/api/barcodes/insight", params=params, cookies=cook)
    assert r.status_code == 200, r.text
    return r.json()


# ── Check digit ─────────────────────────────────────────────────────────────

def test_check_digit():
    assert check_digit_ok(COKE) is True
    assert check_digit_ok("036000291452") is True          # UPC-A
    assert check_digit_ok(BAD) is False
    assert check_digit_ok("SHOP-0042") is None              # own label: never judged
    assert check_digit_ok("12345678") is None               # 8 digits: EAN-8 or UPC-E, not judged


def test_an_invalid_code_is_flagged():
    _phone, cook = _shop()
    got = _insight(cook, BAD)
    assert got["valid"] is False
    assert any(w["kind"] == "invalid" for w in got["warnings"])


def test_a_shop_label_is_never_flagged():
    _phone, cook = _shop()
    got = _insight(cook, "SHOP-0042")
    assert got["valid"] is None and got["warnings"] == []


# ── Names from other shops ──────────────────────────────────────────────────

def test_one_other_shop_is_not_enough():
    a, _ = _shop()
    _stock(a, "coke 33cl", COKE)
    _me, cook = _shop()
    assert _insight(cook, COKE)["suggestion"] is None


def test_two_other_shops_agreeing_are_suggested():
    for _ in range(2):
        other, _c = _shop()
        _stock(other, "coca cola 33cl", COKE)
    _me, cook = _shop()
    got = _insight(cook, COKE)
    assert got["suggestion"]["name"] == "Coca Cola 33Cl"
    assert got["suggestion"]["source"] == "shops" and got["suggestion"]["shops"] == 2


def test_your_own_shop_does_not_count_as_others():
    me, cook = _shop()
    _stock(me, "coca cola 33cl", COKE)
    other, _c = _shop()
    _stock(other, "coca cola 33cl", COKE)
    assert _insight(cook, COKE)["suggestion"] is None       # only one OTHER shop


def test_a_different_product_on_a_known_code_is_warned():
    for _ in range(2):
        other, _c = _shop()
        _stock(other, "coca cola 33cl", COKE)
    _me, cook = _shop()
    got = _insight(cook, COKE, name="Peak Milk 400g")
    mismatch = [w for w in got["warnings"] if w["kind"] == "mismatch"]
    assert mismatch and "Coca Cola" in mismatch[0]["text"]
    assert not any(w["kind"] == "mismatch" for w in _insight(cook, COKE, name="Coca-Cola 33cl")["warnings"])


# ── Public product records (Open Food Facts) ────────────────────────────────

def test_public_name_is_used_and_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(barcode_insight, "_fetch_off",
                        lambda code: calls.append(code) or "Coca-Cola Original 330 ml")
    _me, cook = _shop()
    got = _insight(cook, COKE)
    assert got["suggestion"] == {"name": "Coca-Cola Original 330 ml", "source": "openfoodfacts"}
    _insight(cook, COKE)
    assert calls == [COKE]                                   # asked once, then cached


def test_a_miss_is_cached_and_marked_unknown(_reset):
    _me, cook = _shop()
    got = _insight(cook, COKE)
    assert got["suggestion"] is None and got["unknown"] is True
    _insight(cook, COKE)
    assert _reset == [COKE]                                  # the miss is remembered too


def test_invalid_codes_are_not_looked_up(_reset):
    _me, cook = _shop()
    _insight(cook, BAD)
    assert _reset == []


def test_no_internet_still_answers(monkeypatch):
    def down(code):
        raise OSError("no network")
    monkeypatch.setattr(barcode_insight, "_fetch_off", down)
    _me, cook = _shop()
    got = _insight(cook, COKE)
    assert got["valid"] is True and got["suggestion"] is None and got["unknown"] is False


# ── The till ────────────────────────────────────────────────────────────────

def test_the_till_gets_the_insight_with_an_unknown_scan():
    _me, cook = _shop()
    r = client.get("/app/api/pos/scan", params={"code": BAD}, cookies=cook).json()
    assert r["found"] is False
    assert r["insight"]["valid"] is False


def test_names_differ():
    assert names_differ("Peak Milk 400g", "Milo 400g")
    assert not names_differ("Peak Milk 400g", "Peak Evaporated Milk 400g Tin")
    assert not names_differ("", "Milo")                       # nothing to compare: no warning
