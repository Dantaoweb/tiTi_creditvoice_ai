"""
Settings page routes (app_settings.py) and stock categories.

- Display choices: each person their own.
- Business choices and categories: owner and authorised staff only.
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from database import SessionLocal
from models import InventoryItem, User
from web_auth import require_web_auth
from web_common import _session_owner_phone, _session_user


class DisplayRequest(BaseModel):
    text_size: Optional[str] = Field(default=None, max_length=10)
    theme: Optional[str] = Field(default=None, max_length=10)
    density: Optional[str] = Field(default=None, max_length=12)
    scan_mode: Optional[str] = Field(default=None, max_length=8)


class BusinessRequest(BaseModel):
    values: dict = Field(default_factory=dict)


class RenameCategoryRequest(BaseModel):
    old: str = Field(max_length=60)
    new: str = Field(max_length=60)


class AssignCategoryRequest(BaseModel):
    item_ids: list[int] = Field(max_length=1000)
    category: Optional[str] = Field(default=None, max_length=60)   # None / "" = uncategorised


class CameraCrashRequest(BaseModel):
    user_agent: str = Field(default="", max_length=400)
    stage: Optional[str] = Field(default=None, max_length=20)
    details: Optional[dict] = None
    crashed_at: Optional[str] = Field(default=None, max_length=40)


class ApplySuggestionsRequest(BaseModel):
    items: list[dict] = Field(max_length=2000)    # [{id, category}]


def _require_business_editor(db, session):
    user = _session_user(db, session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    if user.parent_id is not None and not user.can_view_all_transactions:
        raise HTTPException(status_code=403, detail="Only the owner or an authorised staff member "
                                                    "can change business settings.")
    return user


def _categories(db, owner_phone, branch_id=None):
    """Every category in use, with how many products and what they're worth,
    in the owner's chosen order. Branch staff count their branch's stock."""
    from app_settings import get_business_settings
    q = (db.query(InventoryItem.category, func.count(InventoryItem.id),
                  func.coalesce(func.sum(InventoryItem.quantity * InventoryItem.selling_price), 0))
         .filter(InventoryItem.owner_phone == owner_phone))
    if branch_id is not None:
        q = q.filter(InventoryItem.branch_id == branch_id)
    rows = q.group_by(InventoryItem.category).all()
    order = get_business_settings(db, owner_phone)["category_order"]
    out, none_row = [], None
    for cat, count, value in rows:
        entry = {"name": cat, "label": (cat or "Uncategorised").title(), "count": int(count),
                 "value": int(value or 0), "is_service": cat == "service"}
        if not cat:
            none_row = entry
        else:
            out.append(entry)
    rank = {c: i for i, c in enumerate(order)}
    out.sort(key=lambda e: (rank.get(e["name"], 10_000), e["name"] == "service", e["name"]))
    if none_row:
        out.append(none_row)
    return out


def register_settings_routes(app):

    @app.get("/app/api/settings")
    def web_get_settings(session: dict = Depends(require_web_auth)):
        from app_settings import get_business_settings, get_display
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user:
                raise HTTPException(status_code=401, detail="Not authenticated.")
            owner_phone = _session_owner_phone(db, session)
            can_edit = user.parent_id is None or bool(user.can_view_all_transactions)
            return {"display": get_display(user), "business": get_business_settings(db, owner_phone),
                    "can_edit_business": can_edit}
        finally:
            db.close()

    @app.put("/app/api/settings/display")
    def web_set_display(payload: DisplayRequest, session: dict = Depends(require_web_auth)):
        from app_settings import set_display
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="Not authenticated.")
            try:
                display = set_display(user, payload.model_dump(exclude_none=True))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return {"display": display}
        finally:
            db.close()

    @app.put("/app/api/settings/business")
    def web_set_business(payload: BusinessRequest, session: dict = Depends(require_web_auth)):
        from app_settings import set_business_settings
        db = SessionLocal()
        try:
            _require_business_editor(db, session)
            try:
                business = set_business_settings(db, _session_owner_phone(db, session), payload.values)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return {"business": business}
        finally:
            db.close()

    # ── Camera crash reports (phones that go off when the scanner opens) ──
    @app.post("/app/api/client/camera-crash")
    def web_camera_crash(payload: CameraCrashRequest, session: dict = Depends(require_web_auth)):
        import json as _json
        from datetime import datetime as _dt
        from models import CameraCrashReport
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            # A real crash is reported once per relaunch; a few a day is plenty
            from datetime import timedelta as _td
            if user and db.query(CameraCrashReport).filter(
                    CameraCrashReport.user_id == user.id,
                    CameraCrashReport.created_at >= _dt.utcnow() - _td(days=1)).count() >= 5:
                return {"ok": True, "ignored": True}
            when = None
            try:
                when = _dt.fromisoformat((payload.crashed_at or "").replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
            db.add(CameraCrashReport(
                user_id=user.id if user else None,
                owner_phone=_session_owner_phone(db, session),
                user_agent=(payload.user_agent or "")[:400],
                stage=payload.stage,
                details=_json.dumps(payload.details or {})[:2000],
                crashed_at=when,
            ))
            db.commit()
            print(f"[camera-crash] {payload.stage} {payload.user_agent[:160]}", flush=True)
            return {"ok": True}
        finally:
            db.close()

    @app.get("/app/api/settings/print-preview")
    def web_print_preview(session: dict = Depends(require_web_auth)):
        """The business's real header details for the Receipts & printables
        preview (the page applies the choices as they change)."""
        from invoices import _business_header
        from printables import bank_accounts
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            doc = _business_header(db, owner_phone, None, kind="receipt")
            owner = db.query(User).filter(User.phone == owner_phone).first()
            doc["all_bank_accounts"] = bank_accounts(owner) if owner else []
            return doc
        finally:
            db.close()

    @app.get("/app/api/reports/vat")
    def web_vat_report(session: dict = Depends(require_web_auth)):
        """VAT collected this month and last (for filing) — owner and
        authorised staff only, like profit."""
        from datetime import datetime, timezone
        from sqlalchemy import func as _f
        from models import Transaction
        from reports import get_owner_transaction_query
        from web_common import _can_see_profit
        db = SessionLocal()
        try:
            if not _can_see_profit(db, session):
                raise HTTPException(status_code=403, detail="Only the owner or authorised staff see VAT totals.")
            owner_phone = _session_owner_phone(db, session)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            this_m = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_m = (this_m.replace(year=this_m.year - 1, month=12) if this_m.month == 1
                      else this_m.replace(month=this_m.month - 1))

            def total(start, end):
                q = (get_owner_transaction_query(db, owner_phone)
                     .filter(Transaction.vat_amount.isnot(None), Transaction.created_at >= start))
                if end is not None:
                    q = q.filter(Transaction.created_at < end)
                return int(q.with_entities(_f.coalesce(_f.sum(Transaction.vat_amount), 0)).scalar() or 0)
            return {"this_month": total(this_m, None), "last_month": total(last_m, this_m),
                    "month": this_m.strftime("%B %Y"), "last_month_name": last_m.strftime("%B %Y")}
        finally:
            db.close()

    @app.get("/app/api/admin/camera-crashes")
    def web_camera_crashes(session: dict = Depends(require_web_auth)):
        """Which phones and browsers crash on opening the camera, for app admins."""
        from models import CameraCrashReport
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            from admin import is_app_admin
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admins only.")
            rows = db.query(CameraCrashReport).order_by(CameraCrashReport.id.desc()).limit(200).all()
            return {"reports": [{
                "user_agent": r.user_agent, "stage": r.stage, "details": r.details,
                "owner_phone": r.owner_phone,
                "crashed_at": r.crashed_at.isoformat() if r.crashed_at else None,
                "reported_at": r.created_at.isoformat() if r.created_at else None,
            } for r in rows]}
        finally:
            db.close()

    # ── Stock categories ──────────────────────────────────────────────────
    @app.get("/app/api/categories")
    def web_categories(session: dict = Depends(require_web_auth)):
        from web_common import _scoped_read
        db = SessionLocal()
        try:
            branch_id, _rec = _scoped_read(db, session)
            return {"categories": _categories(db, _session_owner_phone(db, session), branch_id)}
        finally:
            db.close()

    @app.get("/app/api/categories/suggest")
    def web_category_suggest(name: str = "", session: dict = Depends(require_web_auth)):
        from app_settings import suggest_category
        db = SessionLocal()
        try:
            return {"category": suggest_category(db, _session_owner_phone(db, session), name[:120])}
        finally:
            db.close()

    @app.post("/app/api/categories/rename")
    def web_rename_category(payload: RenameCategoryRequest, session: dict = Depends(require_web_auth)):
        """Rename (or merge into another) category for every product in it."""
        from app_settings import clean_category, get_business_settings, set_business_settings
        db = SessionLocal()
        try:
            _require_business_editor(db, session)
            owner_phone = _session_owner_phone(db, session)
            old = (payload.old or "").strip().lower()
            if old == "service":
                raise HTTPException(status_code=400, detail="'Service' marks services and can't be renamed.")
            try:
                new = clean_category(payload.new)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            if not new:
                raise HTTPException(status_code=400, detail="Enter the new name.")
            n = (db.query(InventoryItem)
                 .filter(InventoryItem.owner_phone == owner_phone, InventoryItem.category == old)
                 .update({InventoryItem.category: new}, synchronize_session=False))
            order = get_business_settings(db, owner_phone)["category_order"]
            order = [new if c == old else c for c in order]
            set_business_settings(db, owner_phone, {"category_order": list(dict.fromkeys(order))})
            db.commit()
            return {"renamed": n, "categories": _categories(db, owner_phone)}
        finally:
            db.close()

    @app.post("/app/api/categories/assign")
    def web_assign_category(payload: AssignCategoryRequest, session: dict = Depends(require_web_auth)):
        """Put many products into one category at once (services stay services)."""
        from app_settings import clean_category
        db = SessionLocal()
        try:
            _require_business_editor(db, session)
            owner_phone = _session_owner_phone(db, session)
            try:
                cat = clean_category(payload.category) if payload.category else None
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            n = (db.query(InventoryItem)
                 .filter(InventoryItem.owner_phone == owner_phone,
                         InventoryItem.id.in_(payload.item_ids or [0]),
                         (InventoryItem.category.is_(None)) | (InventoryItem.category != "service"))
                 .update({InventoryItem.category: cat}, synchronize_session=False))
            db.commit()
            return {"assigned": n, "categories": _categories(db, owner_phone)}
        finally:
            db.close()

    @app.get("/app/api/categories/auto")
    def web_category_auto(session: dict = Depends(require_web_auth)):
        """tiTi's suggested category for each uncategorised product — shown
        for the owner to check before anything changes."""
        from app_settings import suggest_category
        db = SessionLocal()
        try:
            _require_business_editor(db, session)
            owner_phone = _session_owner_phone(db, session)
            items = (db.query(InventoryItem)
                     .filter(InventoryItem.owner_phone == owner_phone,
                             (InventoryItem.category.is_(None)) | (InventoryItem.category == ""))
                     .all())
            out = []
            for i in items:
                if i.quantity is None:
                    continue
                cat = suggest_category(db, owner_phone, i.name)
                if cat:
                    out.append({"id": i.id, "name": (i.name or "").title(), "category": cat})
            return {"suggestions": out, "uncategorised": len(items)}
        finally:
            db.close()

    @app.post("/app/api/categories/auto")
    def web_category_auto_apply(payload: ApplySuggestionsRequest, session: dict = Depends(require_web_auth)):
        from app_settings import clean_category
        db = SessionLocal()
        try:
            _require_business_editor(db, session)
            owner_phone = _session_owner_phone(db, session)
            done = 0
            for row in payload.items:
                try:
                    cat = clean_category(str(row.get("category") or ""))
                except ValueError:
                    continue
                if not cat:
                    continue
                done += (db.query(InventoryItem)
                         .filter(InventoryItem.owner_phone == owner_phone,
                                 InventoryItem.id == int(row.get("id") or 0),
                                 (InventoryItem.category.is_(None)) | (InventoryItem.category == ""))
                         .update({InventoryItem.category: cat}, synchronize_session=False))
            db.commit()
            return {"applied": done, "categories": _categories(db, owner_phone)}
        finally:
            db.close()
