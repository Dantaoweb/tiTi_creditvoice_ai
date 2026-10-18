"""
Sliding-window rate limiter for the CreditVoice webhook.

Registered owners and staff are never rate-limited — fast mode and
busy market hours must never be blocked.

Only unregistered phones and customer-bot users are throttled.
"""
import threading
import time
from collections import deque


# ── Limits ────────────────────────────────────────────────────────────────────

# Unregistered phone: 5 messages per 10 minutes
UNREGISTERED_LIMIT  = 5
UNREGISTERED_WINDOW = 600   # seconds

# Customer bot user (unregistered, active conversation): 10 per 5 minutes
CUSTOMER_BOT_LIMIT  = 10
CUSTOMER_BOT_WINDOW = 300   # seconds


# ── Limiter ───────────────────────────────────────────────────────────────────

class _SlidingWindowLimiter:
    def __init__(self):
        self._windows: dict[str, deque] = {}
        self._lock = threading.Lock()

    def is_allowed(self, phone: str, limit: int, window_seconds: int) -> bool:
        """
        Return True if the phone is within the rate limit.
        Returns False and does NOT record the attempt if blocked.
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        key = f"{phone}:{window_seconds}"

        with self._lock:
            if key not in self._windows:
                self._windows[key] = deque()
            window = self._windows[key]

            # Evict timestamps outside the window
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= limit:
                return False

            window.append(now)
            return True

    def wait_seconds(self, phone: str, window_seconds: int) -> int:
        """How long until this phone may send again (0 = now)."""
        now = time.monotonic()
        key = f"{phone}:{window_seconds}"
        with self._lock:
            window = self._windows.get(key)
            if not window:
                return 0
            return max(0, int(window[0] + window_seconds - now) + 1)

    def cleanup_old_keys(self):
        """Remove stale entries (call periodically if needed)."""
        now = time.monotonic()
        with self._lock:
            stale = [k for k, dq in self._windows.items()
                     if dq and now - dq[-1] > 1200]
            for k in stale:
                del self._windows[k]


_limiter = _SlidingWindowLimiter()


# ── Public API ────────────────────────────────────────────────────────────────

def check_rate_limit(phone: str, is_registered: bool, is_onboarding: bool, has_active_bot_conversation: bool) -> bool:
    """
    Return True if the request is allowed, False if it should be dropped.

    Registered owners, staff, and users actively onboarding are always allowed.
    """
    if is_registered or is_onboarding:
        return True   # fast mode, busy owners, staff, onboarding — never blocked

    if has_active_bot_conversation:
        return _limiter.is_allowed(phone, CUSTOMER_BOT_LIMIT, CUSTOMER_BOT_WINDOW)

    return _limiter.is_allowed(phone, UNREGISTERED_LIMIT, UNREGISTERED_WINDOW)


def wait_minutes(phone: str, has_active_bot_conversation: bool = False) -> int:
    """The real wait for a throttled phone, in whole minutes (at least 1)."""
    window = CUSTOMER_BOT_WINDOW if has_active_bot_conversation else UNREGISTERED_WINDOW
    secs = _limiter.wait_seconds(phone, window)
    return max(1, -(-secs // 60))


def rate_limit_exceeded_message(minutes: int | None = None) -> str:
    when = (f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes else "a few minutes")
    return (
        "I want to give you my best because you are special.\n\n"
        f"Please wait {when} and send me any message — I'll remember exactly where we stopped."
    )
