"""
Repeat invoices — the same bill to the same customer on a schedule (rent,
service charge, a weekly water supply).

- Made from an existing invoice: Make it repeat → how often (every week /
  month / 3 months / year), the first date, and when to stop (never, after so
  many more, or on a date).
- On each date (Nigeria time) the daily check makes a new, ordinary invoice:
  new INV number, same items and prices, due the same number of days later as
  the first one. "Send it for me" sends it on WhatsApp with the pay link;
  "Let me check first" leaves it for the owner, who is told it's ready.
- Pause / resume / stop at any time. Missed days (server down) make one
  invoice, not a pile.
- Not for schools — opening a term already bills every pupil.
"""
import calendar
import json
from datetime import datetime, timedelta

from models import Customer, Invoice, RecurringInvoice

EVERY = {"week": "every week", "month": "every month", "quarter": "every 3 months", "year": "every year"}
_MONTHS = {"month": 1, "quarter": 3, "year": 12}


class RepeatError(ValueError):
    pass


def lagos_today():
    from appointments import lagos_now
    return lagos_now().date()


def _midnight(d):
    return datetime(d.year, d.month, d.day)


def step(d, every, anchor_day=None):
    """The date one period after d. Monthly repeats keep their day of the
    month (the 31st falls on the 30th / 28th in short months)."""
    if every == "week":
        return d + timedelta(days=7)
    m = d.month - 1 + _MONTHS[every]
    y, m = d.year + m // 12, m % 12 + 1
    return d.replace(year=y, month=m, day=min(anchor_day or d.day, calendar.monthrange(y, m)[1]))


def _parse_date(s, what):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise RepeatError(f"Pick the {what}.")


def _clean(every, start, stop_after, stop_on):
    if every not in EVERY:
        raise RepeatError("Choose how often: every week, month, 3 months or year.")
    start = _parse_date(start, "first date")
    if not start:
        raise RepeatError("Pick the first date.")
    if start < lagos_today():
        raise RepeatError("The first date can't be in the past.")
    if stop_after in ("", 0, "0"):
        stop_after = None
    if stop_after is not None:
        try:
            stop_after = int(stop_after)
        except (TypeError, ValueError):
            raise RepeatError("Enter how many times as a number.")
        if not 1 <= stop_after <= 500:
            raise RepeatError("How many times must be between 1 and 500.")
    stop_on = _parse_date(stop_on, "end date")
    if stop_on and stop_on < start:
        raise RepeatError("The end date must be after the first date.")
    return start, stop_after, stop_on


def _lines(items):
    from invoices import InvoiceError, clean_invoice_items
    try:
        lines, _total = clean_invoice_items(items)
    except InvoiceError as e:
        raise RepeatError(str(e))
    return [{k: l[k] for k in ("inventory_item_id", "name", "qty", "unit", "sold_unit", "fraction", "unit_price")}
            for l in lines]


def make_repeat(db, inv, user_id, *, every, start, stop_after=None, stop_on=None, auto_send=True):
    """Set an invoice to repeat. The invoice itself stays as it is."""
    from invoices import invoice_lines
    if inv.is_quote:
        raise RepeatError("A quotation can't repeat — make it an invoice first.")
    if inv.cancelled_at:
        raise RepeatError("This invoice was cancelled.")
    if db.query(RecurringInvoice).filter(RecurringInvoice.source_invoice_id == inv.id,
                                         RecurringInvoice.status != "ended").first():
        raise RepeatError("This invoice already repeats — change it under Invoices → Repeating.")
    start, stop_after, stop_on = _clean(every, start, stop_after, stop_on)
    due_days = None
    if inv.due_date and inv.created_at:
        due_days = max(0, (inv.due_date.date() - inv.created_at.date()).days)
    r = RecurringInvoice(
        owner_phone=inv.owner_phone, branch_id=inv.branch_id, customer_id=inv.customer_id,
        items_json=json.dumps(_lines(invoice_lines(db, inv))), discount=inv.discount, note=inv.note,
        deposit_percent=inv.deposit_percent, due_days=due_days, every=every, anchor_day=start.day,
        next_date=_midnight(start), stop_after=stop_after, stop_on=_midnight(stop_on) if stop_on else None,
        made_count=0, auto_send=bool(auto_send), status="active", source_invoice_id=inv.id,
        created_by_id=user_id)
    db.add(r)
    db.flush()
    return r


def update_repeat(db, r, *, every, next_date, stop_after=None, stop_on=None, auto_send=True, items=None,
                  discount=None):
    if r.status == "ended":
        raise RepeatError("This repeat has ended.")
    start, stop_after, stop_on = _clean(every, next_date, stop_after, stop_on)
    if items is not None:
        r.items_json = json.dumps(_lines(items))
    if discount is not None:
        r.discount = max(0, int(discount or 0)) or None
    r.every, r.anchor_day, r.next_date = every, start.day, _midnight(start)
    r.stop_after, r.stop_on = stop_after, (_midnight(stop_on) if stop_on else None)
    r.auto_send = bool(auto_send)
    db.flush()
    return r


