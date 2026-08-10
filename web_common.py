"""
Shared helpers for the web API route modules.

web_routes.py grew to ~5k lines with every endpoint in one function. We are
splitting it into per-domain route modules (web_auth_routes, web_pos_routes, …),
and this module holds the pieces they all share — rate limiters first, with the
session/scope helpers to follow — so the domain modules import from here instead
of from the monolith (which would be a circular import).
"""
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException

from database import SessionLocal
from models import User
from subscriptions import get_business_subscription


# ── Demo endpoint rate limiter ────────────────────────────────────────────────
_demo_lock = threading.Lock()
_demo_hits: dict = defaultdict(list)
_DEMO_LIMIT = 20   # requests per IP
_DEMO_WINDOW = 60  # per 60 seconds


def _demo_rate_check(ip: str) -> bool:
    now = time.time()
    cutoff = now - _DEMO_WINDOW
    with _demo_lock:
        hits = [t for t in _demo_hits[ip] if t > cutoff]
        if len(hits) >= _DEMO_LIMIT:
            _demo_hits[ip] = hits
            return False
        hits.append(now)
        _demo_hits[ip] = hits
        return True


# ── AI endpoint rate limiter (voice transcription + chat) ─────────────────────
# 30 AI calls per user per hour to cap OpenAI spend
_ai_lock = threading.Lock()
_ai_hits: dict = defaultdict(list)
_AI_LIMIT  = 30
_AI_WINDOW = 3600


def _ai_rate_check(user_id: str) -> bool:
    now = time.time()
    cutoff = now - _AI_WINDOW
    with _ai_lock:
        hits = [t for t in _ai_hits[user_id] if t > cutoff]
        if len(hits) >= _AI_LIMIT:
            _ai_hits[user_id] = hits
            return False
        hits.append(now)
        _ai_hits[user_id] = hits
        return True


_admin_lock = threading.Lock()
_admin_hits: dict = defaultdict(list)
_ADMIN_LIMIT  = 120   # requests per minute per admin
_ADMIN_WINDOW = 60

_export_lock = threading.Lock()
_export_hits: dict = defaultdict(list)
_EXPORT_LIMIT  = 3    # CSV exports per hour per admin
_EXPORT_WINDOW = 3600

_redeem_lock = threading.Lock()
_redeem_hits: dict = defaultdict(list)
_REDEEM_LIMIT  = 10   # token-code attempts per hour per user
_REDEEM_WINDOW = 3600


def _admin_rate_check(phone: str) -> bool:
    now = time.time()
    cutoff = now - _ADMIN_WINDOW
    with _admin_lock:
        hits = [t for t in _admin_hits[phone] if t > cutoff]
        if len(hits) >= _ADMIN_LIMIT:
            _admin_hits[phone] = hits
            return False
        hits.append(now)
        _admin_hits[phone] = hits
        return True


def _export_rate_check(phone: str) -> bool:
    now = time.time()
    cutoff = now - _EXPORT_WINDOW
    with _export_lock:
        hits = [t for t in _export_hits[phone] if t > cutoff]
        if len(hits) >= _EXPORT_LIMIT:
            _export_hits[phone] = hits
            return False
        hits.append(now)
        _export_hits[phone] = hits
        return True


def _redeem_rate_check(user_id: str) -> bool:
    now = time.time()
    cutoff = now - _REDEEM_WINDOW
    with _redeem_lock:
        hits = [t for t in _redeem_hits[user_id] if t > cutoff]
        if len(hits) >= _REDEEM_LIMIT:
            _redeem_hits[user_id] = hits
            return False
        hits.append(now)
        _redeem_hits[user_id] = hits
        return True


# ── Request-scoped DB + formatting helpers ────────────────────────────────────

def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _money(value):
    return int(value or 0)


def _iso(value):
    return value.isoformat() if value else None


def _safe_filename(name: str) -> str:
    """Strip characters that could break a Content-Disposition filename= field."""
    import re
    return re.sub(r'["\\\r\n;]', "_", name)


def _owner_filter(query, model, owner_phone):
    if owner_phone:
        return query.filter(model.owner_phone == owner_phone)
    return query


# ── Inventory limit helpers ───────────────────────────────────────────────────

def _active_inventory_count(db, owner_phone: str) -> int:
    """Count inventory items that are 'active' — have a selling price set."""
    from models import InventoryItem
    return db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.selling_price != None,
    ).count()


def _check_inventory_limit(db, owner_phone: str, subscription) -> "str | None":
    """Return an error message if the owner is at their active inventory limit, else None."""
    from plans import plan_limit, normalize_plan
    # subscription is the dict returned by get_business_subscription — read its
    # "plan" key. (getattr on a dict never finds "plan", so it silently pinned
    # every upgraded user to BASIC and capped them at 5 active products.)
    plan = normalize_plan((subscription or {}).get("plan", "BASIC"))
    limit = plan_limit(plan, "active_inventory_items")
    if limit is None:
        return None
    count = _active_inventory_count(db, owner_phone)
    if count >= limit:
        return (
            f"You have reached the Basic plan limit of {limit} active products. "
            f"Draft items (no price set) are unlimited. "
            f"Upgrade to Go to add unlimited active products."
        )
    return None


# ── Session / scope helpers (multi-tenant + branch isolation) ─────────────────

