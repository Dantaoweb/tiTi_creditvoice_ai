"""
Settings people choose for themselves.

- Display (each person's own, staff too): text size, theme, list style.
- Business (owner and authorised staff, for everyone in the business): how
  stock is grouped, where categories come from, defaults for new products,
  selling below zero, part delivery at the till, the daily summary.

Every default is how the app behaved before settings existed, so nothing
changes for anyone until they choose. Stored as JSON on the user row
(display_prefs_json on each user, business_settings_json on the owner).
"""
import json
import re
from datetime import datetime, timedelta, timezone

from models import User

DISPLAY_DEFAULTS = {
    "text_size": "normal",        # small | normal | large | xlarge
    "theme": "light",             # light | dark | system — light unless the person chooses
    "density": "comfortable",     # compact | comfortable
    "scan_mode": "keep",          # phone camera: keep (one after another) | tap (one, then close) | photo (phone's Camera app)
}
DISPLAY_CHOICES = {
    "text_size": ("small", "normal", "large", "xlarge"),
    "theme": ("light", "dark", "system"),
    "density": ("compact", "comfortable"),
    "scan_mode": ("keep", "tap", "photo"),
}

BUSINESS_DEFAULTS = {
    "group_by_category": False,
    "group_on_pos": True,                 # when grouping: Inventory and POS (False = Inventory only)
    "category_source": "suggest",         # suggest | manual
    "default_low_stock": None,            # number for new products, or None
    "allow_negative_stock": True,
    "show_part_delivery": True,
    "daily_summary": False,
    "daily_summary_time": "20:00",        # Lagos time, HH:MM
    "category_order": [],
}
# Kept on the same JSON but not a user choice
_INTERNAL = ("daily_summary_last_sent",)

LAGOS = timezone(timedelta(hours=1))      # West Africa Time, no daylight saving


def _load(raw):
    try:
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def get_display(user):
    data = _load(getattr(user, "display_prefs_json", None))
    out = {k: data.get(k, v) if data.get(k) in DISPLAY_CHOICES[k] else v
           for k, v in DISPLAY_DEFAULTS.items()}
    # The first version saved "follow my phone" alongside any other change, as
    # its default — which turned the app dark for people who never picked it.
    # Only a theme the person actually chose counts.
    if not data.get("theme_chosen"):
        out["theme"] = DISPLAY_DEFAULTS["theme"]
    return out


def set_display(user, changes):
    current = get_display(user)
    chosen = bool(_load(getattr(user, "display_prefs_json", None)).get("theme_chosen"))
    for k, v in (changes or {}).items():
        if k not in DISPLAY_CHOICES:
            continue
        if v not in DISPLAY_CHOICES[k]:
            raise ValueError(f"'{v}' is not a choice for {k.replace('_', ' ')}.")
        current[k] = v
        if k == "theme":
            chosen = True
    user.display_prefs_json = json.dumps({**current, "theme_chosen": chosen})
    return current


def _owner(db, owner_phone):
    return db.query(User).filter(User.phone == owner_phone).first()


def _raw_business(owner):
    return _load(getattr(owner, "business_settings_json", None)) if owner else {}


def get_business_settings(db, owner_phone):
    data = _raw_business(_owner(db, owner_phone))
    out = dict(BUSINESS_DEFAULTS)
    for k in BUSINESS_DEFAULTS:
        if k in data:
            out[k] = data[k]
    return out


def business_setting(db, owner_phone, key):
    return get_business_settings(db, owner_phone).get(key, BUSINESS_DEFAULTS.get(key))


def _clean_business(k, v):
    if k in ("group_by_category", "group_on_pos", "allow_negative_stock",
             "show_part_delivery", "daily_summary"):
        return bool(v)
    if k == "category_source":
        if v not in ("suggest", "manual"):
            raise ValueError("Categories come from tiTi's suggestion or your own typing.")
        return v
    if k == "default_low_stock":
        if v in (None, "", 0, "0"):
            return None
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            raise ValueError("The low-stock alert must be a number.")
        if n < 0:
            raise ValueError("The low-stock alert can't be negative.")
        return n
    if k == "daily_summary_time":
        if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("Pick a time like 20:00.")
        return v
    if k == "category_order":
        if not isinstance(v, list):
            raise ValueError("Invalid category order.")
        return [str(x).strip().lower()[:60] for x in v if str(x).strip()][:300]
    raise ValueError("Unknown setting.")


