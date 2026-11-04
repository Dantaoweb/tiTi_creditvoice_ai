"""
Business page routes (business_page.py):
  public   GET/POST /b/{slug}                  — the page, and "Ask for a quotation"
  owner    GET/PUT  /app/api/business-page     — what the page shows
           GET      /app/api/business-page/enquiries, POST …/{id}/quote | …/{id}/close
  admin    POST     /app/api/admin/business-page/{user_id} — switch on after the one-time payment
"""
from typing import Optional
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from database import SessionLocal
from models import InventoryItem, PageEnquiry, User
from web_auth import require_web_auth
from web_common import _session_owner_phone, _session_user


class PageSettingsRequest(BaseModel):
    on: Optional[bool] = None
    about: Optional[str] = Field(default=None, max_length=2000)
    hours: Optional[str] = Field(default=None, max_length=300)
    show_prices: Optional[bool] = None
    items: Optional[list[int]] = Field(default=None, max_length=500)


class AdminPageRequest(BaseModel):
    enabled: bool
    slug: Optional[str] = Field(default=None, max_length=80)


def register_business_page_routes(app):
    import business_page as bp

    def _live_owner(db, slug):
        owner = db.query(User).filter(User.page_slug == bp.slugify(slug)).first()
        return owner if bp.is_live(db, owner) else None

    # ── Public ─────────────────────────────────────────────────────────────
    @app.get("/b/{slug}", response_class=HTMLResponse)
    def public_business_page(slug: str, sent: int = 0):
        db = SessionLocal()
        try:
            owner = _live_owner(db, slug)
            if not owner:
                return HTMLResponse(bp.not_found_html(), status_code=404)
            return HTMLResponse(bp.render_page(bp.public_data(db, owner), sent=bool(sent)))
        finally:
            db.close()

    @app.post("/b/{slug}", response_class=HTMLResponse)
    async def public_business_enquiry(slug: str, request: Request):
        """A plain HTML form post, so it works on any phone without JavaScript."""
        raw = (await request.body())[:20000].decode("utf-8", "replace")
        form = {k: v[0] for k, v in parse_qs(raw).items()}
        db = SessionLocal()
        try:
            owner = _live_owner(db, slug)
            if not owner:
                return HTMLResponse(bp.not_found_html(), status_code=404)
            if form.get("website"):                     # filled by bots only
                return RedirectResponse(f"/b/{owner.page_slug}?sent=1#ask", status_code=303)
            from web_pay_link_routes import _throttle
            try:
                _throttle(request, limit=10)
                wanted = {k[1:]: v for k, v in form.items() if k.startswith("q") and k[1:].isdigit() and v.strip()}
                bp.add_enquiry(db, owner, form.get("name"), form.get("phone"), form.get("message"), wanted)
            except (bp.PageError, HTTPException) as e:
                msg = e.detail if isinstance(e, HTTPException) else str(e)
                return HTMLResponse(bp.render_page(bp.public_data(db, owner), error=msg, form=form), status_code=400)
            return RedirectResponse(f"/b/{owner.page_slug}?sent=1#ask", status_code=303)
        finally:
            db.close()

    # ── The owner ──────────────────────────────────────────────────────────
    def _owner_of(db, session):
        return db.query(User).filter(User.phone == _session_owner_phone(db, session)).first()

    def _can_see_enquiries(db, session):
        u = _session_user(db, session)
        if not u or not (u.parent_id is None or u.can_view_all_transactions):
            raise HTTPException(status_code=403, detail="Only the owner and staff allowed to see all records can see these.")

    def _state(db, owner):
        from app_settings import get_business_settings
        cfg = get_business_settings(db, owner.phone)
        products = (db.query(InventoryItem)
                    .filter(InventoryItem.owner_phone == owner.phone, InventoryItem.is_available.isnot(False))
                    .order_by(InventoryItem.category, InventoryItem.name).limit(3000).all())
        new = db.query(PageEnquiry).filter(PageEnquiry.owner_phone == owner.phone, PageEnquiry.status == "new").count()
        return {
            "enabled": bool(owner.page_enabled),
            "slug": owner.page_slug,
            "url": bp.page_url(owner) if owner.page_enabled else None,
            "live": bp.is_live(db, owner),
            "on": bool(cfg.get("page_on")),
            "about": cfg.get("page_about") or "",
            "hours": cfg.get("page_hours") or "",
            "show_prices": bool(cfg.get("page_show_prices")),
            "items": cfg.get("page_items") or [],
            "max_items": bp.MAX_ITEMS,
            "products": [{"id": p.id, "name": (p.name or "").title(), "category": (p.category or "").title() or None,
                          "price": int(p.selling_price) if p.selling_price else None, "unit": p.unit}
                         for p in products],
            "new_enquiries": new,
        }

    @app.get("/app/api/business-page")
    def web_business_page(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            return _state(db, _owner_of(db, session))
        finally:
            db.close()

    @app.put("/app/api/business-page")
    def web_business_page_save(payload: PageSettingsRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            if _session_user(db, session).parent_id is not None:
                raise HTTPException(status_code=403, detail="Only the owner can change the business page.")
            owner = _owner_of(db, session)
            if not owner.page_enabled:
                raise HTTPException(status_code=403, detail="Your business page isn't active yet. Contact CreditVoice to get it.")
            changes = {k: v for k, v in {"page_on": payload.on, "page_about": payload.about,
                                         "page_hours": payload.hours, "page_show_prices": payload.show_prices,
                                         "page_items": payload.items}.items() if v is not None}
            if "page_items" in changes and len(changes["page_items"]) > bp.MAX_ITEMS:
                raise HTTPException(status_code=400, detail=f"Show up to {bp.MAX_ITEMS} products.")
            from app_settings import set_business_settings
            try:
                set_business_settings(db, owner.phone, changes)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return _state(db, owner)
        finally:
            db.close()

    @app.get("/app/api/business-page/enquiries")
    def web_page_enquiries(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _can_see_enquiries(db, session)
            rows = (db.query(PageEnquiry).filter(PageEnquiry.owner_phone == _session_owner_phone(db, session))
                    .order_by(PageEnquiry.created_at.desc()).limit(300).all())
            return {"enquiries": [bp.enquiry_row(e) for e in rows]}
        finally:
            db.close()

    def _enquiry(db, session, enquiry_id):
        _can_see_enquiries(db, session)
        e = db.query(PageEnquiry).filter(PageEnquiry.id == enquiry_id,
                                         PageEnquiry.owner_phone == _session_owner_phone(db, session)).first()
        if not e:
            raise HTTPException(status_code=404, detail="That request was not found.")
        return e

    @app.post("/app/api/business-page/enquiries/{enquiry_id}/quote")
    def web_page_enquiry_quote(enquiry_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            e = _enquiry(db, session, enquiry_id)
            from invoices import InvoiceError
            try:
                inv = bp.quote_from_enquiry(db, _owner_of(db, session), e, session["user_id"])
            except (bp.PageError, InvoiceError) as err:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(err))
            return {"invoice_id": inv.id, "enquiry": bp.enquiry_row(e)}
        finally:
            db.close()

    @app.post("/app/api/business-page/enquiries/{enquiry_id}/close")
    def web_page_enquiry_close(enquiry_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            e = _enquiry(db, session, enquiry_id)
            e.status = "closed" if e.status != "closed" else "new"
            db.commit()
            return bp.enquiry_row(e)
        finally:
            db.close()

    # ── Admin: switch it on once paid ──────────────────────────────────────
    @app.post("/app/api/admin/business-page/{user_id}")
    def admin_business_page(user_id: str, payload: AdminPageRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from admin import is_app_admin
            me = _session_user(db, session)
            if not me or not is_app_admin(me.phone, db):
                raise HTTPException(status_code=403, detail="Admin only.")
            owner = db.query(User).filter(User.id == user_id, User.parent_id.is_(None)).first()
            if not owner:
                raise HTTPException(status_code=404, detail="Business not found.")
            try:
                bp.enable(db, owner, payload.enabled, payload.slug)
            except bp.PageError as e:
                raise HTTPException(status_code=400, detail=str(e))
            if payload.enabled:
                from web_common import _add_notification
                _add_notification(db, owner.phone, "page_enabled", "🌐 Your business page is ready",
                                  f"{bp.page_url(owner)} — choose what it shows, then turn it on.", link="/business-page")
                db.commit()
            return {"page_enabled": bool(owner.page_enabled), "page_slug": owner.page_slug,
                    "page_url": bp.page_url(owner)}
        finally:
            db.close()
