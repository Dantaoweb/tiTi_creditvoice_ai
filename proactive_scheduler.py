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

    if send_whatsapp:
        try:
            send_whatsapp_message(owner_phone, f"*{title}*\n\n{body}")
        except Exception as e:
            print(f"[proactive] WhatsApp send error for {owner_phone}: {e}", flush=True)


# ── Low-stock check ─────────────────────────────────────────────────────────────

def _check_low_stock(db):
    from models import InventoryItem, ProactiveLog, User

    owners = db.query(User).filter(
        User.role == "user",
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
        User.role == "user",
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
        User.role == "user",
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
            _purge_old_logs(db)
        except Exception as e:
            print(f"[proactive] Scheduler error: {e}", flush=True)
        finally:
            db.close()
