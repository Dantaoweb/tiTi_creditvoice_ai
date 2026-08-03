"""
#3: staff can be assigned to a branch, and their recordings tag that branch.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-branch-staff-tests-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Branch

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _pro_owner(phone):
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    # Premium so multi-branch tests aren't blocked by the Pro 1-branch cap.
    u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_assign_staff_to_branch_and_record_tags_it():
    owner_phone = "2348044440001"
    cookies = _pro_owner(owner_phone)

    # Two branches
    b_main = client.post("/app/api/branches", cookies=cookies, json={"name": "Main"}).json()
    b_ikeja = client.post("/app/api/branches", cookies=cookies, json={"name": "Ikeja"}).json()

    # Invite + accept a staff member
    staff_phone = "2348044440002"
    code = client.post("/app/api/staff/invite", cookies=cookies,
                       json={"name": "Sade", "phone": staff_phone}).json()["invite_code"]
    client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": code})

    member = next(m for m in client.get("/app/api/staff/members", cookies=cookies).json()["members"]
                  if m["phone"] == staff_phone)

    # Assign the staff to the Ikeja branch
    r = client.post(f"/app/api/staff/{member['id']}/branch", cookies=cookies,
                    json={"branch_id": b_ikeja["id"]})
    assert r.status_code == 200 and r.json()["branch_id"] == b_ikeja["id"]

    members = client.get("/app/api/staff/members", cookies=cookies).json()["members"]
    assert next(m for m in members if m["phone"] == staff_phone)["branch_name"] == "Ikeja"

    # Recording resolves the recorder's branch, not the business default.
    from transaction_save import _get_recording_branch_id, _get_default_branch_id
    db = SessionLocal()
    # Make Main the default branch to prove staff branch overrides it.
    db.query(Branch).filter(Branch.id == b_main["id"]).update({"is_default": True})
    db.commit()
    staff_user = db.query(User).filter(User.phone == staff_phone).first()
    owner_user = db.query(User).filter(User.phone == owner_phone).first()
    assert _get_recording_branch_id(db, owner_phone, staff_user) == b_ikeja["id"]
    # The owner (no branch assigned) falls back to the default branch.
    assert _get_recording_branch_id(db, owner_phone, owner_user) == b_main["id"]
    assert _get_default_branch_id(db, owner_phone) == b_main["id"]
    db.close()


def test_assign_to_other_owners_branch_rejected():
    a_cookies = _pro_owner("2348044440010")
    b_cookies = _pro_owner("2348044440011")
    a_branch = client.post("/app/api/branches", cookies=a_cookies, json={"name": "A-Branch"}).json()

    staff_phone = "2348044440012"
    code = client.post("/app/api/staff/invite", cookies=b_cookies,
                       json={"name": "Tunde", "phone": staff_phone}).json()["invite_code"]
    client.post("/app/api/staff/accept", json={"phone": staff_phone, "code": code})
    member = next(m for m in client.get("/app/api/staff/members", cookies=b_cookies).json()["members"]
                  if m["phone"] == staff_phone)

    # Owner B cannot assign their staff to owner A's branch
    r = client.post(f"/app/api/staff/{member['id']}/branch", cookies=b_cookies,
                    json={"branch_id": a_branch["id"]})
    assert r.status_code == 404
