"""
App-admin routes: broadcast notifications, failed-parse log (list + CSV export),
overview stats, and the users directory.

Split out of web_routes.py. Register with register_admin_routes(app); shared
helpers come from web_common. Every endpoint is app-admin only (is_app_admin)
and rate-limited.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, AppNotification, FailedParse, Transaction, utcnow
from web_auth import require_web_auth
from web_common import _admin_rate_check, _export_rate_check


class AdminNotifyRequest(BaseModel):
    title: str = Field(max_length=120)
    body: str = Field(max_length=1000)
    target: str = "all"                       # "all" business owners, or "phone"
    phone: Optional[str] = Field(default=None, max_length=20)
    also_whatsapp: bool = False


def register_admin_routes(app):

    @app.post("/app/api/admin/notifications")
    def web_admin_send_notification(payload: AdminNotifyRequest, session: dict = Depends(require_web_auth)):
        """App admin broadcasts an in-app notification to one user or all business
        owners (optionally also via WhatsApp)."""
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
            title = payload.title.strip()
            body = payload.body.strip()
            if not title or not body:
                raise HTTPException(status_code=400, detail="Title and message are required.")

            if payload.target == "phone":
                from parser import normalize_phone
                target = db.query(User).filter(
                    User.phone.in_([p for p in {(payload.phone or "").strip(), normalize_phone(payload.phone or "")} if p]),
                    User.parent_id.is_(None),
                ).first()
                if not target:
                    raise HTTPException(status_code=404, detail="No business owner with that phone.")
                phones = [target.phone]
            else:
                phones = [
                    r[0] for r in db.query(User.phone).filter(
                        User.parent_id.is_(None), User.deleted_at.is_(None)
                    ).all() if r[0]
                ]

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for ph in phones:
                db.add(AppNotification(owner_phone=ph, event_type="admin",
                                       title=title, body=body, is_read=0, created_at=now))
            db.commit()

            sent_wa = 0
            if payload.also_whatsapp:
                from whatsapp_client import send_whatsapp_message
                for ph in phones:
                    try:
                        if send_whatsapp_message(ph, f"*{title}*\n\n{body}"):
                            sent_wa += 1
                    except Exception:
                        pass
            return {"ok": True, "recipients": len(phones), "whatsapp_sent": sent_wa}
        finally:
            db.close()

    # ── Admin: failed parse log ───────────────────────────────────────────────
    @app.get("/app/api/admin/failed-parses")
    def web_admin_failed_parses(
        limit: int = Query(default=200, le=1000),
        session: dict = Depends(require_web_auth),
    ):
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
            rows = (
                db.query(FailedParse)
                .order_by(FailedParse.created_at.desc())
                .limit(limit)
                .all()
            )
            return {"rows": [
                {
                    "id": r.id,
                    "phone": r.phone,
                    "text": r.text,
                    "resolved_by": r.resolved_by,
                    "llm_reply": r.llm_reply,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]}
        finally:
            db.close()

    @app.get("/app/api/admin/failed-parses/export")
    def web_admin_failed_parses_export(
        session: dict = Depends(require_web_auth),
    ):
        import csv, io
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _export_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Export limit reached. Max 3 exports per hour.")
            from audit import audit
            audit(db, action="ADMIN_DATA_EXPORT", actor_id=user.id, actor_phone=user.phone,
                  resource="failed_parses.csv")
            db.commit()
            rows = db.query(FailedParse).order_by(FailedParse.created_at.desc()).limit(5000).all()
            from export_utils import _csv_safe
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "phone", "text", "resolved_by", "llm_reply", "created_at"])
            for r in rows:
                writer.writerow([_csv_safe(v) for v in (
                    r.id, r.phone, r.text, r.resolved_by or "",
                    r.llm_reply or "",
                    r.created_at.isoformat() if r.created_at else "",
                )])
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=failed_parses.csv"},
            )
        finally:
            db.close()

    # ── Admin: overview stats ──────────────────────────────────────────────────
    @app.get("/app/api/admin/stats")
    def web_admin_stats(session: dict = Depends(require_web_auth)):
        from admin import is_app_admin
        from datetime import timedelta
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            now = utcnow()
            today_start   = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start    = today_start - timedelta(days=7)
            month_start   = today_start - timedelta(days=30)

            total_users   = db.query(User).filter(User.parent_id == None).count()
            new_today     = db.query(User).filter(User.parent_id == None, User.created_at >= today_start).count()
            new_this_week = db.query(User).filter(User.parent_id == None, User.created_at >= week_start).count()
            new_this_month= db.query(User).filter(User.parent_id == None, User.created_at >= month_start).count()

            total_tx      = db.query(Transaction).count()
            tx_today      = db.query(Transaction).filter(Transaction.created_at >= today_start).count()
            tx_this_week  = db.query(Transaction).filter(Transaction.created_at >= week_start).count()

            failed_total  = db.query(FailedParse).count()
            failed_today  = db.query(FailedParse).filter(FailedParse.created_at >= today_start).count()
            llm_resolved  = db.query(FailedParse).filter(FailedParse.resolved_by == "llm").count()

            # Signup trend: last 14 days
            signup_trend = []
            for i in range(13, -1, -1):
                day_start = today_start - timedelta(days=i)
                day_end   = day_start + timedelta(days=1)
                count = db.query(User).filter(
                    User.parent_id == None,
                    User.created_at >= day_start,
                    User.created_at < day_end,
                ).count()
                signup_trend.append({
                    "date": day_start.strftime("%b %d"),
                    "signups": count,
                })

            # Tx trend: last 14 days
            tx_trend = []
            for i in range(13, -1, -1):
                day_start = today_start - timedelta(days=i)
                day_end   = day_start + timedelta(days=1)
                count = db.query(Transaction).filter(
                    Transaction.created_at >= day_start,
                    Transaction.created_at < day_end,
                ).count()
                tx_trend.append({
                    "date": day_start.strftime("%b %d"),
                    "transactions": count,
                })

            # Business type breakdown
            biz_types = {}
            for u in db.query(User).filter(User.parent_id == None).all():
                key = u.business_type_label or u.business_type or "Unknown"
                biz_types[key] = biz_types.get(key, 0) + 1

            biz_breakdown = sorted(
                [{"label": k, "count": v} for k, v in biz_types.items()],
                key=lambda x: -x["count"]
            )[:10]

            return {
                "users": {
                    "total": total_users,
                    "new_today": new_today,
                    "new_this_week": new_this_week,
                    "new_this_month": new_this_month,
                    "signup_trend": signup_trend,
                },
                "transactions": {
                    "total": total_tx,
                    "today": tx_today,
                    "this_week": tx_this_week,
                    "tx_trend": tx_trend,
                },
                "failed_parses": {
                    "total": failed_total,
                    "today": failed_today,
                    "llm_resolved": llm_resolved,
                },
                "business_breakdown": biz_breakdown,
            }
        finally:
            db.close()

    @app.get("/app/api/admin/users")
    def web_admin_users(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=50, le=200),
        q: str = Query(default=""),
        session: dict = Depends(require_web_auth),
    ):
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            query = db.query(User).filter(User.parent_id == None)
            if q:
                like = f"%{q}%"
                query = query.filter(
                    User.name.ilike(like) | User.phone.ilike(like) | User.email.ilike(like)
                )

            total = query.count()
            rows  = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

            return {
                "total": total,
                "page": page,
                "per_page": per_page,
                "users": [
                    {
                        "id": u.id,
                        "name": u.name,
                        "phone": u.phone,
                        "email": u.email,
                        "business_type_label": u.business_type_label or u.business_type,
                        "subscription_plan": u.subscription_plan,
                        "subscription_status": u.subscription_status,
                        "created_at": u.created_at.isoformat() if u.created_at else None,
                    }
                    for u in rows
                ],
            }
        finally:
            db.close()