def set_status(db, r, action):
    if r.status == "ended":
        raise RepeatError("This repeat has ended.")
    if action == "pause":
        r.status = "paused"
    elif action == "resume":
        r.status = "active"
        today = lagos_today()
        while r.next_date.date() < today:           # skip the dates missed while paused
            r.next_date = _midnight(step(r.next_date.date(), r.every, r.anchor_day))
        _maybe_end(r)
    elif action == "stop":
        r.status = "ended"
    else:
        raise RepeatError("Unknown action.")
    db.flush()


def _maybe_end(r):
    if (r.stop_after and (r.made_count or 0) >= r.stop_after) or (r.stop_on and r.next_date > r.stop_on):
        r.status = "ended"


def make_one(db, r, today=None):
    """Make (and maybe send) the invoice that is due. Returns (invoice, sent)."""
    from invoices import create_invoice, format_invoice_doc_text, invoice_document
    today = today or lagos_today()
    due = _midnight(today + timedelta(days=r.due_days)).replace(hour=12) if r.due_days is not None else None
    inv = create_invoice(db, r.owner_phone, r.created_by_id, r.customer_id, json.loads(r.items_json or "[]"),
                         due_date=due, note=r.note, branch_id=r.branch_id, discount=r.discount or 0,
                         deposit_percent=r.deposit_percent)
    inv.recurring_id = r.id
    r.made_count = (r.made_count or 0) + 1
    r.last_invoice_id = inv.id
    while r.next_date.date() <= today:              # missed days make one invoice, not a pile
        r.next_date = _midnight(step(r.next_date.date(), r.every, r.anchor_day))
    _maybe_end(r)
    db.commit()                                     # saved before sending: a failed send never makes it twice
    sent = False
    if r.auto_send:
        doc = invoice_document(db, inv)
        phone = (doc.get("customer") or {}).get("phone")
        if phone:
            from whatsapp_client import send_whatsapp_message
            try:
                sent = send_whatsapp_message(phone, format_invoice_doc_text(doc)) is not False
            except Exception as e:
                print(f"[repeat invoice] send failed {inv.id}: {e}", flush=True)
            if sent:
                inv.sent_at = datetime.utcnow()
                db.commit()
    return inv, sent


def due_repeats(db, today=None):
    today = today or lagos_today()
    return db.query(RecurringInvoice).filter(RecurringInvoice.status == "active",
                                             RecurringInvoice.next_date <= _midnight(today)).all()


def summary_text(r):
    return EVERY.get(r.every, r.every)


def row(db, r):
    from invoices import format_invoice_number
    items = json.loads(r.items_json or "[]")
    lines_total = sum(int(round(float(i["qty"]) * int(i["unit_price"]))) for i in items)
    cust = db.query(Customer).filter(Customer.id == r.customer_id).first()
    last = db.query(Invoice).filter(Invoice.id == r.last_invoice_id).first() if r.last_invoice_id else None
    return {
        "id": r.id, "customer": (cust.name or "").title() if cust else "", "customer_phone": cust.customer_phone if cust else None,
        "items": items, "discount": r.discount or 0, "total": max(0, lines_total - (r.discount or 0)),
        "every": r.every, "every_label": summary_text(r), "next_date": r.next_date.date().isoformat() if r.next_date else None,
        "stop_after": r.stop_after, "stop_on": r.stop_on.date().isoformat() if r.stop_on else None,
        "made_count": r.made_count or 0, "auto_send": bool(r.auto_send), "status": r.status,
        "source_invoice_id": r.source_invoice_id,
        "last_invoice": {"id": last.id, "ref": format_invoice_number(last.number)} if last else None,
    }


def repeat_for_invoice(db, inv):
    """For an invoice's page: the repeat it was made by, or that it starts."""
    r = None
    if inv.recurring_id:
        r = db.query(RecurringInvoice).filter(RecurringInvoice.id == inv.recurring_id).first()
    if not r:
        r = (db.query(RecurringInvoice).filter(RecurringInvoice.source_invoice_id == inv.id)
             .order_by(RecurringInvoice.id.desc()).first())
    if not r:
        return None
    return {"id": r.id, "every_label": summary_text(r), "status": r.status,
            "next_date": r.next_date.date().isoformat() if r.next_date else None,
            "made_by_repeat": inv.recurring_id == r.id}


def list_repeats(db, owner_phone, branch_id=None):
    q = db.query(RecurringInvoice).filter(RecurringInvoice.owner_phone == owner_phone)
    if branch_id is not None:
        q = q.filter(RecurringInvoice.branch_id == branch_id)
    order = {"active": 0, "paused": 1, "ended": 2}
    return sorted((row(db, r) for r in q.all()), key=lambda x: (order.get(x["status"], 3), x["next_date"] or ""))
