"""
In-app notification routes (the bell): list, mark-one-read, mark-all-read.

First per-domain slice split out of web_routes.py. Register with
register_notification_routes(app); shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, AppNotification, PushSubscription
from web_auth import require_web_auth
from web_common import _session_owner_phone


class PushSubscribeRequest(BaseModel):
    endpoint: str = Field(max_length=1000)
    p256dh: str = Field(max_length=300)
    auth: str = Field(max_length=100)


class PushUnsubscribeRequest(BaseModel):
    endpoint: Optional[str] = Field(default=None, max_length=1000)


def register_notification_routes(app):

    @app.get("/app/api/notifications")
    def web_get_notifications(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            rows = (
                db.query(AppNotification)
                .filter(AppNotification.owner_phone == owner_phone)
                .order_by(AppNotification.created_at.desc())
                .limit(50)
                .all()
            )
            return {"notifications": [
                {
                    "id": r.id, "event_type": r.event_type,
                    "title": r.title, "body": r.body,
                    "is_read": bool(r.is_read),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/notifications/{notif_id}/read")
    def web_mark_notification_read(notif_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            notif = db.query(AppNotification).filter(
                AppNotification.id == notif_id,
                AppNotification.owner_phone == owner_phone,
            ).first()
            if notif:
                notif.is_read = 1
                db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/notifications/read-all")
    def web_mark_all_notifications_read(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            db.query(AppNotification).filter(
                AppNotification.owner_phone == owner_phone,
                AppNotification.is_read == 0,
            ).update({"is_read": 1})
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.delete("/app/api/notifications/{notif_id}")
    def web_delete_notification(notif_id: int, session: dict = Depends(require_web_auth)):
        """Permanently delete a single notification (frees the row)."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            deleted = db.query(AppNotification).filter(
                AppNotification.id == notif_id,
                AppNotification.owner_phone == owner_phone,
            ).delete(synchronize_session=False)
            db.commit()
            return {"ok": True, "deleted": deleted}
        finally:
            db.close()

    @app.post("/app/api/notifications/clear")
    def web_clear_notifications(
        only_read: bool = Query(default=False),
        session: dict = Depends(require_web_auth),
    ):
        """Delete notifications for this business. only_read=true clears just the
        read ones; otherwise clears all. Rows are removed, not just hidden."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            q = db.query(AppNotification).filter(AppNotification.owner_phone == owner_phone)
            if only_read:
                q = q.filter(AppNotification.is_read == 1)
            deleted = q.delete(synchronize_session=False)
            db.commit()
            return {"ok": True, "deleted": deleted}
        finally:
            db.close()

    # ── Web Push subscribe / unsubscribe (phone notifications) ────────────────
    @app.get("/app/api/push/status")
    def web_push_status(session: dict = Depends(require_web_auth)):
        """Whether push is configured, and whether this device is subscribed."""
        from web_push import push_enabled
        endpoint = None  # device identity is client-side; report only config here
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            count = db.query(PushSubscription).filter(
                PushSubscription.owner_phone == owner_phone,
            ).count()
            return {"push_enabled": push_enabled(), "subscriptions": count}
        finally:
            db.close()

    @app.post("/app/api/push/subscribe")
    def web_push_subscribe(payload: PushSubscribeRequest, session: dict = Depends(require_web_auth)):
        """Store this device's push subscription for the business."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            existing = db.query(PushSubscription).filter(
                PushSubscription.endpoint == payload.endpoint,
            ).first()
            if existing:
                existing.owner_phone = owner_phone
                existing.user_id = user.id
                existing.p256dh = payload.p256dh
                existing.auth = payload.auth
            else:
                db.add(PushSubscription(
                    owner_phone=owner_phone, user_id=user.id,
                    endpoint=payload.endpoint, p256dh=payload.p256dh, auth=payload.auth,
                ))
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/push/unsubscribe")
    def web_push_unsubscribe(payload: PushUnsubscribeRequest, session: dict = Depends(require_web_auth)):
        """Remove this device's subscription (silences phone notifications)."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            q = db.query(PushSubscription)
            if payload.endpoint:
                q = q.filter(PushSubscription.endpoint == payload.endpoint)
            else:
                # No endpoint given → drop all of this user's device subscriptions.
                q = q.filter(PushSubscription.user_id == user.id)
            removed = q.delete(synchronize_session=False)
            db.commit()
            return {"ok": True, "removed": removed}
        finally:
            db.close()
