"""
Public, crawlable pages: /resources and /events.

Why these are not React pages: the app lives behind a login, so a link there is
invisible to search engines — useless to a partner who asked for one, and
useless for our own SEO. These render as plain HTML on the server, in the same
style as the landing page, from rows an admin can edit.

How links are marked matters and is not cosmetic:
  EDITORIAL  — we recommend it; a normal link that passes authority
  SPONSORED  — paid for or exchanged; rel="sponsored nofollow", as Google asks
  NOFOLLOW   — listed for convenience, no endorsement
"""
import html
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from database import SessionLocal
from models import AuditLog, PublicListing, User, utcnow
from web_auth import require_web_auth
from web_common import _admin_rate_check

SITE = "https://creditvoiceai.com"

_REL = {"EDITORIAL", "SPONSORED", "NOFOLLOW"}

PAGES = {
    "resources": {
        "title": "Resources & Sponsors — CreditVoiceai",
        "description": ("Tools, services and partners we think are worth knowing about, "
                        "and the sponsors supporting CreditVoiceai."),
        "heading": "Resources &amp; sponsors",
        "intro": ("Things we think are worth knowing about, and the people supporting our "
                  "work. Sponsored listings are marked as such."),
        "default_section": "Resources",
    },
    "events": {
        "title": "Events — CreditVoiceai",
        "description": "Workshops, trainings and meet-ups for business owners using CreditVoiceai.",
        "heading": "Events",
        "intro": "Where to find us, and what is coming up for business owners.",
        "default_section": "Events",
    },
}


class ListingRequest(BaseModel):
    page: str = Field(default="resources", max_length=40)
    section: Optional[str] = Field(default=None, max_length=80)
    title: str = Field(max_length=160)
    url: Optional[str] = Field(default=None, max_length=500)
    blurb: Optional[str] = Field(default=None, max_length=1000)
    link_rel: str = Field(default="EDITORIAL", max_length=20)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    event_date: Optional[str] = None          # YYYY-MM-DD
    event_venue: Optional[str] = Field(default=None, max_length=200)
    sort_order: int = 0
    is_active: bool = True


def _esc(value):
    """Everything from the database is escaped before it reaches the page — an
    admin typo must never be able to inject markup."""
    return html.escape(str(value or ""), quote=True)


def _listing_dict(row):
    return {
        "id": row.id,
        "page": row.page,
        "section": row.section,
        "title": row.title,
        "url": row.url,
        "blurb": row.blurb,
        "link_rel": row.link_rel,
        "logo_url": row.logo_url,
        "event_date": row.event_date.date().isoformat() if row.event_date else None,
        "event_venue": row.event_venue,
        "sort_order": row.sort_order or 0,
        "is_active": bool(row.is_active),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
    }


def _rel_tokens(link_rel):
    """rel values for an outbound link. `noopener` is always there for safety and
    does not affect whether the link passes authority; EDITORIAL therefore stays
    a normal dofollow link."""
    tokens = ["noopener"]
    if link_rel == "SPONSORED":
        tokens += ["sponsored", "nofollow"]
    elif link_rel == "NOFOLLOW":
        tokens.append("nofollow")
    return " ".join(tokens)


def _item_html(row, is_event=False):
    title = _esc(row.title)
    if row.url:
        rel = _rel_tokens(row.link_rel or "EDITORIAL")
        head = (f'<h3><a href="{_esc(row.url)}" rel="{rel}" target="_blank">'
                f'{title}</a></h3>')
    else:
        head = f"<h3>{title}</h3>"

    meta = []
    if is_event and row.event_date:
        meta.append(row.event_date.strftime("%d %b %Y"))
    if is_event and row.event_venue:
        meta.append(_esc(row.event_venue))
    if row.link_rel == "SPONSORED":
        meta.append("sponsored")
    meta_html = f'<div class="meta">{" · ".join(meta)}</div>' if meta else ""

    blurb = f"<p>{_esc(row.blurb)}</p>" if row.blurb else ""
    return f"<li>{head}{meta_html}{blurb}</li>"


