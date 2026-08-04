"""
Dashboard + Fast Mode routes: the dashboard summary (branch-scoped) and the
fast-capture (market mode) settings get/toggle.

Split out of web_routes.py. Register with register_dashboard_routes(app);
shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, InventoryItem, FastCaptureSettings
from reports import (
    get_dashboard_summary, get_unpaid_debtors, get_product_sales_by_period,
    get_margin_summary, dashboard_period_label,
)
from web_auth import require_web_auth
from web_common import _session_owner_phone, _scoped_read


class FastModeToggleRequest(BaseModel):
    enabled: bool
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None


class SetBusinessTypeRequest(BaseModel):
    business_type: str = Field(max_length=60)


def register_dashboard_routes(app):

    # ── Dashboard ────────────────────────────────────────────────────────
    @app.get("/app/api/dashboard")
    def web_dashboard(
        period: Optional[str] = Query(default="TODAY"),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            # Enforce branch isolation: a branch staff is locked to their branch,
            # an unassigned staff to their own records; an owner may filter by the
            # branch they picked. eff_branch/rec flow into every figure below.
            eff_branch, rec = _scoped_read(db, session, branch_id)
            summary = get_dashboard_summary(db, owner_phone, period_key, recorded_by_id=rec, branch_id=eff_branch)
            debtors, _ = get_unpaid_debtors(db, owner_phone, recorded_by_id=rec, branch_id=eff_branch)
            low_stock_q = db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner_phone,
                InventoryItem.is_available == True,
                InventoryItem.low_stock_alert != None,
                InventoryItem.quantity <= InventoryItem.low_stock_alert,
            )
            if eff_branch is not None:
                low_stock_q = low_stock_q.filter(InventoryItem.branch_id == eff_branch)
            low_stock_count = low_stock_q.count()
            top_products_raw = get_product_sales_by_period(db, owner_phone, period_key, recorded_by_id=rec, branch_id=eff_branch)[:8]
            margin = get_margin_summary(db, owner_phone, period_key, recorded_by_id=rec, branch_id=eff_branch)
            return {
                "period": period_key,
                "period_label": dashboard_period_label(period_key),
                "owner_phone": owner_phone,
                "summary": summary,
                "low_stock_count": low_stock_count,
                "top_debtors": sorted(
                    debtors,
                    key=lambda row: row["balance"],
                    reverse=True,
                )[:5],
                "top_products": [
                    {
                        "name": r.product,
                        "qty": r.total_quantity,
                        "amount": r.total_amount,
                    }
                    for r in top_products_raw
                ],
                "margin": {
                    "expected": margin["expected"],
                    "actual": margin["actual"],
                    "discount_gap": margin["discount_gap"],
                    "below_cost_products": margin["below_cost_products"],
                },
            }
        finally:
            db.close()

    # ── Get started (empty-state guidance + business-type inference) ──────────
    @app.get("/app/api/getting-started")
    def web_getting_started(session: dict = Depends(require_web_auth)):
        """Drives the web get-started card: whether the business still has no
        priced stock, whether its type is unset/generic, and — when there's
        enough signal — an inferred business-type suggestion."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            owner = db.query(User).filter(User.phone == owner_phone).first()

            priced_stock = db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner_phone,
                InventoryItem.selling_price != None,
            ).count()

            btype = (getattr(owner, "business_type", None) or "").strip()
            needs_type = (not btype) or btype.startswith("other_")

            suggestion = None
            if needs_type:
                try:
                    from business_inference import suggest_business_type
                    suggestion = suggest_business_type(db, owner_phone)
                except Exception:
                    import traceback; traceback.print_exc()

            return {
                "has_priced_stock": priced_stock > 0,
                "business_type": btype or None,
                "business_type_label": getattr(owner, "business_type_label", None),
                "needs_type": needs_type,
                "suggestion": suggestion,
            }
        finally:
            db.close()

    @app.post("/app/api/getting-started/business-type")
    def web_set_business_type(payload: SetBusinessTypeRequest, session: dict = Depends(require_web_auth)):
        """Set the owner's business type (drives templates, stock fields, and
        receipts). Owner-only; the type must be a real one from the taxonomy."""
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.id == session["user_id"]).first()
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can set the business type.")
            from business_inference import _type_meta
            key, label, category = _type_meta(payload.business_type.strip())
            if not key:
                raise HTTPException(status_code=400, detail="Unknown business type.")
            owner.business_type = key
            owner.business_category = category
            # Only set the display label if the owner hasn't customised one.
            if not (owner.business_type_label or "").strip():
                owner.business_type_label = label
            db.commit()
            return {"ok": True, "business_type": key, "business_type_label": owner.business_type_label,
                    "business_category": category}
        finally:
            db.close()

    # ── Fast Mode ────────────────────────────────────────────────────────
    @app.get("/app/api/fast-mode")
    def web_fast_mode_get(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.phone == session["phone"]).first()
            if not user:
                return {"enabled": False, "start_hour": 8, "end_hour": 18}
            owner_phone = session["phone"]
            if user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else session["phone"]
            settings = db.query(FastCaptureSettings).filter(
                FastCaptureSettings.owner_phone == owner_phone
            ).first()
            if not settings:
                return {"enabled": False, "start_hour": 8, "end_hour": 18}
            return {
                "enabled": settings.enabled,
                "start_hour": settings.market_start_hour,
                "end_hour": settings.market_end_hour,
            }
        finally:
            db.close()

    @app.post("/app/api/fast-mode")
    def web_fast_mode_toggle(payload: FastModeToggleRequest, session: dict = Depends(require_web_auth)):
        from fast_capture_commands import get_or_create_fast_capture_settings
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.phone == session["phone"]).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found.")
            owner_phone = session["phone"]
            if user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else session["phone"]
            settings = get_or_create_fast_capture_settings(db, owner_phone)
            settings.enabled = payload.enabled
            if payload.start_hour is not None:
                settings.market_start_hour = payload.start_hour
            if payload.end_hour is not None:
                settings.market_end_hour = payload.end_hour
            db.commit()
            return {"ok": True, "enabled": settings.enabled}
        finally:
            db.close()
