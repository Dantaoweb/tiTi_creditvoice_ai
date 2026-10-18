"""
How much AI one person can use from the web app — counting only messages that
actually needed the AI (tiTi asking the AI to understand something, a voice
note), never ordinary recording ("Ade bought rice 5000", "yes", menu numbers),
which the local parser reads for free.

The web chat and voice capture set the person for the request (`for_user`);
the AI call sites ask `allow()` before calling. WhatsApp sets nobody, so
registered owners and staff there are never limited — busy market hours must
never be blocked.

When the budget is used up the AI is simply skipped for that message (tiTi
answers from what it can read itself) and the reply says how many minutes are
left, honestly — not "come back in an hour".
"""
import math
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar

AI_LIMIT = 100          # AI-assisted messages per hour, per person
AI_WINDOW = 3600

MESSAGE_LIMIT = 600     # any messages per hour — only an abuse guard
MESSAGE_WINDOW = 3600

_current = ContextVar("ai_budget_user", default=None)
_exhausted = ContextVar("ai_budget_exhausted", default=False)
_lock = threading.Lock()
_ai_hits = defaultdict(list)
_msg_hits = defaultdict(list)


def _trim(hits, window, now):
    cutoff = now - window
    return [t for t in hits if t > cutoff]


def _wait_minutes(hits, window, now):
    if not hits:
        return 0
    return max(1, math.ceil((hits[0] + window - now) / 60))


@contextmanager
def for_user(user_id):
    """Count AI use against this person for the length of one request."""
    token = _current.set(str(user_id))
    flag = _exhausted.set(False)
    try:
        yield
    finally:
        _current.reset(token)
        _exhausted.reset(flag)


def allow():
    """Called right before an AI call. True = go ahead (and it's counted)."""
    user = _current.get()
    if user is None:
        return True                         # WhatsApp, scheduler… never limited here
    now = time.time()
    with _lock:
        hits = _trim(_ai_hits[user], AI_WINDOW, now)
        if len(hits) >= AI_LIMIT:
            _ai_hits[user] = hits
            _exhausted.set(True)
            return False
        hits.append(now)
        _ai_hits[user] = hits
        return True


def consume_for(user_id):
    """Count one AI use for this person directly (a voice note always needs
    the AI). Returns (allowed, minutes to wait)."""
    token = _current.set(str(user_id))
    try:
        if allow():
            return True, 0
        return False, ai_minutes_left(user_id)
    finally:
        _current.reset(token)


def was_exhausted():
    """Whether this request wanted the AI but the budget was used up."""
    return _exhausted.get()


def ai_minutes_left(user_id):
    now = time.time()
    with _lock:
        return _wait_minutes(_trim(_ai_hits[str(user_id)], AI_WINDOW, now), AI_WINDOW, now)


def message_allowed(user_id):
    """The abuse guard on any message. Returns (allowed, minutes to wait)."""
    now = time.time()
    key = str(user_id)
    with _lock:
        hits = _trim(_msg_hits[key], MESSAGE_WINDOW, now)
        if len(hits) >= MESSAGE_LIMIT:
            _msg_hits[key] = hits
            return False, _wait_minutes(hits, MESSAGE_WINDOW, now)
        hits.append(now)
        _msg_hits[key] = hits
        return True, 0


def exhausted_note(user_id):
    mins = ai_minutes_left(user_id)
    return (f"\n\n_You've sent a lot of messages that needed extra thinking, so I answered this one "
            f"from what I could read myself. Full help is back in {mins} minute{'s' if mins != 1 else ''}. "
            f"Normal recording (like \"Ade bought rice 5000\") works as usual._")


def _reset_for_tests():
    with _lock:
        _ai_hits.clear()
        _msg_hits.clear()
