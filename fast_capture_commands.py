"""
Fast Capture Mode — tiTi's market-hour recording engine.

During busy trading hours the owner sends transactions without confirmation.
tiTi saves each entry to FastCaptureEntry instantly and acknowledges with a
one-line receipt.  At end of day (or when the owner sends "close sales"),
tiTi presents only the unclear entries for review; high-confidence entries
are auto-approved.  Approved entries are written to the real Transaction
table exactly like a normal confirmed sale.
"""

import json
from datetime import datetime, timedelta, timezone

from constants import ACTION_FAST_CAPTURE_REVIEW
from models import (
    Customer,
    CustomerMemory,
    FastCaptureEntry,
    FastCaptureSettings,
    PendingAction,
    Transaction,
    TransactionItem,
)
from inventory_suppliers import deduct_inventory_for_items
from parser import add_transaction_items
from plans import plan_allows_feature


# ── Time helpers ──────────────────────────────────────────────────────────────
WAT = timezone(timedelta(hours=1))


def _wat_now():
    return datetime.now(WAT)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today_key():
    return _wat_now().strftime("%Y-%m-%d")


# ── Settings helpers ──────────────────────────────────────────────────────────

def get_or_create_fast_capture_settings(db, owner_phone):
    settings = db.query(FastCaptureSettings).filter(
        FastCaptureSettings.owner_phone == owner_phone
    ).first()
    if not settings:
        settings = FastCaptureSettings(owner_phone=owner_phone)
        db.add(settings)
        db.flush()
    return settings


def is_fast_mode_active(db, owner_phone):
    """Return True only when fast mode is enabled AND current WAT time is within market hours."""
    settings = db.query(FastCaptureSettings).filter(
        FastCaptureSettings.owner_phone == owner_phone
    ).first()
    if not settings or not settings.enabled:
        return False
    hour = _wat_now().hour
    return settings.market_start_hour <= hour < settings.market_end_hour


# ── Confidence scoring ────────────────────────────────────────────────────────

def _score_confidence(parsed, db, owner_phone):
    """
    Returns (confidence: str, reason: str | None).
    HIGH  — parsed cleanly, customer known or direct sale
    MEDIUM — parseable but something is uncertain
    LOW   — could not determine transaction type or amount
    """
    if not parsed or parsed.get("type") not in ("TRANSACTION",):
        return "low", "Could not understand this as a sale or payment."

    action = parsed.get("action")
    if action not in ("BUY", "PAY", "COMBINED", "SALE"):
        return "low", "Transaction type is not clear."

    if action == "SALE":
        if not parsed.get("buy_amount"):
            return "low", "Amount is missing."
        return "high", None

    name = parsed.get("name", "").lower()
    if name in ("he", "she", "they"):
        return "medium", "Customer name is unclear — pronoun used instead of name."

    amount = parsed.get("buy_amount") or parsed.get("paid_amount") or 0
    if not amount:
        return "low", "Amount is missing."

    customer = db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name == name,
    ).first() if name else None

    if not customer:
        return "medium", f"'{name.title()}' is not in your customer list yet."

    return "high", None


# ── Save one fast entry ───────────────────────────────────────────────────────

def save_fast_entry(db, owner_phone, user_id, raw_input, parsed):
    confidence, reason = _score_confidence(parsed, db, owner_phone)
    entry = FastCaptureEntry(
        owner_phone=owner_phone,
        recorded_by_id=user_id,
        raw_input=raw_input,
        parsed_type=parsed.get("action") if parsed else None,
        parsed_data=json.dumps(parsed) if parsed else None,
        confidence=confidence,
        confidence_reason=reason,
        status="pending",
        session_date=_today_key(),
    )
    db.add(entry)
    db.flush()
    return entry


def _ack_message(entry, parsed, market_end_hour=None):
    """Brief one-line acknowledgement shown in fast mode instead of a confirmation prompt.

    market_end_hour: if provided, shows ⚡ instead of ✓ and appends a closing-soon
    notice when within the final hour of the market window.
    """
    if not parsed:
        return "⚠ Entry saved — unclear, will check at close."

    action = parsed.get("action")
    name = (parsed.get("name") or "Cash sale").title()
    amount = parsed.get("buy_amount") or parsed.get("paid_amount") or parsed.get("total") or 0
    icon = "⚡" if market_end_hour is not None else "✓"

    if action == "SALE":
        product = (parsed.get("product") or "").title()
        base = f"{icon} {product} — N{amount:,} noted."
    elif action == "PAY":
        base = f"{icon} {name} paid N{amount:,} noted."
    elif action in ("BUY", "COMBINED"):
        product = (parsed.get("product") or "").title()
        product_part = f" — {product}" if product else ""
        base = f"{icon} {name}{product_part} N{amount:,} noted."
    else:
        base = f"{icon} Entry noted."

    if market_end_hour is not None:
        hour = _wat_now().hour
        if market_end_hour - 1 <= hour < market_end_hour:
            base += f"\n· Fast mode closes at {market_end_hour:02d}:00. Send 'close sales' when done."

    return base


