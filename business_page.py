"""
Business page — a public page of the business's own, at creditvoiceai.com/b/<name>.

Bought outside the app (a one-time payment). An admin switches it on for the
business and gives it its address; the owner then turns it on in the app and
chooses what shows: a few lines about the business, opening hours, and the
products to show (with or without prices).

The page is plain HTML rendered on the server, so Google can find it and it
loads fast on any phone. Visitors can call, chat on WhatsApp, or "Ask for a
quotation"; that lands in the app as an enquiry the owner turns into a
quotation with one tap.

Never on the page: stock quantities, cost prices, customers, or anything else
from inside the app.
"""
import html
import json
import re

from models import Branch, InventoryItem, PageEnquiry, User, utcnow

SITE = "https://creditvoiceai.com"
MAX_ITEMS = 200
# Addresses that must never be a business's page
_RESERVED = {"app", "api", "admin", "b", "book", "pay", "login", "signup", "register", "help", "support",
             "resources", "events", "creditvoice", "creditvoiceai", "titi", "www", "static", "assets"}


class PageError(ValueError):
    pass


# ── The page's address ──────────────────────────────────────────────────────

def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:50].strip("-")


def clean_slug(db, slug, owner_id):
    """A free, valid address for this business, or a PageError saying why not."""
    s = slugify(slug)
    if len(s) < 3:
        raise PageError("The page address needs at least 3 letters or numbers.")
    if s in _RESERVED:
        raise PageError(f"'{s}' can't be used. Pick another address.")
    taken = db.query(User.id).filter(User.page_slug == s, User.id != owner_id).first()
    if taken:
        raise PageError(f"creditvoiceai.com/b/{s} is already taken. Pick another address.")
    return s


def suggest_slug(db, owner):
    from business_templates import business_display_name
    base = slugify(business_display_name(owner)) or "shop"
    if len(base) < 3:
        base = f"{base}-shop".strip("-")
    s, n = base, 2
    while s in _RESERVED or db.query(User.id).filter(User.page_slug == s, User.id != owner.id).first():
        s, n = f"{base}-{n}", n + 1
    return s


def page_url(owner):
    return f"{SITE}/b/{owner.page_slug}" if owner and owner.page_slug else None


def enable(db, owner, enabled, slug=None):
    """Admin: switch the page on (after the one-time payment) or off."""
    if enabled:
        owner.page_slug = clean_slug(db, slug, owner.id) if slug else (owner.page_slug or suggest_slug(db, owner))
    owner.page_enabled = bool(enabled)
    db.commit()
    return owner


# ── What the page shows ─────────────────────────────────────────────────────

def _settings(db, owner):
    from app_settings import get_business_settings
    return get_business_settings(db, owner.phone)


def is_live(db, owner):
    return bool(owner and owner.page_enabled and owner.page_slug and _settings(db, owner).get("page_on")
                and not getattr(owner, "deleted_at", None))


def page_items(db, owner, cfg=None):
    cfg = cfg or _settings(db, owner)
    ids = [int(i) for i in (cfg.get("page_items") or [])][:MAX_ITEMS]
    if not ids:
        return []
    rows = (db.query(InventoryItem)
            .filter(InventoryItem.owner_phone == owner.phone, InventoryItem.id.in_(ids),
                    InventoryItem.is_available.isnot(False))
            .order_by(InventoryItem.category, InventoryItem.name).all())
    out = []
    for it in rows:
        stocked = it.quantity is not None and (it.category or "") != "service"
        out.append({
            "id": it.id,
            "name": (it.name or "").strip().title(),
            "unit": it.unit,
            "category": (it.category or "").strip().title() or "Products",
            "price": int(it.selling_price) if (cfg.get("page_show_prices") and it.selling_price) else None,
            "detail": " · ".join(x for x in (it.size, it.color) if x) or None,
            "about": (it.description or "").strip()[:200] or None,
            "image": it.media_url if (it.media_url or "").startswith(("https://", "data:image/")) else None,
            # Never the count — only whether it can be had now
            "in_stock": (not stocked) or (it.quantity or 0) > 0,
        })
    return out


