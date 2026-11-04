"""
Production (production.py): a bakery's recipe, a bake that puts loaves into
stock and takes the flour, sugar and yeast out, the real cost per loaf, using
more than is in stock, and undoing a mistake.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-production-000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import InventoryItem, InventoryMovement, StockBatch, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _bakery():
    phone = f"2347081{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Mama Tee Bakery", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(phone=phone).one()
        u.business_type = "bakery"; u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
        mk = lambda name, unit, qty, cost, sell=None: InventoryItem(   # noqa: E731
            owner_phone=phone, name=name, unit=unit, quantity=qty, cost_price=cost, selling_price=sell, is_available=True)
        flour, sugar, yeast = mk("flour", "bag", 10, 60000), mk("sugar", "kg", 20, 1500), mk("yeast", "kg", 3, 8000)
        loaf = mk("bread large loaf", "loaf", 0, None, 1500)
        db.add_all([flour, sugar, yeast, loaf]); db.commit()
        ids = {"flour": flour.id, "sugar": sugar.id, "yeast": yeast.id, "loaf": loaf.id, "uid": u.id}
    finally:
        db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies, ids


def _q(item_id):
    db = SessionLocal()
    try:
        it = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
        return it.quantity, it.cost_price
    finally:
        db.close()


def _recipe(cook, ids, extra=4000):
    # 1 bag flour + 2 kg sugar + 0.5 kg yeast + ₦4,000 gas & labour → 80 loaves
    return client.put(f"/app/api/production/recipe/{ids['loaf']}", cookies=cook, json={
        "yield_qty": 80, "extra_cost": extra, "lines": [
            {"item_id": ids["flour"], "qty": 1}, {"item_id": ids["sugar"], "qty": 2}, {"item_id": ids["yeast"], "qty": 0.5}]})


def test_recipe_then_a_bake_moves_stock_and_costs_the_loaf():
    _phone, cook, ids = _bakery()
    r = _recipe(cook, ids)
    assert r.status_code == 200, r.text
    assert [l["name"] for l in r.json()["recipe"]["lines"]] == ["Flour", "Sugar", "Yeast"]
    home = {i["id"]: i for i in client.get("/app/api/production", cookies=cook).json()["items"]}
    assert home[ids["loaf"]]["has_recipe"] and not home[ids["flour"]]["has_recipe"]

    # Plan 160 loaves = 2 batches: 2 bags flour, 4 kg sugar, 1 kg yeast
    p = client.post("/app/api/production/plan", cookies=cook, json={"product_id": ids["loaf"], "made_qty": 160}).json()
    assert p["batches"] == 2
    assert {l["name"]: l["qty"] for l in p["lines"]} == {"Flour": 2, "Sugar": 4, "Yeast": 1}
    # 2×60,000 + 4×1,500 + 1×8,000 = 134,000 materials + 8,000 gas & labour = 142,000 → ₦887.50 a loaf
    assert (p["materials_cost"], p["extra_cost"], p["total_cost"]) == (134000, 8000, 142000)
    assert p["cost_per_unit"] == 887.5 and p["short"] == []

    run = client.post("/app/api/production/runs", cookies=cook, json={
        "product_id": ids["loaf"], "made_qty": 160, "expiry_date": "2054-11-08"})
    assert run.status_code == 200, run.text
    assert _q(ids["loaf"]) == (160, 888)                    # in stock, at the real cost
    assert _q(ids["flour"])[0] == 8 and _q(ids["sugar"])[0] == 16 and _q(ids["yeast"])[0] == 2
    db = SessionLocal()
    try:
        assert db.query(StockBatch).filter(StockBatch.item_id == ids["loaf"]).one().expiry_date.day == 8
        used = db.query(InventoryMovement).filter(InventoryMovement.source_type == "PRODUCTION_USE",
                                                  InventoryMovement.item_id == ids["flour"]).one()
        assert used.quantity == 2 and "Used to make 160" in used.note
    finally:
        db.close()

    # A second bake at a different cost: the cost price is the average of both
    client.put(f"/app/api/production/recipe/{ids['loaf']}", cookies=cook, json={
        "yield_qty": 80, "extra_cost": 0, "lines": [{"item_id": ids["flour"], "qty": 1}]})   # 60,000/80 = 750
    client.post("/app/api/production/runs", cookies=cook, json={"product_id": ids["loaf"], "made_qty": 80})
    assert _q(ids["loaf"]) == (240, round((160 * 888 + 80 * 750) / 240))

    lst = client.get("/app/api/production/runs", cookies=cook).json()
    assert len(lst["runs"]) == 2 and lst["totals"][0]["made"] == 240


def test_what_was_really_used_and_other_costs_can_differ_from_the_recipe():
    _phone, cook, ids = _bakery()
    _recipe(cook, ids)
    run = client.post("/app/api/production/runs", cookies=cook, json={
        "product_id": ids["loaf"], "made_qty": 75, "extra_cost": 5000,
        "lines": [{"item_id": ids["flour"], "qty": 1}, {"item_id": ids["sugar"], "qty": 2.5}]}).json()
    assert run["made_qty"] == 75 and run["total_cost"] == 60000 + 3750 + 5000
    assert _q(ids["sugar"])[0] == 17.5 and _q(ids["yeast"])[0] == 3          # yeast not used this time


def test_not_enough_in_stock_is_refused_unless_recorded_anyway():
    _phone, cook, ids = _bakery()
    _recipe(cook, ids)
    # 960 loaves = 12 bags of flour; only 10 in stock
    r = client.post("/app/api/production/runs", cookies=cook, json={"product_id": ids["loaf"], "made_qty": 960})
    assert r.status_code == 400 and "Flour (need 12, have 10)" in r.json()["detail"]
    assert _q(ids["loaf"])[0] == 0
    r = client.post("/app/api/production/runs", cookies=cook, json={
        "product_id": ids["loaf"], "made_qty": 960, "allow_short": True})
    assert r.status_code == 200
    assert _q(ids["flour"])[0] == 0 and _q(ids["loaf"])[0] == 960

    # Undo puts back only what really came out (10 bags, not 12)
    assert client.post(f"/app/api/production/runs/{r.json()['id']}/undo", cookies=cook).status_code == 200
    assert _q(ids["flour"])[0] == 10 and _q(ids["loaf"])[0] == 0


def test_undo_only_while_what_was_made_is_still_there():
    phone, cook, ids = _bakery()
    _recipe(cook, ids)
    run = client.post("/app/api/production/runs", cookies=cook, json={"product_id": ids["loaf"], "made_qty": 80}).json()
    # 10 loaves sold
    client.post("/app/api/pos/save", cookies=cook, json={"owner_phone": phone, "payment_amount": 15000, "items": [
        {"inventory_item_id": ids["loaf"], "name": "bread large loaf", "qty": 10, "unit_price": 1500}]})
    r = client.post(f"/app/api/production/runs/{run['id']}/undo", cookies=cook)
    assert r.status_code == 400 and "sold or used" in r.json()["detail"]


def test_recipe_rules():
    _phone, cook, ids = _bakery()
    url = f"/app/api/production/recipe/{ids['loaf']}"
    assert client.put(url, cookies=cook, json={"yield_qty": 80, "lines": []}).status_code == 400
    assert "itself" in client.put(url, cookies=cook, json={
        "yield_qty": 80, "lines": [{"item_id": ids["loaf"], "qty": 1}]}).json()["detail"]
    assert client.put(url, cookies=cook, json={"yield_qty": 0, "lines": [{"item_id": ids["flour"], "qty": 1}]}).status_code == 400
    assert client.put(url, cookies=cook, json={"yield_qty": 80, "lines": [
        {"item_id": ids["flour"], "qty": 1}, {"item_id": ids["flour"], "qty": 2}]}).status_code == 400
    # No recipe and nothing listed: the loaves still go in, at no recorded cost
    run = client.post("/app/api/production/runs", cookies=cook, json={"product_id": ids["loaf"], "made_qty": 5}).json()
    assert run["total_cost"] == 0 and _q(ids["loaf"]) == (5, None)


def test_only_stock_managers_and_only_your_own_stock():
    phone, cook, ids = _bakery()
    _other, other_cook, _o = _bakery()
    db = SessionLocal()
    sp = f"2347082{next(_seq):06d}"
    db.add(User(phone=sp, name="Baker", role="delegate", parent_id=ids["uid"],
                recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE"))
    db.commit(); db.close()
    staff = client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies
    assert client.get("/app/api/production", cookies=staff).status_code == 403
    assert client.post("/app/api/production/runs", cookies=staff, json={"product_id": ids["loaf"], "made_qty": 1}).status_code == 403
    # Another business can't use this bakery's stock
    assert client.post("/app/api/production/runs", cookies=other_cook, json={
        "product_id": ids["loaf"], "made_qty": 1}).status_code == 400
    assert client.put(f"/app/api/production/recipe/{ids['loaf']}", cookies=other_cook, json={
        "yield_qty": 1, "lines": [{"item_id": ids["flour"], "qty": 1}]}).status_code == 400


def test_titi_explains_production():
    from faq import FAQ_ANSWERS, detect_faq
    assert detect_faq("how do i add a recipe?") == "production"
    assert detect_faq("i bake bread, how do i record it?") == "production"
    assert detect_faq("how do i sell my farm produce?") != "production"
    assert "Record production" in FAQ_ANSWERS["production"]
