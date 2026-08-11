"""
Proactive tiTi scheduler.

Runs three checks and delivers alerts to BOTH WhatsApp and the frontend
(via AppNotification table, shown as a bell icon in the web app).

Checks:
  1. Low-stock alerts  — items at or below alert threshold (once per 24h)
  2. Overdue debt      — customers with balance >7 days unpaid (every 72h)
  3. Inactivity nudge  — no messages in 3+ days (once per week)

Interval: every 6 hours.  ProactiveLog prevents duplicate sends.
"""

import asyncio
from datetime import datetime, timedelta, timezone

_INTERVAL_HOURS = 6

# Exposed so /health can report when the scheduler last completed a full cycle.
last_run_at: datetime | None = None


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _notify(db, owner_phone, event_type, title, body, send_whatsapp=True):
    """Save a frontend notification AND optionally send via WhatsApp."""
    from models import AppNotification
    from whatsapp_client import send_whatsapp_message

    db.add(AppNotification(
        owner_phone=owner_phone,
        event_type=event_type,
        title=title,
        body=body,
        is_read=0,
        created_at=_utcnow(),
    ))
    db.commit()

    # Web Push to the business's subscribed devices (reaches the phone while the
    # app is closed). Fire-and-forget; no-op when push is unconfigured.
    try:
        from web_push import send_web_push
        send_web_push(owner_phone, title, body)
    except Exception:
        pass

    if send_whatsapp:
        try:
            send_whatsapp_message(owner_phone, f"*{title}*\n\n{body}")
        except Exception as e:
            print(f"[proactive] WhatsApp send error for {owner_phone}: {e}", flush=True)


# ── Low-stock check ─────────────────────────────────────────────────────────────

def _check_low_stock(db):
    from models import InventoryItem, ProactiveLog, User

    owners = db.query(User).filter(
        # Any top-level account is an owner. Web-registered owners have role
        # "owner", WhatsApp ones "user" — gate on parent_id, not role, or web
        # owners get no proactive reminders/alerts at all.
        User.parent_id == None,
        User.phone != None,
    ).all()

    for owner in owners:
        low_items = [
            it for it in db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner.phone,
                InventoryItem.is_available == True,
                InventoryItem.low_stock_alert != None,
                InventoryItem.quantity != None,
            ).all()
            if (it.quantity or 0) <= it.low_stock_alert
        ]
        if not low_items:
            continue

        last = db.query(ProactiveLog).filter(
            ProactiveLog.owner_phone == owner.phone,
            ProactiveLog.event_type == "low_stock",
        ).order_by(ProactiveLog.sent_at.desc()).first()

        if last and (_utcnow() - last.sent_at).total_seconds() < 86400:
            continue

        lines = "\n".join(
            f"• {it.name.title()}: {it.quantity or 0} {it.unit or 'unit(s)'} left"
            for it in low_items[:8]
        )
        body = (
            f"These {len(low_items)} product(s) need restocking:\n\n"
            f"{lines}\n\n"
            "Send *stock* to see your full inventory."
        )

        try:
            _notify(db, owner.phone, "low_stock", "⚠️ Low Stock Alert", body)
            db.add(ProactiveLog(
                owner_phone=owner.phone,
                event_type="low_stock",
                sent_at=_utcnow(),
            ))
            db.commit()
        except Exception as e:
            print(f"[proactive] low_stock error for {owner.phone}: {e}", flush=True)


# ── Overdue debt check ──────────────────────────────────────────────────────────

