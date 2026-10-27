"""
Appointments — bookings with a time, for salons, barbers, clinics, vets,
mechanics, tailors and professionals.

- Book: customer, service(s) from the price list, date + time (Nigeria time,
  as people say it), how long, with which staff, a note.
- Two bookings for the same staff that overlap are allowed, with a warning.
- Booked → Arrived → Done (becomes an ordinary sale with a receipt; unpaid
  part is debt as usual), or No-show / Cancelled. No-shows are counted per
  customer.
- Reminders: the customer gets a WhatsApp the evening before; the owner gets
  the day's list each morning (proactive_scheduler).
"""
import json
from datetime import datetime, timedelta

from app_settings import LAGOS
from models import Appointment, Customer, User

STATUS_LABELS = {"requested": "Asked to book", "declined": "Declined", "booked": "Booked", "arrived": "Arrived", "done": "Done",
                 "no_show": "No-show", "cancelled": "Cancelled"}
SERVICE_GROUPS = ("service", "clinic", "professional")


class AppointmentError(ValueError):
    pass


def lagos_now():
    return datetime.now(LAGOS).replace(tzinfo=None)


def parse_start(date_str, time_str):
    try:
        return datetime.strptime(f"{(date_str or '')[:10]} {(time_str or '')[:5]}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise AppointmentError("Pick the date and time.")


def _services(db, owner_phone, services):
    from models import InventoryItem
    out = []
    for s in services or []:
        item = None
        if s.get("inventory_item_id"):
            item = db.query(InventoryItem).filter(InventoryItem.id == s["inventory_item_id"],
                                                  InventoryItem.owner_phone == owner_phone).first()
        name = (s.get("name") or (item.name if item else "") or "").strip()
        if not name:
            continue
        try:
            price = int(s.get("price")) if s.get("price") not in (None, "") else int(item.selling_price or 0) if item else 0
        except (TypeError, ValueError):
            raise AppointmentError("Prices must be numbers.")
        out.append({"inventory_item_id": item.id if item else None, "name": name[:120], "price": max(0, price)})
    return out


def _customer(db, owner_phone, customer_id=None, name=None, phone=None):
    from web_pos import resolve_sale_customer
    cid = resolve_sale_customer(db, owner_phone, customer_id, name, phone)
    if not cid:
        raise AppointmentError("Choose who the appointment is for.")
    return cid


def clashes(db, owner_phone, start, duration, staff_user_id=None, staff_name=None, exclude_id=None):
    """Bookings for the same staff that overlap this time."""
    if not (staff_user_id or staff_name):
        return []
    end = start + timedelta(minutes=duration)
    q = db.query(Appointment).filter(Appointment.owner_phone == owner_phone,
                                     Appointment.status.in_(("booked", "arrived")),
                                     Appointment.start_at < end,
                                     Appointment.start_at > start - timedelta(hours=12))
    if exclude_id:
        q = q.filter(Appointment.id != exclude_id)
    out = []
    for a in q.all():
        same = (staff_user_id and a.staff_user_id == staff_user_id) or \
               (staff_name and (a.staff_name or "").lower() == staff_name.strip().lower())
        if same and a.start_at + timedelta(minutes=a.duration_min or 30) > start:
            out.append(a)
    return out


def book(db, owner_phone, user_id, *, start_at, duration_min=30, services=None, customer_id=None,
         customer_name=None, customer_phone=None, staff_user_id=None, staff_name=None, note=None,
         branch_id=None, appt=None):
    try:
        duration_min = int(duration_min or 30)
    except (TypeError, ValueError):
        raise AppointmentError("Enter how long it takes in minutes.")
    if not 5 <= duration_min <= 24 * 60:
        raise AppointmentError("How long must be between 5 minutes and a day.")
    staff_name = (staff_name or "").strip()[:80] or None
    if staff_user_id:
        u = db.query(User).filter(User.id == staff_user_id).first()
        staff_name = (u.name or "").title() if u else staff_name
    a = appt or Appointment(owner_phone=owner_phone, branch_id=branch_id, created_by_id=user_id, status="booked")
    a.customer_id = _customer(db, owner_phone, customer_id, customer_name, customer_phone)
    if appt is not None and a.start_at != start_at:
        a.reminded_at = None                     # moved: remind again
    a.start_at, a.duration_min = start_at, duration_min
    a.services_json = json.dumps(_services(db, owner_phone, services))
    a.staff_user_id, a.staff_name = staff_user_id or None, staff_name
    a.note = (note or "").strip()[:300] or None
    if appt is None:
        db.add(a)
    db.flush()
    return a, clashes(db, owner_phone, start_at, duration_min, a.staff_user_id, a.staff_name, exclude_id=a.id)


def set_status(db, a, status):
    if status not in ("booked", "arrived", "no_show", "cancelled"):
        raise AppointmentError("Unknown status.")
    if a.status == "done":
        raise AppointmentError("This appointment is done — its sale is recorded.")
    if a.status in ("requested", "declined") and status != "cancelled":
        raise AppointmentError("Confirm or decline the booking request first.")
    a.status = status
    db.flush()


def complete(db, a, user_id, paid, services=None):
    """Done: record it as a sale (services and prices), with what was paid."""
    from web_pos import save_pos_sale
    if a.status == "done":
        raise AppointmentError("Already done.")
    if a.status in ("cancelled", "declined"):
        raise AppointmentError("This appointment was cancelled.")
    if a.status == "requested":
        raise AppointmentError("Confirm the booking request first.")
    svc = _services(db, a.owner_phone, services) if services is not None else json.loads(a.services_json or "[]")
    if not svc:
        raise AppointmentError("Add the service(s) done and their price.")
    items = [{"inventory_item_id": s["inventory_item_id"], "name": s["name"], "qty": 1, "unit": None,
              "unit_price": s["price"]} for s in svc]
    try:
        paid = int(paid or 0)
    except (TypeError, ValueError):
        raise AppointmentError("Enter what was paid.")
    result = save_pos_sale(db, a.owner_phone, user_id, a.customer_id, items, paid, branch_id=a.branch_id,
                           commit=False, label="Appointment")
    a.services_json = json.dumps(svc)
    a.status = "done"
    a.sale_tx_id = result["receipt_id"]
    db.flush()
    return result


def no_shows(db, customer_id):
    return db.query(Appointment).filter(Appointment.customer_id == customer_id,
                                        Appointment.status == "no_show").count()


def row(db, a):
    cust = db.query(Customer).filter(Customer.id == a.customer_id).first()
    svc = json.loads(a.services_json or "[]")
    return {
        "id": a.id, "date": a.start_at.date().isoformat(), "time": a.start_at.strftime("%H:%M"),
        "end": (a.start_at + timedelta(minutes=a.duration_min or 30)).strftime("%H:%M"),
        "duration_min": a.duration_min, "status": a.status, "status_label": STATUS_LABELS.get(a.status, a.status),
        "customer": ({"id": cust.id, "name": (cust.name or "").title(), "phone": cust.customer_phone} if cust
                     else {"id": None, "name": a.request_name, "phone": a.request_phone} if a.request_name else None),
        "booked_via": a.booked_via,
        "no_shows": no_shows(db, a.customer_id) if cust else 0,
        "services": svc, "total": sum(s["price"] for s in svc),
        "staff_user_id": a.staff_user_id, "staff_name": a.staff_name, "note": a.note,
        "sale_tx_id": a.sale_tx_id, "reminded": a.reminded_at is not None,
    }


def day_list(db, owner_phone, day, branch_id=None, staff_user_id=None):
    start = datetime(day.year, day.month, day.day)
    q = db.query(Appointment).filter(Appointment.owner_phone == owner_phone,
                                     Appointment.start_at >= start, Appointment.start_at < start + timedelta(days=1))
    if branch_id is not None:
        q = q.filter(Appointment.branch_id == branch_id)
    if staff_user_id is not None:
        q = q.filter(Appointment.staff_user_id == staff_user_id)
    return [row(db, a) for a in q.order_by(Appointment.start_at).all()]


def reminder_text(business_name, a, cust):
    svc = ", ".join(s["name"] for s in json.loads(a.services_json or "[]")) or "your appointment"
    when = a.start_at.strftime("%I:%M %p").lstrip("0")
    who = f" with {a.staff_name}" if a.staff_name else ""
    return (f"Hello {(cust.name or 'there').title()}, a reminder from *{business_name}*: "
            f"{svc}{who} tomorrow at *{when}*.\n\nReply if you need to change it. See you!")


def due_reminders(db, now=None):
    """Appointments tomorrow (Lagos), not yet reminded — sent from 5pm the day before."""
    now = now or lagos_now()
    if now.hour < 17:
        return []
    tomorrow = (now + timedelta(days=1)).date()
    start = datetime(tomorrow.year, tomorrow.month, tomorrow.day)
    return db.query(Appointment).filter(Appointment.status == "booked", Appointment.reminded_at.is_(None),
                                        Appointment.start_at >= start,
                                        Appointment.start_at < start + timedelta(days=1)).all()
