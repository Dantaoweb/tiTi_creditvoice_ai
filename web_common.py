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
