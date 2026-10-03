"""
Switches for things that are built but not yet allowed to run.

WhatsApp is the one that matters today: tiTi can hold a conversation, send
reminders and deliver login codes on WhatsApp, but Meta has to approve the
number before any of that reaches a real person. Until then the site says
"coming soon" rather than promising it, and nothing offers a delivery channel
that cannot deliver.

It is one switch so that the day approval lands it is a toggle in the admin
screen, not a deploy: set it from Admin → Site, or pin it with the WHATSAPP_LIVE
env var when you want it decided outside the database.
"""
import logging
import os
import time

_log = logging.getLogger(__name__)

WHATSAPP_LIVE_KEY = "whatsapp_live"

_TRUE = {"1", "true", "yes", "on", "live"}
_FALSE = {"0", "false", "no", "off", ""}

# Read on nearly every public request, so the database answer is held briefly.
_cache = {"at": 0.0, "value": None}
_CACHE_SECONDS = 60


def _from_env():
    raw = os.getenv("WHATSAPP_LIVE", "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE and raw != "":
        return False
    return None


def whatsapp_live(db=None):
    """Is WhatsApp approved and working? False until someone says otherwise.

    The default is off on purpose: an unapproved number fails silently, and a
    promise that fails silently is worse than one not made.
    """
    pinned = _from_env()
    if pinned is not None:
        return pinned

    now = time.time()
    if _cache["value"] is not None and now - _cache["at"] < _CACHE_SECONDS:
        return _cache["value"]

    value = False
    own_session = False
    try:
        from models import SiteSetting
        if db is None:
            from database import SessionLocal
            db = SessionLocal()
            own_session = True
        row = db.query(SiteSetting).filter(SiteSetting.key == WHATSAPP_LIVE_KEY).first()
        value = bool(row and str(row.value or "").strip().lower() in _TRUE)
    except Exception:
        _log.exception("could not read the whatsapp_live setting; treating it as off")
        value = False
    finally:
        if own_session and db is not None:
            db.close()

    _cache.update(at=now, value=value)
    return value


def clear_cache():
    """Called when an admin changes the setting, and by tests."""
    _cache.update(at=0.0, value=None)