def _check_overdue_debt(db):
    from models import Customer, ProactiveLog, User

    cutoff = _utcnow() - timedelta(days=7)

    owners = db.query(User).filter(
        # Any top-level account is an owner. Web-registered owners have role
        # "owner", WhatsApp ones "user" — gate on parent_id, not role, or web
        # owners get no proactive reminders/alerts at all.
        User.parent_id == None,
        User.phone != None,
    ).all()

    for owner in owners:
        debtors = db.query(Customer).filter(
            Customer.owner_phone == owner.phone,
            Customer.balance > 0,
            Customer.last_transaction_at != None,
            Customer.last_transaction_at <= cutoff,
        ).order_by(Customer.balance.desc()).limit(5).all()

        if not debtors:
            continue

        last = db.query(ProactiveLog).filter(
            ProactiveLog.owner_phone == owner.phone,
            ProactiveLog.event_type == "overdue_debt",
        ).order_by(ProactiveLog.sent_at.desc()).first()

        if last and (_utcnow() - last.sent_at).total_seconds() < 259200:
            continue

        total = sum(d.balance for d in debtors)
        lines = "\n".join(
            f"• {(d.name or 'Customer').title()}: ₦{d.balance:,.0f}"
            for d in debtors
        )
        body = (
            f"Customers with balances older than 7 days:\n\n"
            f"{lines}\n\n"
            f"Total: ₦{total:,.0f}\n\n"
            "Tap to send reminders, or say *debtors* in chat."
        )

        try:
            _notify(db, owner.phone, "overdue_debt", "💰 Unpaid Debts", body)
            db.add(ProactiveLog(
                owner_phone=owner.phone,
                event_type="overdue_debt",
                sent_at=_utcnow(),
            ))
            db.commit()
        except Exception as e:
            print(f"[proactive] overdue_debt error for {owner.phone}: {e}", flush=True)


# ── Inactivity nudge ────────────────────────────────────────────────────────────

def _check_inactivity(db):
    from models import ProactiveLog, Transaction, User

    cutoff_inactive = _utcnow() - timedelta(days=3)
    cutoff_nudge    = _utcnow() - timedelta(days=7)

    owners = db.query(User).filter(
        # Any top-level account is an owner. Web-registered owners have role
        # "owner", WhatsApp ones "user" — gate on parent_id, not role, or web
        # owners get no proactive reminders/alerts at all.
        User.parent_id == None,
        User.phone != None,
    ).all()

    for owner in owners:
        last_tx = db.query(Transaction).filter(
            Transaction.owner_phone == owner.phone,
        ).order_by(Transaction.created_at.desc()).first()

        if not last_tx or last_tx.created_at > cutoff_inactive:
            continue

        last = db.query(ProactiveLog).filter(
            ProactiveLog.owner_phone == owner.phone,
            ProactiveLog.event_type == "inactivity",
        ).order_by(ProactiveLog.sent_at.desc()).first()

        if last and last.sent_at > cutoff_nudge:
            continue

        first_name = (owner.name or "there").split()[0].title()
        body = (
            f"Hi {first_name}! We noticed you haven't recorded anything in a few days.\n\n"
            "Quick question — what's been happening?\n\n"
            "1️⃣ Just been busy, I'll catch up\n"
            "2️⃣ I'm not sure how to record something\n"
            "3️⃣ Business has been slow lately\n"
            "4️⃣ Something else\n\n"
            "Reply with 1, 2, 3 or 4 — tiTi will help from there 🤝"
        )

        try:
            _notify(db, owner.phone, "inactivity", "👋 Missing you!", body)
            # Set a pending action so tiTi can respond to their reply
            from models import PendingAction
            db.query(PendingAction).filter(
                PendingAction.phone == owner.phone,
                PendingAction.action == "INACTIVITY_CHECKIN",
            ).delete()
            db.add(PendingAction(
                phone=owner.phone,
                action="INACTIVITY_CHECKIN",
                created_at=_utcnow(),
            ))
            db.add(ProactiveLog(
                owner_phone=owner.phone,
                event_type="inactivity",
                sent_at=_utcnow(),
            ))
            db.commit()
        except Exception as e:
            print(f"[proactive] inactivity error for {owner.phone}: {e}", flush=True)


# ── Reminder automation ─────────────────────────────────────────────────────────

def _check_reminder_automation(db):
    """Run reminder automation for every owner who has auto_send_enabled."""
    from models import User
    from reminder_automation import get_or_create_reminder_settings, run_reminder_automation
    from whatsapp_client import send_whatsapp_message

    owners = db.query(User).filter(
        # Any top-level account is an owner. Web-registered owners have role
        # "owner", WhatsApp ones "user" — gate on parent_id, not role, or web
        # owners get no proactive reminders/alerts at all.
        User.parent_id == None,
        User.phone != None,
    ).all()

    for owner in owners:
        try:
            settings = get_or_create_reminder_settings(db, owner.phone)
            if not getattr(settings, "auto_send_enabled", False):
                continue
            result = run_reminder_automation(db, owner.phone, send_whatsapp_message)
            if result.get("sent", 0) > 0:
                print(f"[proactive] reminders: sent {result['sent']} for {owner.phone}", flush=True)
        except Exception as e:
            print(f"[proactive] reminder_automation error for {owner.phone}: {e}", flush=True)


