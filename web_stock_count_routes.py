"""
Stock count on the web (stock_counts.py).

- Anyone who records sales may start a count, count and send it for approval.
- Only the owner or authorised staff approve (stock changes then), and only
  they see what the differences are worth at cost.
- While a blind count is being counted, nobody sees the app's numbers.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import InventoryItem, StockCount
from web_auth import require_web_auth
from web_common import (
    _add_notification, _can_see_profit, _owner_filter, _require_can_record, _scoped_read,
    _session_owner_phone, _session_user,
)


class StartCountRequest(BaseModel):
    category: Optional[str] = Field(default=None, max_length=60)


class CountsRequest(BaseModel):
    counts: Dict[str, Optional[float]] = Field(default_factory=dict)


class ReasonsRequest(BaseModel):
    reasons: Dict[str, Optional[str]] = Field(default_factory=dict)


def _is_approver(user):
    return bool(user and (user.parent_id is None or user.can_view_all_transactions))


def register_stock_count_routes(app):
    from stock_counts import (
        StockCountError, approve_count, cancel_count, count_document, format_count_number,
        list_counts, losses, save_counts, set_reasons, start_count, submit_count,
    )

    def _load(db, session, count_id):
        sc = db.query(StockCount).filter(StockCount.id == count_id,
                                         StockCount.owner_phone == _session_owner_phone(db, session)).first()
        if not sc:
            raise HTTPException(status_code=404, detail="Stock count not found.")
        branch, rec = _scoped_read(db, session)
        if (branch is not None and sc.branch_id != branch) or (rec is not None and sc.created_by_id != rec):
            raise HTTPException(status_code=404, detail="Stock count not found.")
        return sc

    def _doc(db, session, sc):
        user = _session_user(db, session)
        doc = count_document(db, sc, show_expected=not (sc.blind and sc.status == "counting"),
                             show_money=_can_see_profit(db, session))
        doc["can_approve"] = _is_approver(user)
        return doc

    def _run(db, fn):
        try:
            fn()
        except StockCountError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        db.commit()

    @app.get("/app/api/stock-counts")
    def web_stock_counts(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            branch, rec = _scoped_read(db, session)
            rows = list_counts(db, _session_owner_phone(db, session), branch_id=branch)
            if rec is not None:
                mine = {s.id for s in db.query(StockCount.id).filter(StockCount.created_by_id == rec).all()}
                rows = [r for r in rows if r["id"] in mine]
            return {"counts": rows}
        finally:
            db.close()

    @app.get("/app/api/stock-counts/losses")
    def web_stock_losses(days: int = Query(default=30, ge=1, le=366), session: dict = Depends(require_web_auth)):
        """What counts found missing or extra, by reason, at cost — owner and
        authorised staff only, like profit."""
        db = SessionLocal()
        try:
            if not _can_see_profit(db, session):
                raise HTTPException(status_code=403, detail="Only the owner or authorised staff see stock losses.")
            since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
            branch, _rec = _scoped_read(db, session)
            return {"days": days, **losses(db, _session_owner_phone(db, session), since, branch_id=branch)}
        finally:
            db.close()

    @app.post("/app/api/stock-counts")
    def web_start_count(payload: StartCountRequest, session: dict = Depends(require_web_auth)):
        from app_settings import business_setting
        db = SessionLocal()
        try:
            user = _require_can_record(db, session, count_sale=False)
            owner_phone = _session_owner_phone(db, session)
            branch, _rec = _scoped_read(db, session)
            items = _owner_filter(db.query(InventoryItem), InventoryItem, owner_phone)
            if branch is not None:
                items = items.filter(InventoryItem.branch_id == branch)
            box = {}
            _run(db, lambda: box.setdefault("sc", start_count(
                db, owner_phone, user.id, items, category=payload.category, branch_id=branch,
                blind=business_setting(db, owner_phone, "count_blind"))))
            return _doc(db, session, box["sc"])
        finally:
            db.close()

    @app.get("/app/api/stock-counts/{count_id}")
    def web_get_count(count_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            return _doc(db, session, _load(db, session, count_id))
        finally:
            db.close()

    @app.put("/app/api/stock-counts/{count_id}/counts")
    def web_save_counts(count_id: int, payload: CountsRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            sc = _load(db, session, count_id)
            _run(db, lambda: save_counts(db, sc, payload.counts))
            return _doc(db, session, sc)
        finally:
            db.close()

    @app.post("/app/api/stock-counts/{count_id}/submit")
    def web_submit_count(count_id: int, payload: CountsRequest, session: dict = Depends(require_web_auth)):
        """Counting done. The owner is told there's a count to approve."""
        db = SessionLocal()
        try:
            user = _require_can_record(db, session, count_sale=False)
            sc = _load(db, session, count_id)

            def go():
                if payload.counts:
                    save_counts(db, sc, payload.counts)
                submit_count(db, sc, user.id)
            _run(db, go)
            if not _is_approver(user):
                doc = count_document(db, sc)
                _add_notification(
                    db, sc.owner_phone, "stock_count",
                    f"Stock count {format_count_number(sc.number)} to approve",
                    f"{(user.name or 'Staff').title()} counted {doc['counted']} product(s) — "
                    f"{doc['differ']} differ from the app. Stock changes only when you approve.",
                    link=f"/stock-counts/{sc.id}",
                )
                db.commit()
            return _doc(db, session, sc)
        finally:
            db.close()

    @app.put("/app/api/stock-counts/{count_id}/reasons")
    def web_count_reasons(count_id: int, payload: ReasonsRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            sc = _load(db, session, count_id)
            _run(db, lambda: set_reasons(db, sc, payload.reasons))
            return _doc(db, session, sc)
        finally:
            db.close()

    @app.post("/app/api/stock-counts/{count_id}/approve")
    def web_approve_count(count_id: int, payload: ReasonsRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not _is_approver(user):
                raise HTTPException(status_code=403, detail="Only the owner or an authorised staff member "
                                                            "can approve a stock count.")
            sc = _load(db, session, count_id)

            def go():
                if payload.reasons:
                    set_reasons(db, sc, payload.reasons)
                approve_count(db, sc, user.id)
            _run(db, go)
            doc = count_document(db, sc)
            if doc["value_lost"]:
                _add_notification(
                    db, sc.owner_phone, "stock_count",
                    f"Stock count {doc['number']} approved",
                    f"{doc['differ']} product(s) changed. ₦{doc['value_lost']:,} worth of stock was "
                    f"missing, damaged or expired (at cost).",
                    link=f"/stock-counts/{sc.id}",
                )
                db.commit()
            return _doc(db, session, sc)
        finally:
            db.close()

    @app.post("/app/api/stock-counts/{count_id}/cancel")
    def web_cancel_count(count_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            sc = _load(db, session, count_id)
            if not _is_approver(user) and sc.created_by_id != user.id:
                raise HTTPException(status_code=403, detail="Only who started it, or the owner, can cancel a count.")
            _run(db, lambda: cancel_count(db, sc))
            return _doc(db, session, sc)
        finally:
            db.close()