def check_fast_mode_expiry_notice(db, owner_phone, phone, send_message):
    """Send a one-time notice when fast mode is enabled but market hours have passed.

    Called from the main webhook flow so the user is notified on their next
    message after close — not as a background push.
    """
    settings = db.query(FastCaptureSettings).filter(
        FastCaptureSettings.owner_phone == owner_phone
    ).first()
    if not settings or not settings.enabled:
        return

    hour = _wat_now().hour
    if hour < settings.market_end_hour:
        return  # still within hours, nothing to do

    today = _today_key()
    pending_count = db.query(FastCaptureEntry).filter(
        FastCaptureEntry.owner_phone == owner_phone,
        FastCaptureEntry.session_date == today,
        FastCaptureEntry.status == "pending",
    ).count()

    if pending_count > 0:
        send_message(
            phone,
            f"⚡ Fast mode closed at {settings.market_end_hour:02d}:00.\n\n"
            f"{pending_count} entr{'y' if pending_count == 1 else 'ies'} from today need your review.\n"
            "Send 'close sales' to go through them.",
        )
    else:
        send_message(
            phone,
            f"⚡ Fast mode closed at {settings.market_end_hour:02d}:00.\n"
            "Nothing to review — good day!",
        )
        # All entries handled — disable until next enable
        settings.enabled = False
        settings.updated_at = _utcnow()
        db.commit()


# ── End-of-day review ─────────────────────────────────────────────────────────

def _auto_approve_high_confidence(db, owner_phone, entries):
    """Write high-confidence entries to Transaction table immediately and mark approved."""
    approved = []
    for entry in entries:
        if entry.confidence != "high" or entry.status != "pending":
            continue
        parsed = json.loads(entry.parsed_data or "{}")
        _commit_entry(db, owner_phone, entry, parsed)
        approved.append(entry)
    return approved


def _commit_entry(db, owner_phone, entry, parsed):
    """Write one FastCaptureEntry to the real Transaction table."""
    action = parsed.get("action")
    if not action:
        entry.status = "skipped"
        return

    if action == "SALE":
        tx = Transaction(
            customer_id=None,
            type="SALE",
            amount=parsed.get("buy_amount") or parsed.get("total") or 0,
            product=parsed.get("product"),
            quantity=parsed.get("quantity"),
            unit=parsed.get("unit"),
            unit_price=parsed.get("unit_price"),
            recorded_by_id=entry.recorded_by_id,
            created_at=entry.created_at,
        )
        db.add(tx)
        db.flush()
        entry.status = "approved"
        entry.reviewed_at = _utcnow()
        return

    name = (parsed.get("name") or "").lower()
    customer = db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name == name,
    ).first()
    if not customer:
        customer = Customer(name=name, owner_phone=owner_phone)
        db.add(customer)
        db.flush()

    if action in ("BUY", "COMBINED"):
        tx = Transaction(
            customer_id=customer.id,
            type="BUY",
            amount=parsed.get("buy_amount") or parsed.get("total") or 0,
            product=parsed.get("product"),
            quantity=parsed.get("quantity"),
            unit=parsed.get("unit"),
            unit_price=parsed.get("unit_price"),
            due_date=parsed.get("due_date"),
            recorded_by_id=entry.recorded_by_id,
            created_at=entry.created_at,
        )
        db.add(tx)
        db.flush()
        if action == "COMBINED" and parsed.get("paid_amount"):
            pay_tx = Transaction(
                customer_id=customer.id,
                type="PAY",
                amount=parsed.get("paid_amount"),
                recorded_by_id=entry.recorded_by_id,
                created_at=entry.created_at,
            )
            db.add(pay_tx)

    elif action == "PAY":
        tx = Transaction(
            customer_id=customer.id,
            type="PAY",
            amount=parsed.get("paid_amount") or 0,
            recorded_by_id=entry.recorded_by_id,
            created_at=entry.created_at,
        )
        db.add(tx)

    entry.status = "approved"
    entry.reviewed_at = _utcnow()