# ── Main scheduler loop ─────────────────────────────────────────────────────────

_LOG_RETENTION_DAYS = 90


def _purge_old_logs(db) -> None:
    """Delete parse_logs and failed_parses older than 90 days (NDPR storage limitation).

    Raw WhatsApp message content must not be held longer than necessary.
    Retention period: 90 days from creation.
    """
    from models import FailedParse, ParseLog
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=_LOG_RETENTION_DAYS)
    deleted_parse   = db.query(ParseLog).filter(ParseLog.created_at < cutoff).delete()
    deleted_failed  = db.query(FailedParse).filter(FailedParse.created_at < cutoff).delete()
    if deleted_parse or deleted_failed:
        db.commit()
        print(
            f"[proactive] Log retention: purged {deleted_parse} parse_logs, "
            f"{deleted_failed} failed_parses older than {_LOG_RETENTION_DAYS} days.",
            flush=True,
        )


# Notifications self-limit so the app_notifications table can't grow without
# bound: read ones drop after 30 days, and no business keeps more than 200 rows.
_NOTIF_READ_RETENTION_DAYS = 30
_NOTIF_KEEP_MAX = 200


def _purge_old_notifications(db) -> None:
    """Delete read notifications older than 30 days, and cap each business to the
    most recent 200 rows so the bell's backing table stays bounded.

    'note' notifications are NEVER auto-deleted — notes are business records, so
    the automatic retention leaves them alone. (Users can still delete them by
    hand from the bell.)"""
    from models import AppNotification
    from sqlalchemy import func

    # coalesce so rows with a NULL event_type still count as non-note.
    not_a_note = func.coalesce(AppNotification.event_type, "") != "note"

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=_NOTIF_READ_RETENTION_DAYS)
    deleted_read = db.query(AppNotification).filter(
        AppNotification.is_read == 1,
        AppNotification.created_at < cutoff,
        not_a_note,
    ).delete(synchronize_session=False)

    # The cap counts and deletes only non-note rows; notes are always kept.
    capped = 0
    overflowing = (
        db.query(AppNotification.owner_phone)
        .filter(not_a_note)
        .group_by(AppNotification.owner_phone)
        .having(func.count(AppNotification.id) > _NOTIF_KEEP_MAX)
        .all()
    )
    for (owner_phone,) in overflowing:
        keep_ids = [
            r.id for r in db.query(AppNotification.id)
            .filter(AppNotification.owner_phone == owner_phone, not_a_note)
            .order_by(AppNotification.created_at.desc(), AppNotification.id.desc())
            .limit(_NOTIF_KEEP_MAX)
            .all()
        ]
        if keep_ids:
            capped += db.query(AppNotification).filter(
                AppNotification.owner_phone == owner_phone,
                not_a_note,
                ~AppNotification.id.in_(keep_ids),
            ).delete(synchronize_session=False)

    if deleted_read or capped:
        db.commit()
        print(
            f"[proactive] Notification retention: purged {deleted_read} read "
            f"(>{_NOTIF_READ_RETENTION_DAYS}d) + {capped} over the {_NOTIF_KEEP_MAX}-row cap "
            f"(notes preserved).",
            flush=True,
        )


# ── Delivery / ready-by reminders (owner-facing) ────────────────────────────────