def set_business_settings(db, owner_phone, changes):
    owner = _owner(db, owner_phone)
    if not owner:
        raise ValueError("Business not found.")
    data = _raw_business(owner)
    for k, v in (changes or {}).items():
        if k not in BUSINESS_DEFAULTS:
            continue
        data[k] = _clean_business(k, v)
    owner.business_settings_json = json.dumps(data)
    return get_business_settings(db, owner_phone)


# ── Categories ────────────────────────────────────────────────────────────────

SERVICE_CATEGORY = "service"      # InventoryItem.category "service" marks a service


def clean_category(name):
    name = re.sub(r"\s+", " ", (name or "").strip().lower())[:60]
    if name == SERVICE_CATEGORY:
        raise ValueError("'Service' is kept for services — pick another name.")
    return name or None


def suggest_category(db, owner_phone, product_name):
    """tiTi's category for a product name, from the business type's catalogue."""
    from business_templates import get_product_category_suggestion, template_key_for_user
    owner = _owner(db, owner_phone)
    if not owner or not product_name:
        return None
    try:
        s = get_product_category_suggestion(template_key_for_user(owner), product_name,
                                            getattr(owner, "business_type", None))
    except Exception:
        return None
    s = (s or "").strip().lower()
    return s if s and s != SERVICE_CATEGORY else None


def apply_new_item_defaults(db, owner_phone, item):
    """Settings that shape a brand-new product: its low-stock alert and (when
    tiTi suggests categories) its category. Never overrides what was given."""
    s = get_business_settings(db, owner_phone)
    is_service = item.quantity is None or item.category == SERVICE_CATEGORY
    if not is_service and item.low_stock_alert is None and s["default_low_stock"] is not None:
        item.low_stock_alert = s["default_low_stock"]
    if not is_service and not item.category and s["category_source"] == "suggest":
        item.category = suggest_category(db, owner_phone, item.name)


# ── Daily summary on WhatsApp ─────────────────────────────────────────────────

def due_daily_summaries(db, now=None):
    """Owners whose daily summary time has come today (Lagos) and who haven't
    had today's yet, as (owner, today_str)."""
    now = (now or datetime.now(timezone.utc)).astimezone(LAGOS)
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    out = []
    for owner in db.query(User).filter(User.parent_id.is_(None),
                                       User.business_settings_json.isnot(None)).all():
        data = _raw_business(owner)
        if not data.get("daily_summary"):
            continue
        if data.get("daily_summary_last_sent") == today:
            continue
        if hhmm >= data.get("daily_summary_time", "20:00"):
            out.append((owner, today))
    return out


def send_daily_summaries(db, send_message=None, now=None):
    """Send today's summary to each owner who asked for it. Returns how many."""
    from reports import build_dashboard_summary_message, get_dashboard_summary
    if send_message is None:
        # Until Meta approves the number a send never arrives — wait, don't
        # mark today as done.
        from feature_flags import whatsapp_live
        if not whatsapp_live(db):
            return 0
        from whatsapp_client import send_whatsapp_message as send_message
    sent = 0
    for owner, today in due_daily_summaries(db, now):
        summary = get_dashboard_summary(db, owner.phone, "TODAY", None)
        text = ("🌙 *Your daily summary*\n\n" + build_dashboard_summary_message(summary, "TODAY", owner)
                + "\n\n_Change or stop this in Settings._")
        data = _raw_business(owner)
        data["daily_summary_last_sent"] = today
        owner.business_settings_json = json.dumps(data)
        db.commit()                      # mark first — never send twice on a retry
        try:
            send_message(owner.phone, text)
            sent += 1
        except Exception as e:
            print(f"[daily-summary] send failed for {owner.phone}: {e!r}", flush=True)
    return sent


async def run_daily_summary_loop():
    import asyncio
    from database import SessionLocal
    while True:
        await asyncio.sleep(600)
        db = SessionLocal()
        try:
            send_daily_summaries(db)
        except Exception as e:
            print(f"[daily-summary] {e!r}", flush=True)
            db.rollback()
        finally:
            db.close()
