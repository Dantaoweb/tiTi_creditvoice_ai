"""
Production routes (production.py): recipes, planning a run, recording it,
the list of runs, and undoing a mistake. The stock rule applies: the owner and
staff allowed to manage stock.
"""
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import InventoryItem, Recipe
from web_auth import require_web_auth
from web_common import _require_stock_manager, _scoped_read, _session_owner_phone


class LineIn(BaseModel):
    item_id: int
    qty: float


class RecipeIn(BaseModel):
    yield_qty: float
    extra_cost: int = 0
    note: Optional[str] = Field(default=None, max_length=300)
    lines: list[LineIn] = Field(max_length=60)


class RunIn(BaseModel):
    product_id: int
    made_qty: float
    batches: Optional[float] = None
    lines: Optional[list[LineIn]] = Field(default=None, max_length=60)   # what was really used; None = the recipe
    extra_cost: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=300)
    expiry_date: Optional[str] = None                                     # YYYY-MM-DD
    allow_short: bool = False


def register_production_routes(app):
    import production as pr

    def _ctx(db, session):
        user = _require_stock_manager(db, session)
        branch, _rec = _scoped_read(db, session)
        return user, _session_owner_phone(db, session), branch

    def _err(fn):
        try:
            return fn()
        except pr.ProductionError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/app/api/production")
    def web_production_home(session: dict = Depends(require_web_auth)):
        """The stock list to pick products and materials from, and which have a recipe."""
        db = SessionLocal()
        try:
            _u, owner_phone, branch = _ctx(db, session)
            q = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone,
                                               InventoryItem.is_available.isnot(False))
            if branch is not None:
                q = q.filter((InventoryItem.branch_id == branch) | (InventoryItem.branch_id.is_(None)))
            with_recipe = {r.product_id for r in db.query(Recipe.product_id).filter(Recipe.owner_phone == owner_phone)}
            return {"items": [{"id": i.id, "name": (i.name or "").title(), "unit": i.unit, "category": i.category,
                               "quantity": i.quantity, "cost_price": i.cost_price, "selling_price": i.selling_price,
                               "has_recipe": i.id in with_recipe}
                              for i in q.order_by(InventoryItem.name).limit(5000).all()]}
        finally:
            db.close()

    @app.get("/app/api/production/recipe/{product_id}")
    def web_recipe(product_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _u, owner_phone, _b = _ctx(db, session)
            return {"recipe": pr.recipe_dict(db, pr.get_recipe(db, owner_phone, product_id))}
        finally:
            db.close()

    @app.put("/app/api/production/recipe/{product_id}")
    def web_recipe_save(product_id: int, payload: RecipeIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _u, owner_phone, branch = _ctx(db, session)
            r = _err(lambda: pr.save_recipe(db, owner_phone, product_id, payload.yield_qty,
                                            [l.model_dump() for l in payload.lines], payload.extra_cost,
                                            payload.note, branch))
            return {"recipe": pr.recipe_dict(db, r)}
        finally:
            db.close()

    @app.delete("/app/api/production/recipe/{product_id}")
    def web_recipe_delete(product_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _u, owner_phone, _b = _ctx(db, session)
            pr.delete_recipe(db, owner_phone, product_id)
            return {"ok": True}
        finally:
            db.close()

    def _lines(payload):
        return [l.model_dump() for l in payload.lines] if payload.lines is not None else None

    @app.post("/app/api/production/plan")
    def web_production_plan(payload: RunIn, session: dict = Depends(require_web_auth)):
        """What a run would use and cost — shown before it's recorded."""
        db = SessionLocal()
        try:
            _u, owner_phone, branch = _ctx(db, session)
            return _err(lambda: pr.plan(db, owner_phone, payload.product_id, payload.made_qty, payload.batches,
                                        _lines(payload), payload.extra_cost, branch))
        finally:
            db.close()

    @app.post("/app/api/production/runs")
    def web_production_record(payload: RunIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user, owner_phone, branch = _ctx(db, session)
            expiry = None
            if payload.expiry_date:
                try:
                    expiry = datetime.strptime(payload.expiry_date[:10], "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Pick a valid best-before date.")
            run = _err(lambda: pr.record_run(db, owner_phone, user.id, payload.product_id, payload.made_qty,
                                             batches=payload.batches, lines=_lines(payload),
                                             extra_cost=payload.extra_cost, note=payload.note,
                                             expiry_date=expiry, allow_short=payload.allow_short, branch_id=branch))
            return pr.run_dict(db, run)
        finally:
            db.close()

    @app.get("/app/api/production/runs")
    def web_production_runs(days: int = 30, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _u, owner_phone, branch = _ctx(db, session)
            return pr.list_runs(db, owner_phone, max(1, min(int(days), 366)), branch)
        finally:
            db.close()

    @app.get("/app/api/production/report")
    def web_production_report(days: int = 30, session: dict = Depends(require_web_auth)):
        """Made / sold / removed per product, and materials used vs what the recipes say."""
        db = SessionLocal()
        try:
            _u, owner_phone, branch = _ctx(db, session)
            return pr.report(db, owner_phone, max(1, min(int(days), 366)), branch)
        finally:
            db.close()

    @app.post("/app/api/production/runs/{run_id}/undo")
    def web_production_undo(run_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user, owner_phone, _b = _ctx(db, session)
            return pr.run_dict(db, _err(lambda: pr.undo_run(db, owner_phone, run_id, user.id)))
        finally:
            db.close()
