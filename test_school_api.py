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


def test_fee_reminders_are_queued_for_the_parents_who_owe(head):
    session = _post("sessions", head, {"name": "2025/2026"})
    term1 = session["terms"][0]["id"]
    jss2 = _post("classes", head, {"name": "JSS 2"})["id"]
    tuition = _post("fee-items", head, {"name": "Tuition"})["id"]
    _post("schedule", head, {"term_id": term1, "class_id": jss2,
                             "amounts": {tuition: 45_000}})

    owing = _post("pupils", head, {"name": "Aisha Bello", "class_id": jss2,
                                   "parent_name": "Mr Bello",
                                   "parent_phone": "08031112222",
                                   "details": {"sex": "Female"}})
    paid_up = _post("pupils", head, {"name": "Tunde Okoro", "class_id": jss2,
                                     "parent_name": "Mrs Okoro",
                                     "parent_phone": "08039998888",
                                     "details": {"sex": "Male"}})
    no_phone = _post("pupils", head, {"name": "Chidi Eze", "class_id": jss2,
                                      "details": {"sex": "Male"}})
    _post(f"terms/{term1}/open", head, {})
    _post("payments", head, {"customer_id": paid_up["customer_id"], "amount": 45_000})

    result = _post("fee-reminders", head, {})
    assert result["queued"] == 1                  # only the one who owes, with a phone
    assert result["no_phone"] == 1                # Chidi's parent has no number
    assert result["owing"] == 2

    # Asking twice does not queue the same parent twice.
    assert _post("fee-reminders", head, {})["already_queued"] == 1

    queue = client.get("/app/api/reminders", cookies=head).json()
    item = next(r for r in queue.get("reminders", [])
                if r.get("customer_name") == "Aisha Bello")
    message = item["message_text"]
    assert "Mr Bello" in message                  # the parent, not the pupil
    assert "Aisha Bello" in message and "JSS 2" in message
    assert "First Term" in message
    assert "N45,000" in message
    assert "Bright Star School" in message        # signed by the school
    assert paid_up["name"] not in str(queue)      # nobody paid-up is chased


def test_everything_entered_can_be_corrected_over_the_api(head):
    session = _post("sessions", head, {"name": "2025/2026"})
    term1 = session["terms"][0]["id"]
    jss2 = _post("classes", head, {"name": "JS2"})["id"]
    pry4 = _post("classes", head, {"name": "Primary 4"})["id"]
    tuition = _post("fee-items", head, {"name": "Tutition"})["id"]   # typo on purpose
    pupil = _post("pupils", head, {"name": "Aisah Bello", "class_id": jss2,
                                   "parent_phone": "08031112222",
                                   "details": {"sex": "Female"}})

    # A class, a fee item and a pupil, all corrected.
    r = client.put(f"/app/api/school/classes/{jss2}", cookies=head,
                   json={"name": "JSS 2", "level_order": 2, "is_active": True})
    assert r.status_code == 200, r.text
    r = client.put(f"/app/api/school/fee-items/{tuition}", cookies=head,
                   json={"name": "Tuition"})
    assert r.status_code == 200, r.text
    r = client.put(f"/app/api/school/pupils/{pupil['customer_id']}", cookies=head,
                   json={"name": "Aisha Bello", "class_id": pry4,
                         "parent_name": "Mr Bello"})
    assert r.status_code == 200, r.text

    listed = _get("pupils", head)["pupils"][0]
    assert listed["name"] == "Aisha Bello"
    assert listed["class_name"] == "Primary 4"
    assert listed["parent_name"] == "Mr Bello"
    assert {c["name"] for c in _get("setup", head)["classes"]} == {"JSS 2", "Primary 4"}

    # What the class owes can be rewritten, including removing an item.
    _post("schedule", head, {"term_id": term1, "class_id": pry4,
                             "amounts": {tuition: 45_000}})
    _post("schedule", head, {"term_id": term1, "class_id": pry4,
                             "amounts": {tuition: 50_000}})
    assert _get("schedule", head, term_id=term1, class_id=pry4)["total"] == 50_000

    # An empty class goes outright.
    assert client.delete(f"/app/api/school/classes/{jss2}",
                         cookies=head).json()["deleted"] is True


def test_what_money_depends_on_is_closed_rather_than_deleted(head):
    session = _post("sessions", head, {"name": "2025/2026"})
    term1 = session["terms"][0]["id"]
    jss2 = _post("classes", head, {"name": "JSS 2"})["id"]
    tuition = _post("fee-items", head, {"name": "Tuition"})["id"]
    _post("schedule", head, {"term_id": term1, "class_id": jss2,
                             "amounts": {tuition: 45_000}})
    pupil = _post("pupils", head, {"name": "Aisha Bello", "class_id": jss2,
                                   "details": {"sex": "Female"}})
    _post(f"terms/{term1}/open", head, {})

    charged = client.delete(f"/app/api/school/pupils/{pupil['customer_id']}",
                            cookies=head).json()
    assert charged["deleted"] is False and charged["marked_left"] is True

    klass = client.delete(f"/app/api/school/classes/{jss2}", cookies=head).json()
    assert klass["deleted"] is False and klass["closed"] is True

    item = client.delete(f"/app/api/school/fee-items/{tuition}", cookies=head).json()
    assert item["deleted"] is False and item["retired"] is True
    assert "already been charged" in item["reason"]

    # The money is still on the books after all three.
    summary = _get("term-summary", head)["summary"]
    assert summary["expected"] == 45_000


def test_a_question_can_be_renamed_and_dropped(head):
    field = _post("pupil-fields", head, {"label": "Best colour"})
    r = client.put(f"/app/api/school/pupil-fields/{field['id']}", cookies=head,
                   json={"label": "Favourite colour", "is_required": True})
    assert r.status_code == 200 and r.json()["label"] == "Favourite colour"

    assert client.delete(f"/app/api/school/pupil-fields/{field['id']}",
                         cookies=head).json()["deleted"] is True
    assert "best_colour" not in {f["key"] for f in _get("pupil-fields", head)["fields"]}


def test_reminding_before_a_term_exists_says_so(head):
    r = client.post("/app/api/school/fee-reminders", cookies=head, json={})
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