def public_data(db, owner):
    from invoices import _business_header
    cfg = _settings(db, owner)
    head = _business_header(db, owner.phone, None)
    branches = [{"name": b.name, "address": b.address, "phone": (b.phone or "").strip() or None}
                for b in db.query(Branch).filter(Branch.owner_phone == owner.phone).order_by(Branch.id).all()
                if (b.address or "").strip()]
    return {
        "slug": owner.page_slug,
        "url": page_url(owner),
        "name": head.get("biz_name") or "Our business",
        "logo": head.get("biz_logo") if (head.get("biz_logo") or "").startswith("data:image/") else None,
        "phone": head.get("biz_phone"),
        "address": head.get("biz_address"),
        "about": cfg.get("page_about") or "",
        "hours": cfg.get("page_hours") or "",
        "show_prices": bool(cfg.get("page_show_prices")),
        "branches": branches,
        "items": page_items(db, owner, cfg),
    }


def _wa_number(phone):
    digits = re.sub(r"\D", "", (phone or "").split("/")[0])
    if digits.startswith("0") and len(digits) == 11:
        digits = "234" + digits[1:]
    return digits if len(digits) >= 10 else None


# ── Enquiries ("Ask for a quotation") ───────────────────────────────────────

def add_enquiry(db, owner, name, phone, message, wanted):
    name = " ".join((name or "").split())[:100]
    phone = "".join(c for c in (phone or "") if c.isdigit() or c == "+")[:20]
    if len(name) < 2:
        raise PageError("Enter your name.")
    if len(phone.lstrip("+")) < 10:
        raise PageError("Enter a phone number the business can call.")
    allowed = {i["id"]: i for i in page_items(db, owner)}
    items = []
    for item_id, qty in (wanted or {}).items():
        try:
            item_id, qty = int(item_id), float(qty or 0)
        except (TypeError, ValueError):
            continue
        if item_id in allowed and 0 < qty <= 100000:
            items.append({"id": item_id, "name": allowed[item_id]["name"], "qty": qty})
    message = (message or "").strip()[:1000]
    if not items and not message:
        raise PageError("Say what you need — pick a product or write a message.")
    e = PageEnquiry(owner_phone=owner.phone, name=name, phone=phone, message=message or None,
                    items_json=json.dumps(items[:50]), status="new", created_at=utcnow())
    db.add(e)
    db.commit()
    from web_common import _add_notification
    what = ", ".join(f"{_num(i['qty'])} {i['name']}" for i in items[:3]) or (message[:60] if message else "")
    _add_notification(db, owner.phone, "page_enquiry", f"🛒 Quotation request from {name}",
                      f"{phone}{' · ' + what if what else ''}. From your business page.", link="/business-page")
    db.commit()
    return e


def _num(q):
    return int(q) if float(q).is_integer() else q


def enquiry_row(e):
    return {"id": e.id, "name": e.name, "phone": e.phone, "message": e.message,
            "items": json.loads(e.items_json or "[]"), "status": e.status, "invoice_id": e.invoice_id,
            "created_at": e.created_at.isoformat() if e.created_at else None}


def quote_from_enquiry(db, owner, e, user_id):
    """The enquiry becomes a quotation (or an invoice, for a business with
    quotations off), for the person who asked — saved as a customer."""
    if e.status == "quoted" and e.invoice_id:
        raise PageError("A quotation was already made for this request.")
    from business_templates import can_quote
    from invoices import create_invoice
    wanted = json.loads(e.items_json or "[]")
    items = {it.id: it for it in db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner.phone, InventoryItem.id.in_([w["id"] for w in wanted] or [0])).all()}
    lines = []
    for w in wanted:
        it = items.get(w["id"])
        if it:
            lines.append({"inventory_item_id": it.id, "name": it.name, "qty": w["qty"], "unit": it.unit,
                          "unit_price": int(it.selling_price or 0)})
    if not lines:
        lines = [{"name": "As requested", "qty": 1, "unit_price": 0}]
    inv = create_invoice(db, owner.phone, user_id, None, lines, customer_name=e.name, customer_phone=e.phone,
                         note=(f"Request from your business page: {e.message}" if e.message else
                               "Request from your business page")[:500],
                         is_quote=bool(can_quote(owner, db)))
    e.status, e.invoice_id = "quoted", inv.id
    db.commit()
    return inv


# ── The public page ─────────────────────────────────────────────────────────

def _e(s):
    return html.escape(str(s or ""), quote=True)


def _naira(n):
    return f"₦{int(n):,}"