def _check_delivery_due(db):
    """Remind the owner 2 days before, 1 day before, and on the day a job/order
    is promised for delivery (Transaction.service_date). Owner-facing only —
    the customer is messaged separately when the owner chooses."""
    from models import Transaction, Customer, ProactiveLog

    today = _utcnow().date()
    # Single bounded query across all businesses: only deliveries due in the next
    # 0–2 days, joined to their customer (owner_phone + name). Far cheaper than a
    # per-owner scan of every service-dated transaction.
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today + timedelta(days=3), datetime.min.time())

    rows = (
        db.query(Transaction, Customer)
        .join(Customer, Transaction.customer_id == Customer.id)
        .filter(
            Transaction.service_date >= start,
            Transaction.service_date < end,
            Transaction.is_voided != True,
        )
        .all()
    )

    for tx, cust in rows:
        owner_phone = cust.owner_phone
        if not owner_phone:
            continue
        days_out = (tx.service_date.date() - today).days
        if days_out not in (0, 1, 2):
            continue
        event_type = f"delivery_{tx.id}_{days_out}"
        already = db.query(ProactiveLog).filter(
            ProactiveLog.owner_phone == owner_phone,
            ProactiveLog.event_type == event_type,
        ).first()
        if already:
            continue

        cname = cust.name.title() if cust.name else "A customer"
        when = "today" if days_out == 0 else ("tomorrow" if days_out == 1 else f"in {days_out} days")
        date_str = tx.service_date.strftime("%d %b %Y")
        body = (
            f"{cname}'s job/order (Receipt #{tx.id}) is due for delivery {when} ({date_str}).\n\n"
            "Open Deliveries to update the date or message the customer."
        )
        try:
            _notify(db, owner_phone, event_type, "📦 Delivery Reminder", body)
            db.add(ProactiveLog(owner_phone=owner_phone, event_type=event_type, sent_at=_utcnow()))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[proactive] delivery reminder error for {owner_phone}: {e}", flush=True)


# ── Supplier payment due ─────────────────────────────────────────────────────────

def _check_supplier_due(db):
    """Remind owners of supplier payments falling due (up to 3 days out) or
    overdue, while the supplier still has an outstanding balance. Delivers via
    in-app notification + web push + WhatsApp — so web-only owners get it, not
    just the WhatsApp daily digest. Advance reminders fire once per day-bucket;
    an overdue balance re-reminds at most once a week."""
    from models import ProactiveLog, Supplier, SupplierPurchase, User
    from inventory_suppliers import get_supplier_balance

    today = _utcnow().date()
    owners = db.query(User).filter(
        # Web owners have role "owner", WhatsApp ones "user" — gate on parent_id.
        User.parent_id == None,
        User.phone != None,
    ).all()

    for owner in owners:
        purchases = db.query(SupplierPurchase).filter(
            SupplierPurchase.owner_phone == owner.phone,
            SupplierPurchase.due_date != None,
            SupplierPurchase.total > SupplierPurchase.paid_amount,
        ).all()
        if not purchases:
            continue

        bal_cache = {}   # supplier_id → net balance still owed
        for p in purchases:
            days_out = (p.due_date.date() - today).days
            if days_out > 3:
                continue   # too far out to remind yet

            if p.supplier_id not in bal_cache:
                bal_cache[p.supplier_id] = get_supplier_balance(db, p.supplier_id)
            if bal_cache[p.supplier_id] <= 0:
                continue   # already settled via later payments

            if days_out < 0:
                yr, wk, _ = today.isocalendar()
                bucket = f"ov{yr}w{wk}"     # weekly overdue re-reminder
            else:
                bucket = str(days_out)      # once per remaining-day bucket
            event_type = f"supplier_due_{p.id}_{bucket}"

            already = db.query(ProactiveLog).filter(
                ProactiveLog.owner_phone == owner.phone,
                ProactiveLog.event_type == event_type,
            ).first()
            if already:
                continue

            sup = db.query(Supplier).filter(Supplier.id == p.supplier_id).first()
            sup_name = (sup.name.title() if sup and sup.name else "a supplier")
            owed = max(0, (p.total or 0) - (p.paid_amount or 0))
            date_str = p.due_date.strftime("%d %b %Y")
            when = (
                "was due" if days_out < 0
                else ("is due today" if days_out == 0
                      else ("is due tomorrow" if days_out == 1 else f"is due in {days_out} days"))
            )
            body = (
                f"Payment to {sup_name} for {(p.product or 'stock').title()} {when} ({date_str}).\n\n"
                f"You owe {sup_name}: ₦{owed:,.0f}.\n"
                "Open Suppliers to record a payment."
            )
            try:
                _notify(db, owner.phone, event_type, "🧾 Supplier Payment Due", body)
                db.add(ProactiveLog(owner_phone=owner.phone, event_type=event_type, sent_at=_utcnow()))
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"[proactive] supplier_due error for {owner.phone}: {e}", flush=True)


# ── Balance reconciliation ──────────────────────────────────────────────────────