def build_review_session(db, owner_phone, date_key=None):
    """Return (all_entries, needs_review_entries, auto_approved_count)."""
    date_key = date_key or _today_key()
    all_entries = db.query(FastCaptureEntry).filter(
        FastCaptureEntry.owner_phone == owner_phone,
        FastCaptureEntry.session_date == date_key,
        FastCaptureEntry.status == "pending",
    ).order_by(FastCaptureEntry.created_at.asc()).all()

    high = [e for e in all_entries if e.confidence == "high"]
    needs_review = [e for e in all_entries if e.confidence != "high"]
    return all_entries, needs_review, len(high)


def build_review_opening_message(total, auto_count, needs_review):
    if total == 0:
        return "No entries to review today."
    lines = [f"End of day review — {total} entries today."]
    if auto_count:
        lines.append(f"tiTi handled {auto_count} automatically.")
    if needs_review:
        lines.append(f"{len(needs_review)} need your check:\n")
        for i, entry in enumerate(needs_review, start=1):
            parsed = json.loads(entry.parsed_data or "{}")
            name = (parsed.get("name") or "Cash sale").title()
            amount = parsed.get("buy_amount") or parsed.get("paid_amount") or 0
            product = (parsed.get("product") or "").title()
            product_part = f" — {product}" if product else ""
            reason = entry.confidence_reason or "Needs review"
            lines.append(
                f"{i}. {name}{product_part} N{amount:,}\n"
                f"   ❓ {reason}"
            )
        lines.append(
            "\nReply:\n"
            "all ok — approve all\n"
            "[number] ok — approve one (e.g. 1 ok)\n"
            "[number] [correction] — correct one (e.g. 2 rice)\n"
            "skip [number] — skip one"
        )
    else:
        lines.append("All entries were clear — nothing to review.")
    return "\n".join(lines)


# ── Pending review state handler ─────────────────────────────────────────────

def handle_fast_capture_review_pending(
    db, phone, text, pending, owner_phone, send_message,
):
    normalized = text.strip().lower()
    payload = json.loads(pending.payload_json or "{}")
    entry_ids = payload.get("entry_ids", [])
    entries = db.query(FastCaptureEntry).filter(
        FastCaptureEntry.id.in_(entry_ids),
        FastCaptureEntry.status == "pending",
    ).order_by(FastCaptureEntry.created_at.asc()).all()

    if not entries:
        db.delete(pending)
        db.commit()
        send_message(phone, "All entries reviewed. Good work today!")
        return {"status": "fast_capture_review_complete"}

    if normalized == "all ok":
        try:
            for entry in entries:
                parsed = json.loads(entry.parsed_data or "{}")
                _commit_entry(db, owner_phone, entry, parsed)
            db.delete(pending)
            db.commit()
        except Exception:
            db.rollback()
            send_message(phone, "Something went wrong. Please try again.")
            return {"status": "fast_capture_approve_error"}
        send_message(phone, f"Done. {len(entries)} entries approved and saved.")
        return {"status": "fast_capture_all_approved"}

    # "1 ok", "skip 2", "2 rice" etc.
    parts = normalized.split(None, 1)
    number_part = parts[0].lstrip("skip").strip() if normalized.startswith("skip") else parts[0]
    if not number_part.isdigit():
        send_message(phone, "Reply 'all ok', '[number] ok', 'skip [number]', or '[number] [correction]'.")
        return {"status": "fast_capture_review_invalid"}

    idx = int(number_part) - 1
    if idx < 0 or idx >= len(entries):
        send_message(phone, f"Send a number between 1 and {len(entries)}.")
        return {"status": "fast_capture_review_out_of_range"}

    entry = entries[idx]

    if normalized.startswith("skip") or normalized == f"{idx + 1} skip":
        entry.status = "skipped"
        entry.reviewed_at = _utcnow()
        db.commit()
        remaining = [e for e in entries if e.status == "pending"]
        if not remaining:
            db.delete(pending)
            db.commit()
            send_message(phone, "All entries reviewed.")
            return {"status": "fast_capture_review_complete"}
        send_message(phone, f"Skipped. {len(remaining)} remaining.")
        return {"status": "fast_capture_entry_skipped"}

    if len(parts) > 1 and parts[1] != "ok":
        entry.correction_input = parts[1].strip()
        parsed = json.loads(entry.parsed_data or "{}")
        parsed["product"] = parts[1].strip()
        entry.parsed_data = json.dumps(parsed)
        entry.confidence = "high"
        entry.confidence_reason = None

    parsed = json.loads(entry.parsed_data or "{}")
    _commit_entry(db, owner_phone, entry, parsed)
    db.commit()

    remaining = [e for e in entries if e.status == "pending"]
    if not remaining:
        db.delete(pending)
        db.commit()
        send_message(phone, "All entries reviewed and saved.")
        return {"status": "fast_capture_review_complete"}

    send_message(phone, f"Saved. {len(remaining)} remaining.")
    return {"status": "fast_capture_entry_approved"}


