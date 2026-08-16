"""
Thrift / Ajo groups: a user creates named rotating-savings groups (each with its
own contribution amount + members), shares an invite link, approves joiners
(admin or a promoted approver), records contributions and rotates the pot.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-thrift-00000000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth

client = TestClient(app)
_seq = iter(range(7500, 7999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _user(name):
    n = next(_seq)
    phone = f"234819{n:06d}"
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "1357"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "1357"}).cookies
    return phone, cook


def _make_group(cook, name="Market Women Ajo", amount=5000):
    return client.post("/app/api/thrift/groups", cookies=cook,
                       json={"name": name, "contribution_amount": amount, "frequency": "weekly"}).json()


def test_full_rotation_flow():
    _, admin = _user("Ada")
    g = _make_group(admin)
    gid = g["id"]
    assert g["contribution_amount"] == 5000
    assert g["active_count"] == 1                       # creator is member #1
    assert g["members"][0]["role"] == "admin"
    assert g["members"][0]["turn_order"] == 1

    # Add a participant directly.
    g = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=admin,
                    json={"name": "Amina"}).json()
    assert g["active_count"] == 2
    assert g["pot"] == 10000                            # 5000 x 2
    token = g["invite_token"]
    assert token

    # A third person joins via the link → pending approval.
    _, tunde = _user("Tunde")
    info = client.get(f"/app/api/thrift/join/{token}", cookies=tunde).json()
    assert info["name"] == "Market Women Ajo"
    jr = client.post(f"/app/api/thrift/join/{token}", cookies=tunde, json={}).json()
    assert jr["status"] == "pending"

    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    assert g["pending_count"] == 1
    pending = next(m for m in g["members"] if m["status"] == "pending")

    g = client.post(f"/app/api/thrift/members/{pending['id']}/approve", cookies=admin).json()
    assert g["active_count"] == 3
    assert g["pending_count"] == 0

    # Everyone contributes for round 1.
    for m in [mm for mm in g["members"] if mm["status"] == "active"]:
        client.post(f"/app/api/thrift/groups/{gid}/contributions", cookies=admin,
                    json={"member_id": m["id"]})
    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    assert g["paid_count"] == 3
    assert g["collected_this_round"] == 15000
    assert g["current_turn"]["name"]                    # someone is due the pot

    # Pay out the pot and advance the round.
    g = client.post(f"/app/api/thrift/groups/{gid}/payout", cookies=admin).json()
    assert g["current_round"] == 2
    assert g["payouts"][0]["amount"] == 15000


def test_promoted_approver_can_add_and_approve():
    _, admin = _user("Owner")
    g = _make_group(admin, name="Office Ajo", amount=2000)
    gid = g["id"]
    token = g["invite_token"]

    # Member joins, admin approves, then promotes them to approver.
    _, bola = _user("Bola")
    client.post(f"/app/api/thrift/join/{token}", cookies=bola, json={})
    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    bola_m = next(m for m in g["members"] if m["status"] == "pending")
    client.post(f"/app/api/thrift/members/{bola_m['id']}/approve", cookies=admin)
    g = client.post(f"/app/api/thrift/members/{bola_m['id']}/promote", cookies=admin).json()
    assert next(m for m in g["members"] if m["id"] == bola_m["id"])["role"] == "approver"

    # The approver can now add a participant.
    r = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=bola, json={"name": "Chidi"})
    assert r.status_code == 200, r.text
    assert r.json()["active_count"] == 3


def test_member_cap_blocks_extra_joins():
    _, admin = _user("Capped")
    g = client.post("/app/api/thrift/groups", cookies=admin,
                    json={"name": "Small Ajo", "contribution_amount": 1000, "max_members": 2}).json()
    gid = g["id"]
    assert g["max_members"] == 2
    # admin is member #1; add member #2 → full.
    g = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=admin, json={"name": "Two"}).json()
    assert g["accepting"] is False
    token = g["invite_token"]
    _, third = _user("Third")
    r = client.post(f"/app/api/thrift/join/{token}", cookies=third, json={})
    assert r.status_code == 400


def test_admin_can_lock_and_unlock():
    _, admin = _user("Locker")
    g = _make_group(admin, name="Lockable", amount=1000)
    gid, token = g["id"], g["invite_token"]

    g = client.post(f"/app/api/thrift/groups/{gid}/settings", cookies=admin, json={"locked": True}).json()
    assert g["locked"] is True and g["accepting"] is False
    _, joiner = _user("Joiner")
    assert client.post(f"/app/api/thrift/join/{token}", cookies=joiner, json={}).status_code == 400

    g = client.post(f"/app/api/thrift/groups/{gid}/settings", cookies=admin, json={"locked": False}).json()
    assert g["locked"] is False
    assert client.post(f"/app/api/thrift/join/{token}", cookies=joiner, json={}).json()["status"] in ("pending", "active")


def test_many_groups_and_unique_names_and_access():
    _, cook = _user("Multi")
    _make_group(cook, name="Group A", amount=5000)
    _make_group(cook, name="Group B", amount=1000)
    groups = client.get("/app/api/thrift/groups", cookies=cook).json()["groups"]
    assert len(groups) == 2
    assert {g["name"] for g in groups} == {"Group A", "Group B"}

    # Duplicate active name is rejected.
    dup = client.post("/app/api/thrift/groups", cookies=cook,
                      json={"name": "Group A", "contribution_amount": 500})
    assert dup.status_code == 409

    # A non-member cannot view someone else's group.
    gid = groups[0]["id"]
    _, stranger = _user("Stranger")
    assert client.get(f"/app/api/thrift/groups/{gid}", cookies=stranger).status_code == 403
