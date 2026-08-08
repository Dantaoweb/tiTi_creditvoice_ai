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
from models import User, AppNotification, FailedParse, Transaction, Customer, InventoryItem, utcnow
from web_auth import require_web_auth
from web_common import _admin_rate_check, _export_rate_check, _add_notification


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
        sort: str = Query(default="recent"),   # recent | active | name
        session: dict = Depends(require_web_auth),
    ):
        """Business directory with per-user activity — how much each business
        actually uses the app: transactions recorded (all-time + last 30 days),
        last active, and customer / stock counts. sort=active ranks every
        business by transaction volume (the platform-wide "most active" view)."""
        from admin import is_app_admin
        from collections import defaultdict
        from datetime import timedelta
        from sqlalchemy import func, case
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            month_start = utcnow() - timedelta(days=30)
            not_voided = Transaction.is_voided != True
            recent_flag = case((Transaction.created_at >= month_start, 1), else_=0)

            # ── Global activity maps (one grouped pass each) ──────────────────
            # A transaction belongs to a business via its customer's owner_phone,
            # or (direct sales with no customer) via the recorder's owner. Build
            # both, keyed by owner phone.
            tx_total  = defaultdict(int)
            tx_30d    = defaultdict(int)
            last_seen = {}

            cust_rows = (
                db.query(
                    Customer.owner_phone,
                    func.count(Transaction.id),
                    func.sum(recent_flag),
                    func.max(Transaction.created_at),
                )
                .join(Transaction, Transaction.customer_id == Customer.id)
                .filter(not_voided)
                .group_by(Customer.owner_phone)
                .all()
            )
            for ph, cnt, c30, last in cust_rows:
                if not ph:
                    continue
                tx_total[ph] += int(cnt or 0)
                tx_30d[ph] += int(c30 or 0)
                if last:
                    last_seen[ph] = last

            # Map every user id → their business owner phone (owners → self,
            # staff → parent) so direct sales attribute to the business.
            id_phone, parent_of = {}, {}
            for uid, uphone, pid in db.query(User.id, User.phone, User.parent_id).all():
                id_phone[uid] = uphone
                parent_of[uid] = pid

            def _owner_phone(uid):
                pid = parent_of.get(uid)
                return id_phone.get(pid) if pid else id_phone.get(uid)

            direct_rows = (
                db.query(
                    Transaction.recorded_by_id,
                    func.count(Transaction.id),
                    func.sum(recent_flag),
                    func.max(Transaction.created_at),
                )
                .filter(Transaction.customer_id == None, not_voided)
                .group_by(Transaction.recorded_by_id)
                .all()
            )
            for rid, cnt, c30, last in direct_rows:
                ph = _owner_phone(rid)
                if not ph:
                    continue
                tx_total[ph] += int(cnt or 0)
                tx_30d[ph] += int(c30 or 0)
                if last and (ph not in last_seen or last > last_seen[ph]):
                    last_seen[ph] = last

            # ── Base directory query ──────────────────────────────────────────
            query = db.query(User).filter(User.parent_id == None)
            if q:
                like = f"%{q}%"
                query = query.filter(
                    User.name.ilike(like) | User.phone.ilike(like) | User.email.ilike(like)
                )
            total = query.count()

            start = (page - 1) * per_page
            if sort == "active":
                # True platform-wide ranking: order all matches by tx volume.
                owners = query.all()
                owners.sort(key=lambda u: (tx_total.get(u.phone, 0), tx_30d.get(u.phone, 0)), reverse=True)
                rows = owners[start:start + per_page]
            elif sort == "name":
                rows = query.order_by(User.name).offset(start).limit(per_page).all()
            else:
                rows = query.order_by(User.created_at.desc()).offset(start).limit(per_page).all()

            # ── Customer / stock counts for the page's businesses ─────────────
            page_phones = [u.phone for u in rows if u.phone]
            cust_counts = dict(
                db.query(Customer.owner_phone, func.count(Customer.id))
                .filter(Customer.owner_phone.in_(page_phones))
                .group_by(Customer.owner_phone).all()
            ) if page_phones else {}
            item_counts = dict(
                db.query(InventoryItem.owner_phone, func.count(InventoryItem.id))
                .filter(InventoryItem.owner_phone.in_(page_phones))
                .group_by(InventoryItem.owner_phone).all()
            ) if page_phones else {}

            return {
                "total": total,
                "page": page,
                "per_page": per_page,
                "sort": sort,
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
                        "deleted_at": u.deleted_at.isoformat() if u.deleted_at else None,
                        "transactions_total": tx_total.get(u.phone, 0),
                        "transactions_30d": tx_30d.get(u.phone, 0),
                        "last_active": last_seen[u.phone].isoformat() if u.phone in last_seen else None,
                        "customers": int(cust_counts.get(u.phone, 0)),
                        "stock_items": int(item_counts.get(u.phone, 0)),
                    }
                    for u in rows
                ],
            }
        finally:
            db.close()

    @app.delete("/app/api/admin/users/{user_id}")
    def web_admin_remove_user(user_id: str, session: dict = Depends(require_web_auth)):
        """Soft-remove a business: mark it (and its staff) deleted, sign every
        session out (token_version bump), and block future logins. Recoverable
        via the restore endpoint. App-admin only, audited."""
        from admin import is_app_admin
        db = SessionLocal()
        try:
            actor = db.query(User).filter(User.id == session["user_id"]).first()
            if not actor or not is_app_admin(actor.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(actor.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            target = db.query(User).filter(User.id == user_id, User.parent_id == None).first()
            if not target:
                raise HTTPException(status_code=404, detail="Business not found.")
            if target.id == actor.id:
                raise HTTPException(status_code=400, detail="You cannot remove your own account.")
            if target.deleted_at:
                return {"ok": True, "already_removed": True}

            now = utcnow()
            # Remove the owner and cascade to their staff so the whole business
            # loses access together.
            members = db.query(User).filter(User.parent_id == target.id).all()
            for u in [target, *members]:
                u.deleted_at = now
                u.token_version = (u.token_version or 0) + 1

            from audit import audit
            audit(db, action="ADMIN_REMOVE_USER", actor_id=actor.id, actor_phone=actor.phone,
                  resource=f"user:{target.id}:{target.phone}")
            db.commit()
            return {"ok": True, "staff_removed": len(members)}
        finally:
            db.close()

    @app.post("/app/api/admin/users/{user_id}/restore")
    def web_admin_restore_user(user_id: str, session: dict = Depends(require_web_auth)):
        """Undo a soft-remove: clear the deleted flag on the business and its
        staff so they can log in again. App-admin only, audited."""
        from admin import is_app_admin
        db = SessionLocal()
        try:
            actor = db.query(User).filter(User.id == session["user_id"]).first()
            if not actor or not is_app_admin(actor.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(actor.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            target = db.query(User).filter(User.id == user_id, User.parent_id == None).first()
            if not target:
                raise HTTPException(status_code=404, detail="Business not found.")

            members = db.query(User).filter(User.parent_id == target.id).all()
            for u in [target, *members]:
                u.deleted_at = None
                u.token_version = (u.token_version or 0) + 1

            from audit import audit
            audit(db, action="ADMIN_RESTORE_USER", actor_id=actor.id, actor_phone=actor.phone,
                  resource=f"user:{target.id}:{target.phone}")
            db.commit()
            return {"ok": True, "staff_restored": len(members)}
        finally:
            db.close()

    # ── Subscription payments: list + approve/reject bank transfers ───────────
    @app.get("/app/api/admin/subscription-payments")
    def web_admin_subscription_payments(
        status: str = Query(default="PENDING"),
        session: dict = Depends(require_web_auth),
    ):
        """Pending (default) subscription payments awaiting admin confirmation —
        the web equivalent of the WhatsApp 'approve <phone>' flow."""
        from admin import is_app_admin
        from models import SubscriptionPayment
        db = SessionLocal()
        try:
            actor = db.query(User).filter(User.id == session["user_id"]).first()
            if not actor or not is_app_admin(actor.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(actor.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            q = db.query(SubscriptionPayment)
            if status:
                q = q.filter(SubscriptionPayment.status == status.upper())
            rows = q.order_by(SubscriptionPayment.created_at.desc()).limit(200).all()
            owners = {
                u.id: u for u in db.query(User).filter(
                    User.id.in_([r.user_id for r in rows] or [None])
                ).all()
            }
            return {"payments": [
                {
                    "id": r.id,
                    "plan": r.plan,
                    "period": r.billing_period or "MONTHLY",
                    "amount": r.amount,
                    "method": r.payment_method,
                    "status": r.status,
                    "phone": r.phone,
                    "owner_name": (owners.get(r.user_id).name if owners.get(r.user_id) else None),
                    "evidence_type": r.evidence_type,
                    "evidence_ref": r.evidence_ref,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/admin/subscription-payments/{payment_id}/approve")
    def web_admin_approve_payment(payment_id: int, session: dict = Depends(require_web_auth)):
        """Activate a pending subscription payment (bank transfer) from the web."""
        from admin import is_app_admin
        from models import SubscriptionPayment, PendingAction
        from subscriptions import approve_subscription_payment
        db = SessionLocal()
        try:
            actor = db.query(User).filter(User.id == session["user_id"]).first()
            if not actor or not is_app_admin(actor.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(actor.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            payment = db.query(SubscriptionPayment).filter(SubscriptionPayment.id == payment_id).first()
            if not payment:
                raise HTTPException(status_code=404, detail="Payment not found.")
            if payment.status != "PENDING":
                raise HTTPException(status_code=409, detail=f"Payment already {payment.status.lower()}.")

            owner = approve_subscription_payment(db, payment, actor)
            if not owner:
                raise HTTPException(status_code=409, detail="Could not approve (already processed).")
            db.query(PendingAction).filter(
                PendingAction.phone == owner.phone,
                PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING",
            ).delete()
            from audit import audit
            audit(db, action="ADMIN_APPROVE_SUBSCRIPTION", actor_id=actor.id, actor_phone=actor.phone,
                  resource=f"payment:{payment.id}:{owner.phone}:{owner.subscription_plan}")
            _exp = owner.subscription_expires_at.strftime('%d/%m/%Y') if owner.subscription_expires_at else "—"
            _add_notification(db, owner.phone, "upgrade", "Subscription activated",
                              f"Your {owner.subscription_plan} plan is now active (expires {_exp}).")
            db.commit()
            try:
                from whatsapp_client import send_whatsapp_message
                send_whatsapp_message(
                    owner.phone,
                    f"Your {owner.subscription_plan} plan is now active.\nExpires: {_exp}\n\n"
                    "Send MY PLAN anytime to check your subscription.")
            except Exception:
                pass
            return {"ok": True, "plan": owner.subscription_plan, "expires_at":
                    owner.subscription_expires_at.isoformat() if owner.subscription_expires_at else None}
        finally:
            db.close()

    @app.post("/app/api/admin/subscription-payments/{payment_id}/reject")
    def web_admin_reject_payment(payment_id: int, session: dict = Depends(require_web_auth)):
        """Reject a pending subscription payment and let the owner know."""
        from admin import is_app_admin
        from models import SubscriptionPayment, PendingAction
        db = SessionLocal()
        try:
            actor = db.query(User).filter(User.id == session["user_id"]).first()
            if not actor or not is_app_admin(actor.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(actor.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            payment = db.query(SubscriptionPayment).filter(SubscriptionPayment.id == payment_id).first()
            if not payment:
                raise HTTPException(status_code=404, detail="Payment not found.")
            if payment.status != "PENDING":
                raise HTTPException(status_code=409, detail=f"Payment already {payment.status.lower()}.")

            payment.status = "REJECTED"
            owner = db.query(User).filter(User.id == payment.user_id).first()
            if owner:
                db.query(PendingAction).filter(
                    PendingAction.phone == owner.phone,
                    PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING",
                ).delete()
                _add_notification(db, owner.phone, "upgrade", "Payment not confirmed",
                                  "Your subscription payment could not be confirmed. Please send a clearer receipt or contact support.")
            from audit import audit
            audit(db, action="ADMIN_REJECT_SUBSCRIPTION", actor_id=actor.id, actor_phone=actor.phone,
                  resource=f"payment:{payment.id}")
            db.commit()
            if owner:
                try:
                    from whatsapp_client import send_whatsapp_message
                    send_whatsapp_message(
                        owner.phone,
                        "Your subscription payment could not be confirmed. Please send a clearer receipt.")
                except Exception:
                    pass
            return {"ok": True}
        finally:
            db.close()
