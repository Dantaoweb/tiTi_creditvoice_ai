"""
In-app notification routes (the bell): list, mark-one-read, mark-all-read.

First per-domain slice split out of web_routes.py. Register with
register_notification_routes(app); shared helpers come from web_common.
"""
from fastapi import Depends, HTTPException, Query

from database import SessionLocal
from models import User, AppNotification
from web_auth import require_web_auth
from web_common import _session_owner_phone


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