# ── Main command handler ──────────────────────────────────────────────────────

def handle_fast_capture_command(db, phone, parsed, user, business_owner_phone, send_message):
    command_type = parsed.get("type")

    if command_type == "FAST_MODE_ON":
        settings = get_or_create_fast_capture_settings(db, business_owner_phone)
        hours = parsed.get("hours", {})
        if hours.get("start") is not None:
            settings.market_start_hour = hours["start"]
        if hours.get("end") is not None:
            settings.market_end_hour = hours["end"]
        settings.enabled = True
        settings.updated_at = _utcnow()
        db.commit()
        start_h = settings.market_start_hour
        end_h = settings.market_end_hour
        send_message(
            phone,
            f"Fast mode ON.\n"
            f"Active hours: {start_h}:00 – {end_h}:00 WAT.\n\n"
            "During these hours tiTi records without asking you to confirm.\n"
            "Send 'close sales' when you're done for the day."
        )
        return {"status": "fast_mode_enabled"}

    if command_type == "FAST_MODE_OFF":
        settings = get_or_create_fast_capture_settings(db, business_owner_phone)
        settings.enabled = False
        settings.updated_at = _utcnow()
        db.commit()
        send_message(phone, "Fast mode OFF. Transactions will ask for confirmation again.")
        return {"status": "fast_mode_disabled"}

    if command_type == "FAST_CAPTURE_STATUS":
        settings = db.query(FastCaptureSettings).filter(
            FastCaptureSettings.owner_phone == business_owner_phone
        ).first()
        if not settings or not settings.enabled:
            send_message(
                phone,
                "Fast mode is OFF.\n\n"
                "Turn it on:\nfast mode on\n"
                "Set hours: fast mode on 8am to 6pm"
            )
        else:
            hour = _wat_now().hour
            active_now = settings.market_start_hour <= hour < settings.market_end_hour
            status = "ACTIVE now" if active_now else "ON but outside market hours"
            send_message(
                phone,
                f"Fast mode: {status}\n"
                f"Hours: {settings.market_start_hour}:00 – {settings.market_end_hour}:00 WAT\n\n"
                "Send 'close sales' to review today's entries."
            )
        return {"status": "fast_capture_status"}

    if command_type == "CLOSE_SALES":
        date_key = _today_key()
        all_entries, needs_review, auto_count = build_review_session(db, business_owner_phone, date_key)

        if not all_entries:
            send_message(phone, "No entries to review today.")
            return {"status": "close_sales_empty"}

        # Auto-approve high-confidence entries + queue the unclear ones
        high_entries = [e for e in all_entries if e.confidence == "high"]
        try:
            for entry in high_entries:
                parsed_data = json.loads(entry.parsed_data or "{}")
                _commit_entry(db, business_owner_phone, entry, parsed_data)
            db.flush()

            if not needs_review:
                db.commit()
                send_message(
                    phone,
                    f"End of day done.\n"
                    f"{len(high_entries)} entries saved automatically.\n"
                    "Nothing unclear — great day!"
                )
                return {"status": "close_sales_all_clean"}

            db.query(PendingAction).filter(PendingAction.phone == phone).delete()
            db.add(PendingAction(
                phone=phone,
                action=ACTION_FAST_CAPTURE_REVIEW,
                customer_name="",
                last_customer="",
                payload_json=json.dumps({"entry_ids": [e.id for e in needs_review]}),
            ))
            db.commit()
        except Exception:
            db.rollback()
            send_message(phone, "Something went wrong during end-of-day save. Please try again.")
            return {"status": "close_sales_error"}

        send_message(phone, build_review_opening_message(
            len(all_entries), auto_count, needs_review
        ))
        return {"status": "close_sales_review_started"}

    return None
