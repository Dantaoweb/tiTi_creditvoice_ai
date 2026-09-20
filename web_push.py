"""
Web Push delivery — sends browser push notifications to a business's subscribed
devices so alerts reach the phone while the app is closed.

Configured via env: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT. When
unconfigured it no-ops silently (WhatsApp + the in-app bell still work). Sending
happens on a background thread so it never blocks the request or scheduler.
"""
import json
import os
import threading

VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT     = os.getenv("VAPID_SUBJECT", "mailto:support@creditvoiceai.com").strip()


def push_enabled() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def send_web_push(owner_phone: str, title: str, body: str, url: str = "/app",
                  tag: str = "") -> None:
    """Fire-and-forget: push to every subscribed device of the business.

    `tag` groups notifications on the phone — pass the event type so a low-stock
    alert doesn't silently replace an overdue-debt one (the service worker sets
    renotify, so a repeat of the same type still alerts).

    Cheap when nobody subscribed (one indexed query returning nothing). Only
    users who opted in have rows, so the network cost is limited to them."""
    if not push_enabled() or not owner_phone:
        return
    threading.Thread(
        target=_send_blocking, args=(owner_phone, title, body, url, tag), daemon=True
    ).start()


def _send_blocking(owner_phone, title, body, url, tag=""):
    try:
        from pywebpush import webpush, WebPushException
        from database import SessionLocal
        from models import PushSubscription
    except Exception:
        return

    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).filter(
            PushSubscription.owner_phone == owner_phone
        ).all()
        if not subs:
            return
        payload = json.dumps({"title": title, "body": body, "url": url,
                              "tag": tag or "cv-notify"})
        dead = []
        for s in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": s.endpoint,
                        "keys": {"p256dh": s.p256dh, "auth": s.auth},
                    },
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_SUBJECT},
                    timeout=10,
                )
            except WebPushException as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                if code in (404, 410):          # subscription gone — prune it
                    dead.append(s.id)
            except Exception:
                pass
        if dead:
            db.query(PushSubscription).filter(
                PushSubscription.id.in_(dead)
            ).delete(synchronize_session=False)
            db.commit()
    except Exception as exc:
        print(f"[web_push] send error for {owner_phone}: {exc}", flush=True)
    finally:
        db.close()
