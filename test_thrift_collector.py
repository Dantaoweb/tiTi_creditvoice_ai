"""
Collector (alajo) thrift: an agent collects a daily amount from many individual
customers; each customer's balance is their own savings; the agent cashes a
customer out any time, keeping a commission (default one day's contribution).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-collector-00000000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth

client = TestClient(app)
_seq = iter(range(8900, 9399))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _agent(name="Alajo"):
    n = next(_seq)
    phone = f"234824{n:06d}"
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "2468"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "2468"}).cookies
    return phone, cook


def _collector_group(cook, name="Daily Ajo", amount=500, ctype="one_day", cval=None):
    return client.post("/app/api/thrift/groups", cookies=cook, json={
        "name": name, "group_type": "collector", "contribution_amount": amount,
        "max_members": 20, "commission_type": ctype, "commission_value": cval,
    }).json()


def _member(g, name):
    return next(m for m in g["members"] if m["name"].lower() == name.lower())


def test_daily_collection_and_one_day_commission_settlement():
    _, cook = _agent()
    g = _collector_group(cook, amount=500)
    gid = g["id"]
    assert g["group_type"] == "collector"

    g = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=cook,
                    json={"name": "Ade", "daily_amount": 500}).json()
    ade = _member(g, "Ade")

    # Collect for 3 days (defaults to the customer's daily amount).
    for _ in range(3):
        g = client.post(f"/app/api/thrift/groups/{gid}/collect", cookies=cook,
                        json={"member_id": ade["id"]}).json()
    ade = _member(g, "Ade")
    assert ade["balance"] == 1500
    assert ade["days_saved"] == 3
    assert ade["paid_today"] is True

    # Cash out — one_day commission keeps one day's contribution (500).
    g = client.post(f"/app/api/thrift/groups/{gid}/members/{ade['id']}/settle", cookies=cook,
                    json={}).json()
    ade = _member(g, "Ade")
    assert ade["balance"] == 0
    assert g["total_paid_out"] == 1000     # 1500 - 500 commission
    assert g["total_commission"] == 500
    assert g["payouts"][0]["amount"] == 1000
    assert g["payouts"][0]["commission"] == 500


def test_percent_commission():
    _, cook = _agent()
    g = _collector_group(cook, name="Percent Ajo", amount=1000, ctype="percent", cval=10)
    gid = g["id"]
    g = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=cook,
                    json={"name": "Bola", "daily_amount": 1000}).json()
    bola = _member(g, "Bola")
    for _ in range(2):
        client.post(f"/app/api/thrift/groups/{gid}/collect", cookies=cook, json={"member_id": bola["id"]})
    g = client.post(f"/app/api/thrift/groups/{gid}/members/{bola['id']}/settle", cookies=cook, json={}).json()
    assert g["total_commission"] == 200     # 10% of 2,000
    assert g["total_paid_out"] == 1800


def test_settle_with_commission_override():
    _, cook = _agent()
    g = _collector_group(cook, name="Override Ajo", amount=200)
    gid = g["id"]
    g = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=cook,
                    json={"name": "Chidi", "daily_amount": 200}).json()
    chidi = _member(g, "Chidi")
    for _ in range(5):
        client.post(f"/app/api/thrift/groups/{gid}/collect", cookies=cook, json={"member_id": chidi["id"]})
    # Agent agrees a custom fee of 300 with this customer.
    g = client.post(f"/app/api/thrift/groups/{gid}/members/{chidi['id']}/settle", cookies=cook,
                    json={"commission": 300}).json()
    assert g["total_commission"] == 300
    assert g["total_paid_out"] == 700       # 1,000 - 300
