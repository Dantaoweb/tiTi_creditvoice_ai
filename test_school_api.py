"""
The school fee structure over HTTP, the way the screens will use it.

One pass through the whole thing: set up the year, register a pupil, open the
term, take a payment, hand out a textbook — then check the bursar's two views
agree with the pupil's statement.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-school-api-0000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from main import app

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
def head():
    """A school, signed in."""
    phone = f"23480901001{next(_seq)}"
    client.post("/app/api/auth/register", json={
        "name": "Bright Star School", "phone": phone, "pin": "5678",
        "business_type": "private_school",
    })
    return client.post("/app/api/auth/login",
                       json={"phone": phone, "pin": "5678"}).cookies


def _post(path, cookies, body):
    r = client.post(f"/app/api/school/{path}", cookies=cookies, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _get(path, cookies, **params):
    r = client.get(f"/app/api/school/{path}", cookies=cookies, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_school_runs_a_term_end_to_end(head):
    # ── Set up the year ──────────────────────────────────────────────────────
    session = _post("sessions", head, {"name": "2025/2026"})
    term1 = session["terms"][0]["id"]
    jss2 = _post("classes", head, {"name": "JSS 2", "level_order": 2})["id"]
    tuition = _post("fee-items", head, {"name": "Tuition", "kind": "FEE"})["id"]
    pta = _post("fee-items", head, {"name": "PTA levy", "kind": "LEVY"})["id"]
    book = _post("fee-items", head, {"name": "Maths textbook", "kind": "BOOK",
                                     "default_amount": 3500, "is_optional": True})["id"]

    setup = _get("setup", head)
    assert setup["current_term_id"] == term1
    assert [c["name"] for c in setup["classes"]] == ["JSS 2"]
    assert setup["fee_items"][-1]["is_optional"] is True        # optional sorts last

    # ── What JSS 2 owes ──────────────────────────────────────────────────────
    _post("schedule", head, {"term_id": term1, "class_id": jss2,
                             "amounts": {tuition: 45_000, pta: 2_000, book: 3_500}})
    schedule = _get("schedule", head, term_id=term1, class_id=jss2)
    assert schedule["total"] == 47_000          # the book is not compulsory

    # ── Register a pupil ─────────────────────────────────────────────────────
    pupil = _post("pupils", head, {"name": "Aisha Bello", "class_id": jss2,
                                   "parent_name": "Mr Bello",
                                   "parent_phone": "08031112222"})
    assert pupil["admission_no"].startswith("2025/")

    pupils = _get("pupils", head)["pupils"]
    assert len(pupils) == 1
    assert pupils[0]["class_name"] == "JSS 2"
    assert pupils[0]["balance"] == 0            # nothing owed until the term opens

    # ── Open the term ────────────────────────────────────────────────────────
    opened = _post(f"terms/{term1}/open", head, {})
    assert opened["charged"] == 1 and opened["total"] == 47_000
    assert _get("pupils", head)["pupils"][0]["balance"] == 47_000

    # Running it again charges nobody twice.
    assert _post(f"terms/{term1}/open", head, {})["charged"] == 0

    # ── Collect, then hand out a textbook ────────────────────────────────────
    paid = _post("payments", head, {"customer_id": pupil["customer_id"],
                                    "amount": 30_000})
    assert paid["balance"] == 17_000

    _post("charge", head, {"customer_id": pupil["customer_id"],
                           "items": [{"fee_item_id": book, "quantity": 1}]})

    # ── The three views agree ────────────────────────────────────────────────
    statement = _get(f"pupils/{pupil['customer_id']}/statement", head)
    assert statement["balance"] == 20_500       # 47,000 − 30,000 + 3,500
    assert statement["class_name"] == "JSS 2"
    assert statement["parent_name"] == "Mr Bello"

    summary = _get("term-summary", head)["summary"]
    assert summary["expected"] == 50_500        # term fees plus the book
    assert summary["outstanding"] == 20_500

    owing = _get("defaulters", head)["defaulters"]
    assert owing[0]["name"] == "Aisha Bello"
    assert owing[0]["outstanding"] == 20_500


def test_nothing_is_readable_without_signing_in():
    # A fresh client: the shared one carries cookies from whichever test ran
    # last, so the request would not actually be anonymous.
    anonymous = TestClient(app, raise_server_exceptions=True)
    for path in ("setup", "pupils", "term-summary", "defaulters"):
        assert anonymous.get(f"/app/api/school/{path}").status_code in (401, 403)


def test_one_school_cannot_see_another(head):
    _post("classes", head, {"name": "JSS 2"})
    other = f"23480901002{next(_seq)}"
    client.post("/app/api/auth/register", json={
        "name": "Other School", "phone": other, "pin": "5678",
        "business_type": "private_school"})
    other_head = client.post("/app/api/auth/login",
                             json={"phone": other, "pin": "5678"}).cookies
    assert _get("setup", other_head)["classes"] == []
    assert _get("pupils", other_head)["pupils"] == []


def test_a_fee_item_needs_a_known_kind(head):
    r = client.post("/app/api/school/fee-items", cookies=head,
                    json={"name": "Mystery", "kind": "NONSENSE"})
    assert r.status_code == 400
    assert "Kind must be one of" in r.json()["detail"]


def test_charging_before_a_term_exists_says_so(head):
    r = client.post("/app/api/school/charge", cookies=head,
                    json={"customer_id": 1, "items": []})
    assert r.status_code == 400
    assert "No term is open yet" in r.json()["detail"]


def test_a_school_builds_its_own_registration_form(head):
    form = _get("pupil-fields", head)
    assert {f["key"] for f in form["fields"]} >= {"sex", "age"}
    # The library offers the rest without imposing it.
    suggested = {s["key"] for s in form["suggestions"]}
    assert {"best_colour", "best_food", "hobby", "blood_group"} <= suggested

    _post("pupil-fields", head, {"label": "Best colour"})
    _post("pupil-fields", head, {"label": "Best food"})
    _post("pupil-fields", head, {"label": "House", "field_type": "choice",
                                 "options": ["Red", "Blue", "Green"]})

    form = _get("pupil-fields", head)
    assert {"best_colour", "best_food", "house"} <= {f["key"] for f in form["fields"]}
    assert "best_colour" not in {s["key"] for s in form["suggestions"]}   # already added

    pupil = _post("pupils", head, {
        "name": "Aisha Bello",
        "details": {"sex": "Female", "age": "9", "best_colour": "Blue",
                    "best_food": "Jollof rice", "house": "Red"},
    })
    shown = {d["label"]: d["value"] for d in pupil["details"]}
    assert shown["Best food"] == "Jollof rice"
    assert shown["House"] == "Red"

    statement = _get(f"pupils/{pupil['customer_id']}/statement", head)
    assert {"key": "best_colour", "label": "Best colour", "value": "Blue"} in statement["details"]


def test_the_form_refuses_an_answer_it_does_not_accept(head):
    _post("pupil-fields", head, {"label": "House", "field_type": "choice",
                                 "options": ["Red", "Blue"]})
    r = client.post("/app/api/school/pupils", cookies=head, json={
        "name": "Tunde Okoro", "details": {"sex": "Male", "house": "Yellow"}})
    assert r.status_code == 400
    assert "House must be one of" in r.json()["detail"]


def test_an_unknown_field_type_is_refused(head):
    r = client.post("/app/api/school/pupil-fields", cookies=head,
                    json={"label": "Something", "field_type": "rainbow"})
    assert r.status_code == 400
    assert "Field type must be one of" in r.json()["detail"]


def test_a_school_with_no_year_set_up_reads_empty_rather_than_breaking(head):
    assert _get("term-summary", head)["summary"] is None
    assert _get("defaulters", head)["defaulters"] == []
    assert _get("setup", head)["current_term_id"] is None
