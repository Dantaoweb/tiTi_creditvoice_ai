"""
Transactions list must reach the WHOLE period: the old endpoint returned only
the latest 200, so a busy shop's "this month" showed a few days, and the type
filters (SALE/BUY/PAY) only filtered those 200 rows.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-tx-paging-0000000000000000")

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    phone = f"234847{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _seed(phone, sales=220, pays=5):
    """`sales` SALEs to Ade, then `pays` older PAYs from Bola — the PAYs are the
    OLDEST rows, so they sit beyond the first 200."""
    db = SessionLocal()
    uid = db.query(User).filter(User.phone == phone).first().id
    ade = Customer(owner_phone=phone, name="Ade", balance=0)
    bola = Customer(owner_phone=phone, name="Bola", balance=0)
    db.add_all([ade, bola]); db.flush()
    now = utcnow()
    for i in range(sales):
        db.add(Transaction(customer_id=ade.id, type="SALE", amount=100 + i, product="rice",
                           recorded_by_id=uid, created_at=now - timedelta(minutes=i + 1)))
    for i in range(pays):
        db.add(Transaction(customer_id=bola.id, type="PAY", amount=50, recorded_by_id=uid,
                           created_at=now - timedelta(days=5, minutes=i)))
    db.commit(); db.close()


def _get(cook, **params):
    params.setdefault("period", "MONTH")
    r = client.get("/app/api/transactions", cookies=cook, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_transaction_in_period_reachable():
    phone, cook = _owner()
    _seed(phone)
    seen, offset = [], 0
    while True:
        d = _get(cook, limit=100, offset=offset)
        assert d["total"] == 225
        seen += [t["id"] for t in d["transactions"]]
        if not d["has_more"]:
            break
        offset += len(d["transactions"])
    assert len(set(seen)) == 225


def test_type_filter_finds_rows_beyond_first_200():
    phone, cook = _owner()
    _seed(phone)
    d = _get(cook, type="PAY")
    assert d["total"] == 5 and {t["type"] for t in d["transactions"]} == {"PAY"}


def test_summary_counts_per_type():
    phone, cook = _owner()
    _seed(phone)
    s = client.get("/app/api/transactions/summary", cookies=cook, params={"period": "MONTH"}).json()
    assert s == {"total": 225, "by_type": {"SALE": 220, "PAY": 5}}


def test_search_by_customer_and_product():
    phone, cook = _owner()
    _seed(phone, sales=3, pays=2)
    assert _get(cook, q="bola")["total"] == 2
    assert _get(cook, q="RICE")["total"] == 3
    assert _get(cook, q="%")["total"] == 0
    s = client.get("/app/api/transactions/summary", cookies=cook,
                   params={"period": "MONTH", "q": "bola"}).json()
    assert s["by_type"] == {"PAY": 2}


def test_sort_by_amount():
    phone, cook = _owner()
    _seed(phone, sales=10, pays=0)
    amounts = [t["amount"] for t in _get(cook, sort="amount", dir="desc")["transactions"]]
    assert amounts == sorted(amounts, reverse=True) and amounts[0] == 109


def test_void_still_listed_and_counted():
    phone, cook = _owner()
    _seed(phone, sales=2, pays=0)
    tx_id = _get(cook)["transactions"][0]["id"]
    r = client.post(f"/app/api/transactions/{tx_id}/void", cookies=cook, json={"reason": "typo"})
    assert r.status_code == 200, r.text
    rows = {t["id"]: t for t in _get(cook)["transactions"]}
    assert rows[tx_id]["is_voided"] is True and len(rows) == 2


def test_loan_statement_reports_latest_100_of_total(monkeypatch):
    phone, cook = _owner()
    _seed(phone, sales=130, pays=0)
    captured = {}

    def fake_statement(**kw):
        captured.update(kw)
        return b"%PDF-1.4 fake"

    import loan_statement
    monkeypatch.setattr(loan_statement, "generate_loan_statement", fake_statement)
    r = client.get("/app/api/loan-statement", cookies=cook, params={"period": "MONTH"})
    assert r.status_code == 200, r.text
    assert len(captured["transactions"]) == 100
    assert captured["transactions_total"] == 130


def test_loan_statement_heading_says_latest_of_total():
    # Render the real PDF uncompressed and check the heading text.
    from fpdf import FPDF
    import loan_statement
    orig = FPDF.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.set_compression(False)

    FPDF.__init__ = init
    try:
        tx = [{"type": "SALE", "customer": "Ade", "amount": 100, "created_at": utcnow(), "product": "rice"}] * 100
        pdf = loan_statement.generate_loan_statement(
            owner={"name": "Shop", "phone": "234"}, summary={}, transactions=tx, debtors=[],
            stock_items=[], period_label="last 30 days", transactions_total=1523,
        )
    finally:
        FPDF.__init__ = orig
    assert b"latest 100 of 1,523 records" in pdf