def _event_jsonld(rows):
    """Structured data so an event can show its date in search results."""
    import json
    events = []
    for row in rows:
        if not row.event_date:
            continue
        entry = {
            "@type": "Event",
            "name": row.title,
            "startDate": row.event_date.date().isoformat(),
            "eventStatus": "https://schema.org/EventScheduled",
        }
        if row.event_venue:
            entry["location"] = {"@type": "Place", "name": row.event_venue}
        if row.url:
            entry["url"] = row.url
        if row.blurb:
            entry["description"] = row.blurb
        events.append(entry)
    if not events:
        return ""
    payload = json.dumps({"@context": "https://schema.org", "@graph": events}, ensure_ascii=False)
    return f'<script type="application/ld+json">{payload}</script>'


def _page_html(page_key, rows):
    cfg = PAGES[page_key]
    is_event_page = page_key == "events"
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Events split themselves into upcoming and past, so the page never looks
    # abandoned because last year's workshop is sitting at the top.
    groups = []
    if is_event_page:
        upcoming = [r for r in rows if not r.event_date or r.event_date >= now]
        past = [r for r in rows if r.event_date and r.event_date < now]
        if upcoming:
            groups.append(("Coming up", upcoming))
        if past:
            groups.append(("Past events", sorted(past, key=lambda r: r.event_date, reverse=True)))
    else:
        seen = {}
        for row in rows:
            seen.setdefault(row.section or cfg["default_section"], []).append(row)
        groups = list(seen.items())

    body = []
    for section, items in groups:
        body.append(f'<h2>{_esc(section)}</h2><ul class="listing">')
        body.extend(_item_html(r, is_event=is_event_page) for r in items)
        body.append("</ul>")
    if not groups:
        body.append('<p class="muted">Nothing listed yet — check back soon.</p>')

    other = "events" if page_key == "resources" else "resources"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
  <title>{cfg['title']}</title>
  <meta name="description" content="{cfg['description']}" />
  <link rel="canonical" href="{SITE}/{page_key}" />
  <meta name="robots" content="index, follow" />
  <meta name="theme-color" content="#1a56db" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="CreditVoiceai" />
  <meta property="og:title" content="{cfg['title']}" />
  <meta property="og:description" content="{cfg['description']}" />
  <meta property="og:url" content="{SITE}/{page_key}" />
  <link rel="icon" type="image/png" href="/app/favicon.png" />
  {_event_jsonld(rows) if is_event_page else ""}
  <style>
    :root {{ --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --brand:#1a56db; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
            color:var(--ink); background:#fff; line-height:1.55; }}
    .wrap {{ max-width:780px; margin:0 auto; padding:0 20px; }}
    header {{ border-bottom:1px solid var(--line); padding:18px 0; }}
    header a {{ color:var(--brand); text-decoration:none; font-weight:700; }}
    h1 {{ font-size:30px; margin:28px 0 6px; }}
    h2 {{ font-size:19px; margin:30px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
    h3 {{ font-size:16px; margin:0 0 2px; }}
    h3 a {{ color:var(--brand); }}
    p {{ margin:4px 0 0; }}
    .muted, .meta {{ color:var(--muted); font-size:14px; }}
    ul.listing {{ list-style:none; padding:0; margin:0; }}
    ul.listing li {{ padding:14px 0; border-bottom:1px solid var(--line); }}
    footer {{ border-top:1px solid var(--line); margin-top:36px; padding:22px 0 40px;
              color:var(--muted); font-size:14px; }}
    footer a {{ color:var(--muted); margin-right:16px; }}
  </style>
</head>
<body>
  <header><div class="wrap"><a href="/">CreditVoiceai</a></div></header>
  <div class="wrap">
    <h1>{cfg['heading']}</h1>
    <p class="muted">{cfg['intro']}</p>
    {''.join(body)}
    <footer>
      <a href="/">Home</a>
      <a href="/{other}">{other.title()}</a>
      <a href="/app">Open the app</a>
      <a href="/app/terms">Terms</a>
      <a href="/app/privacy">Privacy</a>
      <div style="margin-top:8px;">© CreditVoiceai</div>
    </footer>
  </div>
</body>
</html>"""


def register_public_pages(app):

    def _rows(db, page_key):
        return (
            db.query(PublicListing)
            .filter(PublicListing.page == page_key, PublicListing.is_active == True)  # noqa: E712
            .order_by(PublicListing.sort_order.asc(), PublicListing.created_at.asc())
            .all()
        )

    @app.get("/resources", response_class=HTMLResponse)
    def resources_page():
        db = SessionLocal()
        try:
            return _page_html("resources", _rows(db, "resources"))
        finally:
            db.close()

    @app.get("/events", response_class=HTMLResponse)
    def events_page():
        db = SessionLocal()
        try:
            return _page_html("events", _rows(db, "events"))
        finally:
            db.close()

    # ── Admin: edit what appears on those pages ───────────────────────────
    def _require_admin(db, session):
        from admin import is_app_admin
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only")
        if not _admin_rate_check(user.phone):
            raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
        return user

    def _apply(row, payload):
        from datetime import datetime as _dt
        if payload.link_rel not in _REL:
            raise HTTPException(status_code=400, detail=f"link_rel must be one of {sorted(_REL)}")
        if not payload.title.strip():
            raise HTTPException(status_code=400, detail="A title is required.")
        page = (payload.page or "resources").strip().lower()
        if page not in PAGES:
            raise HTTPException(status_code=400, detail=f"page must be one of {sorted(PAGES)}")
        url = (payload.url or "").strip()
        if url and not url.startswith(("http://", "https://", "/")):
            raise HTTPException(status_code=400, detail="A link must start with http://, https:// or /")
        row.page = page
        row.section = (payload.section or "").strip() or None
        row.title = payload.title.strip()
        row.url = url or None
        row.blurb = (payload.blurb or "").strip() or None
        row.link_rel = payload.link_rel
        row.logo_url = (payload.logo_url or "").strip() or None
        row.event_venue = (payload.event_venue or "").strip() or None
        row.sort_order = payload.sort_order
        row.is_active = bool(payload.is_active)
        if payload.event_date:
            try:
                row.event_date = _dt.strptime(payload.event_date[:10], "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Event date must be YYYY-MM-DD.")
        else:
            row.event_date = None
        row.updated_at = utcnow()
        return row

    @app.get("/app/api/admin/public-listings")
    def admin_list_listings(session: dict = Depends(require_web_auth), page: str = ""):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            q = db.query(PublicListing)
            if page:
                q = q.filter(PublicListing.page == page)
            rows = q.order_by(PublicListing.page.asc(), PublicListing.sort_order.asc()).all()
            return {"listings": [_listing_dict(r) for r in rows],
                    "pages": sorted(PAGES), "link_rels": sorted(_REL)}
        finally:
            db.close()

    @app.post("/app/api/admin/public-listings")
    def admin_create_listing(payload: ListingRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            row = PublicListing()
            _apply(row, payload)
            row.updated_by = user.phone
            db.add(row)
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE",
                            resource=f"public_listing:create:{row.page}:{row.title}"))
            db.commit()
            db.refresh(row)
            return _listing_dict(row)
        finally:
            db.close()

    @app.put("/app/api/admin/public-listings/{listing_id}")
    def admin_update_listing(listing_id: str, payload: ListingRequest,
                             session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            row = db.query(PublicListing).filter(PublicListing.id == listing_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Listing not found.")
            _apply(row, payload)
            row.updated_by = user.phone
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE",
                            resource=f"public_listing:update:{row.id}"))
            db.commit()
            db.refresh(row)
            return _listing_dict(row)
        finally:
            db.close()

    @app.delete("/app/api/admin/public-listings/{listing_id}")
    def admin_delete_listing(listing_id: str, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            row = db.query(PublicListing).filter(PublicListing.id == listing_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Listing not found.")
            db.delete(row)
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE",
                            resource=f"public_listing:delete:{listing_id}"))
            db.commit()
            return {"deleted": True}
        finally:
            db.close()