def _session_user(db, session: dict):
    """The logged-in User, fetched at most once per request (cached on the
    SQLAlchemy session's request-scoped `.info` dict)."""
    cache = db.info.setdefault("_req", {})
    if "user" not in cache:
        cache["user"] = db.query(User).filter(User.id == session["user_id"]).first()
    return cache["user"]


def _session_owner_phone(db, session: dict) -> str:
    """Resolve the business owner phone from a web session.
    Staff members' sessions resolve to their owner's phone automatically.
    Raises 401 if the user is not found. Cached per request.
    """
    cache = db.info.setdefault("_req", {})
    if "owner_phone" in cache:
        return cache["owner_phone"]
    user = _session_user(db, session)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.parent_id:
        owner = db.query(User).filter(User.id == user.parent_id).first()
        phone = owner.phone if owner else user.phone
    else:
        phone = user.phone
    cache["owner_phone"] = phone
    return phone


def _session_branch_scope(db, session: dict):
    """(branch_id, limited) the current user's data access is confined to.
    Owner/admin → (None, False) sees all branches; a branch staff → (their
    branch_id, True). See branch_scope_for_user."""
    from webhook_context import branch_scope_for_user
    return branch_scope_for_user(_session_user(db, session))


def _scoped_read(db, session: dict, requested_branch_id=None):
    """Effective (branch_id, recorded_by_id) for a read, enforcing branch
    isolation:
      - owner/full-access: (requested_branch_id, None) — sees all, may filter
        by a branch they picked in the UI
      - branch staff: (their branch_id, None) — locked to their branch
      - staff with no branch: (None, their id) — locked to their own records
    Pass the pair straight to the report/query helpers."""
    from webhook_context import branch_scope_for_user
    user = _session_user(db, session)
    branch_id, limited = branch_scope_for_user(user)
    if not limited:
        return requested_branch_id, None
    if branch_id is not None:
        return branch_id, None
    return None, user.id


def _require_tx_in_scope(db, session: dict, tx):
    """A limited staff may only act on a transaction within their scope — their
    branch (branch admin) or their own records (regular staff). Owner / full
    access is unrestricted. 404 (not 403) so it doesn't reveal the tx exists."""
    eff_branch, rec = _scoped_read(db, session)
    if eff_branch is not None and tx.branch_id != eff_branch:
        raise HTTPException(status_code=404, detail="Not found.")
    if rec is not None and tx.recorded_by_id != rec:
        raise HTTPException(status_code=404, detail="Not found.")


def _require_stock_manager(db, session: dict):
    """Only the owner or a branch admin (a staff granted see-all-branch access)
    may manage stock. Regular staff record sales but cannot add / edit / adjust
    inventory. Returns the acting user."""
    user = _session_user(db, session)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.parent_id is None or user.can_view_all_transactions:
        return user
    raise HTTPException(status_code=403, detail="Only the owner or a branch admin can manage stock.")


def _require_can_record(db, session: dict, count_sale: bool = True):
    """Guard before recording. Blocks:
      - a staff sub-account when the business is on Basic (staff not included);
      - a new SALE once the business hits its monthly transaction cap
        (Basic = 100). Pass count_sale=False for debt payments so collecting
        money owed is never blocked.
    Owners are allowed (subject to the monthly cap). Returns the acting user."""
    from subscriptions import (
        staff_recording_allowed, get_business_subscription, check_monthly_transaction_limit,
    )
    user = _session_user(db, session)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not staff_recording_allowed(db, user):
        raise HTTPException(
            status_code=403,
            detail="Staff can only record on the Pro or Premium plan. "
                   "Ask the business owner to renew the subscription.",
        )
    if count_sale:
        owner_phone = _session_owner_phone(db, session)
        sub = get_business_subscription(db, user)
        ok, msg = check_monthly_transaction_limit(db, owner_phone, sub)
        if not ok:
            raise HTTPException(status_code=403, detail=msg)
    return user


def _session_subscription(db, session: dict):
    """The business subscription, resolved at most once per request."""
    cache = db.info.setdefault("_req", {})
    if "sub" not in cache:
        user = _session_user(db, session)
        cache["sub"] = get_business_subscription(db, user) if user else None
    return cache["sub"]


def _add_notification(db, owner_phone, event_type, title, body):
    """Insert an in-app notification for the business owner (shown in the bell)
    and fire a Web Push to their subscribed devices. The caller is responsible
    for committing the row; the push is fire-and-forget on a background thread."""
    from models import AppNotification
    db.add(AppNotification(
        owner_phone=owner_phone, event_type=event_type, title=title, body=body,
        is_read=0, created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    try:
        from web_push import send_web_push
        send_web_push(owner_phone, title, body)
    except Exception:
        pass


def _send_web_receipt(db, owner_phone, tx_id):
    """Best-effort: send the customer their receipt on WhatsApp after a web sale
    or payment (mirrors the WhatsApp flow). No-op if the customer has no phone."""
    if not tx_id:
        return
    try:
        from web_pos import get_pos_receipt, format_receipt_text
        from whatsapp_client import send_whatsapp_message
        owner_user = db.query(User).filter(User.phone == owner_phone).first()
        receipt = get_pos_receipt(db, tx_id, user=owner_user)
        if not receipt:
            return
        phone = (receipt.get("customer") or {}).get("phone")
        if not phone:
            return
        send_whatsapp_message(phone, format_receipt_text(receipt))
    except Exception:
        import traceback; traceback.print_exc()