def _reconcile_balances(db):
    """Safety net for the denormalized Customer.balance: recompute the true
    BUY − PAY sum per customer in one grouped query and repair any drift
    (including NULLs on rows that predate the backfill). The Transaction event
    listeners in models.py keep the column correct in normal operation, so a
    non-zero repair count indicates a bug worth investigating — hence the log."""
    from sqlalchemy import case, func
    from models import Customer, Transaction

    sums = dict(
        db.query(
            Transaction.customer_id,
            func.sum(
                case(
                    (Transaction.type == "BUY", Transaction.amount),
                    (Transaction.type == "PAY", -Transaction.amount),
                    else_=0,
                )
            ),
        )
        .filter(
            Transaction.customer_id.isnot(None),
            Transaction.is_voided.isnot(True),
        )
        .group_by(Transaction.customer_id)
        .all()
    )

    fixed = 0
    for cid, stored in db.query(Customer.id, Customer.balance).all():
        expected = int(sums.get(cid) or 0)
        if stored is None or int(stored) != expected:
            db.query(Customer).filter(Customer.id == cid).update(
                {"balance": expected}, synchronize_session=False
            )
            fixed += 1
    if fixed:
        db.commit()
        print(f"[proactive] balance reconciliation repaired {fixed} customer(s) — "
              "investigate if this recurs", flush=True)


def _check_subscription_expiry(db):
    """Remind owners whose paid plan is about to expire (within 3 days) or is in
    its post-expiry grace window, so they renew before losing paid features."""
    from models import ProactiveLog, User
    from plans import PAID_PLANS
    from subscriptions import SUBSCRIPTION_GRACE_DAYS

    now = _utcnow()
    owners = db.query(User).filter(
        User.parent_id == None,
        User.phone != None,
        User.subscription_plan.in_(PAID_PLANS),
        User.subscription_expires_at != None,
    ).all()

    for owner in owners:
        exp = owner.subscription_expires_at
        if not exp:
            continue
        plan = owner.subscription_plan

        if now < exp:
            # Upcoming expiry — only within the 3-day lead window.
            days_left = (exp - now).days
            if (exp - now) > timedelta(days=3):
                continue
            event_type, cooldown_h = "sub_expiring", 48
            title = "Subscription expiring soon"
            body = (
                f"Your {plan} plan expires in {max(days_left, 0)} day(s) "
                f"(on {exp.strftime('%d %b %Y')}). Renew to keep staff, branches, "
                "reminders and your other paid features. Reply UPGRADE to renew."
            )
        elif now < exp + timedelta(days=SUBSCRIPTION_GRACE_DAYS):
            # In the grace window — expired but still working for a few days.
            grace_left = (exp + timedelta(days=SUBSCRIPTION_GRACE_DAYS) - now).days
            event_type, cooldown_h = "sub_grace", 24
            title = "Subscription expired — grace period"
            body = (
                f"Your {plan} plan expired on {exp.strftime('%d %b %Y')}. You have "
                f"about {max(grace_left, 0)} day(s) of grace left before it drops to "
                "Basic (staff can no longer record, extra branches/partners lock). "
                "Reply UPGRADE to renew now."
            )
        else:
            continue

        last = db.query(ProactiveLog).filter(
            ProactiveLog.owner_phone == owner.phone,
            ProactiveLog.event_type == event_type,
        ).order_by(ProactiveLog.sent_at.desc()).first()
        if last and (now - last.sent_at) < timedelta(hours=cooldown_h):
            continue

        _notify(db, owner.phone, event_type, title, body)
        db.add(ProactiveLog(owner_phone=owner.phone, event_type=event_type, sent_at=now))
        db.commit()


async def run_proactive_scheduler():
    from database import SessionLocal

    print("[proactive] Scheduler started.", flush=True)
    while True:
        await asyncio.sleep(_INTERVAL_HOURS * 3600)
        db = SessionLocal()
        try:
            print("[proactive] Running proactive checks…", flush=True)
            _check_low_stock(db)
            _check_overdue_debt(db)
            _check_inactivity(db)
            _check_reminder_automation(db)
            _check_delivery_due(db)
            _check_supplier_due(db)
            _check_subscription_expiry(db)
            _reconcile_balances(db)
            _purge_old_logs(db)
            _purge_old_notifications(db)
            global last_run_at
            last_run_at = datetime.now(timezone.utc)
            print("[proactive] Cycle complete.", flush=True)
        except Exception as e:
            print(f"[proactive] Scheduler error: {e}", flush=True)
        finally:
            db.close()
