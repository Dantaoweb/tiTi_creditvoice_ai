"""
Poultry-farm web routes: daily egg collection (production) and daily feed usage
(consumption), plus their daily history. Registered from web_routes.
"""
from typing import List, Optional

from fastapi import Depends, Query
from pydantic import BaseModel

from database import SessionLocal
from models import User
from web_auth import require_web_auth
from web_common import _session_owner_phone
import poultry


class EggRow(BaseModel):
    grade: str
    crates: float = 0


class EggCollectionRequest(BaseModel):
    date: Optional[str] = None
    rows: List[EggRow] = []


class FeedRow(BaseModel):
    item_id: int
    quantity: float = 0


class FeedUsageRequest(BaseModel):
    date: Optional[str] = None
    rows: List[FeedRow] = []


def register_poultry_routes(app):

    @app.get("/app/api/poultry/config")
    def poultry_config(session: dict = Depends(require_web_auth)):
        """Everything the poultry screen needs to render: the egg grades for the
        collection form, the farm's feed products for the usage form, and the
        header summary."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            owner = db.query(User).filter(User.phone == owner_phone).first()
            feeds = poultry.list_feed_items(db, owner_phone)
            return {
                "is_poultry": poultry.is_poultry_user(owner),
                "grades": [{"key": k, "label": lbl} for k, lbl in poultry.EGG_GRADES],
                "eggs_per_crate": poultry.EGGS_PER_CRATE,
                "feeds": [
                    {"id": f.id, "name": f.name, "unit": f.unit or "bag",
                     "in_stock": f.quantity or 0}
                    for f in feeds
                ],
                "summary": poultry.poultry_summary(db, owner_phone),
            }
        finally:
            db.close()

    @app.post("/app/api/poultry/egg-collection")
    def poultry_egg_collection(payload: EggCollectionRequest,
                               session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            total = poultry.record_egg_collection(
                db, owner_phone,
                [r.model_dump() for r in payload.rows],
                recorded_by_id=session["user_id"], date=payload.date,
            )
            return {"crates": total, "summary": poultry.poultry_summary(db, owner_phone)}
        finally:
            db.close()

    @app.post("/app/api/poultry/feed-usage")
    def poultry_feed_usage(payload: FeedUsageRequest,
                           session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            total = poultry.record_feed_usage(
                db, owner_phone,
                [r.model_dump() for r in payload.rows],
                recorded_by_id=session["user_id"], date=payload.date,
            )
            return {"quantity": total, "summary": poultry.poultry_summary(db, owner_phone)}
        finally:
            db.close()

    @app.get("/app/api/poultry/egg-history")
    def poultry_egg_history(days: int = Query(default=30, ge=1, le=180),
                            session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            return {"days": poultry.egg_collection_history(db, owner_phone, days)}
        finally:
            db.close()

    @app.get("/app/api/poultry/feed-history")
    def poultry_feed_history(days: int = Query(default=30, ge=1, le=180),
                             session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            return {"days": poultry.feed_usage_history(db, owner_phone, days)}
        finally:
            db.close()
