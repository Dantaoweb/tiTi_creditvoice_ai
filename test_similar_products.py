"""
Is this product already in my stock? — a shop with hundreds of products and
no barcodes. "Paracetemol", "paracetamol 500 mg" and "g/nut oil" must find
what's there; a twin must not be created by accident; tiTi must answer
"do I have…?" with yes, close matches, or a clear no.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import InventoryItem
from query_handler import handle_natural_language_query
from similar_products import (
    check_new_product, possible_duplicates, same_product_score, search_score,
)

OWNER = "2348007000003"
NAMES = [
    ("paracetamol 500mg", "pack", 40), ("paracetamol syrup", "bottle", 12),
    ("groundnut oil", "bottle", 9), ("indomie noodles 70g", "carton", 5),
    ("peak milk (tin)", "tin", 30), ("golden penny semovita 1kg", "bag", 7),
    ("tomato paste", "tin", 24), ("amoxicillin 250mg", "pack", 18),
    ("peak milk tin", "tin", 6),          # a twin already made
]


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    for n, u, q in NAMES:
        s.add(InventoryItem(owner_phone=OWNER, name=n, unit=u, quantity=q, selling_price=500, is_available=True))
    # A big shop: 600 unrelated products around them
    for k in range(600):
        s.add(InventoryItem(owner_phone=OWNER, name=f"item {k} zx{k}", unit="pc", quantity=1, is_available=True))
    s.commit()
    yield s
    s.close()


@pytest.mark.parametrize("typed,stored", [
    ("paracetemol", "paracetamol 500mg"),
    ("paracetamol 500 mg", "paracetamol 500mg"),
    ("ground nut oil", "groundnut oil"),
    ("g/nut oil", "groundnut oil"),
    ("indomie noodle 70 g", "indomie noodles 70g"),
    ("tomatoes paste", "tomato paste"),
    ("semovita", "golden penny semovita 1kg"),
])
def test_spelling_slips_still_find_it(typed, stored):
    assert search_score(typed, stored) >= 0.78


def test_different_sizes_are_different_products():
    assert same_product_score("paracetamol 500mg", "paracetamol 250mg") == 0.0
    assert same_product_score("peak milk tin", "peak milk (tin)") == 1.0


def test_adding_a_twin_is_caught_and_close_names_shown(db):
    r = check_new_product(db, OWNER, "Paracetamol 500 MG", "pack")
    assert [x["name"] for x in r["exact"]] == ["Paracetamol 500Mg"]
    r = check_new_product(db, OWNER, "paracetemol 500mg", "pack")
    assert not r["exact"] and "Paracetamol 500Mg" in [x["name"] for x in r["similar"]]
    r = check_new_product(db, OWNER, "sardine", "tin")
    assert r == {"exact": [], "similar": []}


def test_duplicates_already_in_the_list_are_found(db):
    pairs = possible_duplicates(db, OWNER)
    names = {frozenset((p["a"]["name"].lower(), p["b"]["name"].lower())) for p in pairs}
    assert frozenset(("peak milk (tin)", "peak milk tin")) in names
    assert all("item" not in n for pair in names for n in pair)


@pytest.mark.parametrize("ask,expect", [
    ("do I have paracetemol?", "Yes"),
    ("is groundnut oil in my stock?", "Yes"),
    ("have I added semovita before?", "Yes"),
    ("do I have g/nut oil", "Yes"),
    ("do i have sardine", "No — there's nothing like *sardine*"),
])
def test_titi_answers_do_i_have(db, ask, expect):
    reply = handle_natural_language_query(db, OWNER, ask)
    assert reply and reply.startswith(expect), reply
    if expect.startswith("No"):
        assert "609 products" in reply


def test_titi_lists_duplicates(db):
    reply = handle_natural_language_query(db, OWNER, "check duplicates")
    assert "same product entered twice" in reply and "Peak Milk Tin" in reply