def render_page(data, sent=False, error=None, form=None):
    form = form or {}
    name = _e(data["name"])
    desc = (data["about"] or f"{data['name']}: products, prices and contacts.").replace("\n", " ")[:160]
    wa = _wa_number(data["phone"])
    groups = {}
    for it in data["items"]:
        groups.setdefault(it["category"], []).append(it)

    cards = []
    for cat, items in groups.items():
        rows = []
        for it in items:
            img = f'<img src="{_e(it["image"])}" alt="" loading="lazy">' if it["image"] else ""
            price = f'<span class="price">{_naira(it["price"])}{" / " + _e(it["unit"]) if it["unit"] else ""}</span>' \
                if it["price"] else '<span class="price ask">Ask for price</span>'
            stock = "" if it["in_stock"] else '<span class="out">Ask for availability</span>'
            detail = f'<span class="detail">{_e(it["detail"])}</span>' if it["detail"] else ""
            about = f'<p class="about">{_e(it["about"])}</p>' if it["about"] else ""
            qty = _e(form.get(f"q{it['id']}", ""))
            rows.append(
                f'<li class="item">{img}<div class="info"><h3>{_e(it["name"])}</h3>{detail}{about}'
                f'<div class="row">{price}{stock}</div></div>'
                f'<label class="want">Qty<input type="number" name="q{it["id"]}" min="0" step="any" inputmode="decimal" value="{qty}"></label></li>')
        cards.append(f'<h2>{_e(cat)}</h2><ul class="items">{"".join(rows)}</ul>')
    products = "".join(cards) or '<p class="muted">Call or chat with us for what we have and our prices.</p>'

    contact = []
    if data["phone"]:
        contact.append(f'<a class="btn" href="tel:{_e(re.sub(r"[^0-9+]", "", data["phone"].split("/")[0]))}">Call {_e(data["phone"])}</a>')
    if wa:
        contact.append(f'<a class="btn wa" href="https://wa.me/{wa}" rel="nofollow">Chat on WhatsApp</a>')
    places = []
    if data["address"]:
        places.append(f'<li>{_e(data["address"])}</li>')
    for b in data["branches"]:
        places.append(f'<li><b>{_e(b["name"])}</b> — {_e(b["address"])}{" · " + _e(b["phone"]) if b["phone"] else ""}</li>')
    where = f'<ul class="places">{"".join(places)}</ul>' if places else ""
    hours = f'<p class="hours">Open: {_e(data["hours"])}</p>' if data["hours"] else ""
    logo = f'<img class="logo" src="{_e(data["logo"])}" alt="{name} logo">' if data["logo"] else ""
    about = "".join(f"<p>{_e(p)}</p>" for p in data["about"].split("\n\n") if p.strip())

    if sent:
        notice = '<div class="ok" role="status">Thank you — your request was sent. The business will contact you with a quotation.</div>'
    elif error:
        notice = f'<div class="err" role="alert">{_e(error)}</div>'
    else:
        notice = ""

    jsonld = json.dumps({
        "@context": "https://schema.org", "@type": "Store", "name": data["name"], "url": data["url"],
        **({"telephone": data["phone"]} if data["phone"] else {}),
        **({"address": data["address"]} if data["address"] else {}),
        **({"openingHours": data["hours"]} if data["hours"] else {}),
        **({"description": desc} if data["about"] else {}),
    }, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{name}</title>
  <meta name="description" content="{_e(desc)}">
  <link rel="canonical" href="{_e(data['url'])}">
  <meta name="robots" content="index, follow">
  <meta property="og:type" content="business.business">
  <meta property="og:title" content="{name}">
  <meta property="og:description" content="{_e(desc)}">
  <meta property="og:url" content="{_e(data['url'])}">
  <link rel="icon" type="image/png" href="/app/favicon.png">
  <script type="application/ld+json">{jsonld}</script>
  <style>
    :root {{ --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --brand:#1a56db; --bg:#f8fafc; --card:#fff; --wa:#128c4a; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --ink:#e5e7eb; --muted:#94a3b8; --line:#273244; --brand:#6b9bff; --bg:#0b1220; --card:#111a2c; --wa:#34c46e; }} }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:var(--bg); line-height:1.5; }}
    .wrap {{ max-width:820px; margin:0 auto; padding:0 max(16px, env(safe-area-inset-left)); }}
    header.top {{ background:var(--card); border-bottom:1px solid var(--line); padding:22px 0; }}
    .id {{ display:flex; gap:14px; align-items:center; }}
    .logo {{ width:64px; height:64px; object-fit:contain; border-radius:10px; background:#fff; border:1px solid var(--line); }}
    h1 {{ font-size:26px; margin:0; line-height:1.2; }}
    .hours, .muted {{ color:var(--muted); margin:4px 0 0; font-size:15px; }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }}
    .btn {{ display:inline-block; padding:10px 16px; border-radius:8px; background:var(--brand); color:#fff; text-decoration:none; font-weight:600; font-size:15px; border:0; cursor:pointer; }}
    .btn.wa {{ background:var(--wa); }}
    section {{ margin-top:26px; }}
    h2 {{ font-size:18px; margin:26px 0 10px; }}
    .places {{ padding-left:18px; margin:8px 0 0; }}
    .items {{ list-style:none; padding:0; margin:0; display:grid; gap:10px; }}
    .item {{ display:flex; gap:12px; align-items:flex-start; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; }}
    .item img {{ width:72px; height:72px; object-fit:cover; border-radius:8px; flex:none; }}
    .info {{ flex:1; min-width:0; }}
    .item h3 {{ font-size:16px; margin:0; }}
    .detail, .about {{ color:var(--muted); font-size:14px; margin:2px 0 0; display:block; }}
    .row {{ display:flex; gap:10px; flex-wrap:wrap; align-items:baseline; margin-top:6px; }}
    .price {{ font-weight:700; font-variant-numeric:tabular-nums; }}
    .price.ask, .out {{ font-weight:600; color:var(--muted); font-size:14px; }}
    .want {{ font-size:12px; color:var(--muted); display:flex; flex-direction:column; gap:2px; flex:none; }}
    .want input {{ width:72px; padding:6px; border:1px solid var(--line); border-radius:6px; font-size:15px; background:var(--card); color:var(--ink); }}
    .ask-box {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; display:grid; gap:10px; margin-top:16px; }}
    .ask-box label {{ display:grid; gap:4px; font-size:14px; font-weight:600; }}
    .ask-box input, .ask-box textarea {{ padding:9px; border:1px solid var(--line); border-radius:8px; font:inherit; background:var(--card); color:var(--ink); }}
    .hp {{ position:absolute; left:-5000px; }}
    .ok, .err {{ padding:12px 14px; border-radius:8px; margin-top:16px; font-weight:600; }}
    .ok {{ background:#dcfce7; color:#166534; }} .err {{ background:#fee2e2; color:#991b1b; }}
    footer {{ color:var(--muted); font-size:13px; padding:30px 0 40px; }}
    footer a {{ color:var(--muted); }}
    @media (max-width:480px) {{ .item {{ flex-wrap:wrap; }} .want {{ flex-direction:row; align-items:center; gap:6px; }} }}
  </style>
</head>
<body>
  <header class="top"><div class="wrap">
    <div class="id">{logo}<div><h1>{name}</h1>{hours}</div></div>
    <div class="actions">{"".join(contact)}<a class="btn" href="#ask" style="background:transparent;color:var(--brand);border:1px solid var(--brand)">Ask for a quotation</a></div>
  </div></header>
  <main class="wrap">
    {notice}
    {f'<section>{about}{where}</section>' if (about or where) else ''}
    <form method="post" action="/b/{_e(data['slug'])}#ask">
      <section>{products}</section>
      <section id="ask">
        <h2>Ask for a quotation</h2>
        <p class="muted">Enter quantities above for what you need, add a note, and the business will send you a quotation.</p>
        <div class="ask-box">
          <label>Your name<input name="name" required maxlength="100" value="{_e(form.get('name', ''))}"></label>
          <label>Phone number<input name="phone" required maxlength="20" inputmode="tel" value="{_e(form.get('phone', ''))}"></label>
          <label>What do you need? (optional)<textarea name="message" rows="3" maxlength="1000">{_e(form.get('message', ''))}</textarea></label>
          <label class="hp" aria-hidden="true">Leave empty<input name="website" tabindex="-1" autocomplete="off"></label>
          <button class="btn" type="submit">Send request</button>
        </div>
      </section>
    </form>
    <footer>Page made with <a href="{SITE}/">CreditVoice</a> — sales, stock and debts for your business.</footer>
  </main>
</body>
</html>"""


def not_found_html():
    return """<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found</title><meta name="robots" content="noindex"><style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:60px auto;padding:0 16px;color:#0f172a}a{color:#1a56db}</style></head>
<body><h1>This business page isn't available</h1><p>It may have been switched off. <a href="/">Go to CreditVoice</a></p></body></html>"""
