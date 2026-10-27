"""
The customer booking link — one public link per business (…/app/book/<token>).

The customer picks service(s), a day and a free time, and leaves a name and
WhatsApp number. It arrives in Appointments as a *request*; the owner taps
Confirm (customer gets "You're booked") or Decline (with a reason). If the
owner chose "book straight away" in Settings it's booked at once.

Off until the owner switches it on (Settings → Appointments). Free times come
from the opening hours set there; a time is free while fewer bookings overlap
it than there are people to do the work (staff + owner).
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta

from app_settings import business_setting
from appointments import AppointmentError, lagos_now
from models import Appointment, Customer, InventoryItem, User

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ACTIVE = ("requested", "booked", "arrived")
MAX_OPEN_REQUESTS = 3                       # per phone, per business — stops junk


class BookingLinkError(ValueError):
    pass


def _sig(body):
    secret = os.getenv("WEB_SECRET_KEY", "cv-web-secret-change-in-production").encode()
    return hmac.new(secret, f"book:{body}".encode(), hashlib.sha256).hexdigest()[:12]


def make_token(owner):
    return f"b{owner.id}-{_sig(f'b{owner.id}')}"


def link_for(owner):
    from payment_links import base_url
    return f"{base_url()}/app/book/{make_token(owner)}"


def owner_for(db, token):
    """The business behind a genuine, switched-on link."""
    try:
        body, sig = (token or "").rsplit("-", 1)
    except ValueError:
        body, sig = "", ""
    if not body.startswith("b") or not hmac.compare_digest(sig, _sig(body)):
        raise BookingLinkError("This booking link isn't valid.")
    owner = db.query(User).filter(User.id == body[1:], User.parent_id.is_(None)).first()
    if not owner:
        raise BookingLinkError("This booking link isn't valid.")
    if not business_setting(db, owner.phone, "booking_link"):
        raise BookingLinkError("This business isn't taking bookings online right now.")
    return owner


def _services(db, owner_phone):
    """The price list customers choose from: services (no stock count) if the
    business has any, else everything for sale."""
    items = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone,
                                           InventoryItem.is_available.isnot(False),
                                           InventoryItem.selling_price > 0).order_by(InventoryItem.name).all()
    svc = [i for i in items if i.quantity is None or (i.category or "").lower() == "service"]
    return (svc or items)[:200]


def _people(db, owner):
    staff = db.query(User).filter(User.parent_id == owner.id).all()
    return [{"id": u.id, "name": (u.name or "").title()} for u in staff if u.name] + \
           [{"id": owner.id, "name": (owner.name or "Owner").title()}]


def _hours(db, owner_phone, day):
    h = (business_setting(db, owner_phone, "booking_hours") or {}).get(DAYS[day.weekday()])
    if not h:
        return None
    o, c = (datetime.strptime(t, "%H:%M").time() for t in h)
    return datetime.combine(day, o), datetime.combine(day, c)


def free_times(db, owner, day, staff_user_id=None, now=None):
    """Start times ("09:30") still free on that day."""
    now = now or lagos_now()
    hours = _hours(db, owner.phone, day)
    if not hours:
        return []
    step = int(business_setting(db, owner.phone, "booking_slot_min") or 30)
    capacity = 1 if staff_user_id else len(_people(db, owner))
    taken = db.query(Appointment).filter(Appointment.owner_phone == owner.phone,
                                         Appointment.status.in_(ACTIVE),
                                         Appointment.start_at >= hours[0] - timedelta(hours=12),
                                         Appointment.start_at < hours[1]).all()
    if staff_user_id:
        taken = [a for a in taken if a.staff_user_id == staff_user_id]
    out, t = [], hours[0]
    while t + timedelta(minutes=step) <= hours[1]:
        end = t + timedelta(minutes=step)
        busy = sum(1 for a in taken if a.start_at < end and a.start_at + timedelta(minutes=a.duration_min or 30) > t)
        if t > now + timedelta(minutes=30) and busy < capacity:
            out.append(t.strftime("%H:%M"))
        t = end
    return out


def page(db, token):
    """What the public booking page shows."""
    from invoices import _business_header
    owner = owner_for(db, token)
    head = _business_header(db, owner.phone, None, kind="invoice")
    ahead = int(business_setting(db, owner.phone, "booking_days_ahead") or 14)
    today = lagos_now().date()
    days = []
    for n in range(ahead + 1):
        d = today + timedelta(days=n)
        days.append({"date": d.isoformat(), "open": bool(_hours(db, owner.phone, d))})
    return {
        "biz_name": head.get("biz_name"), "biz_logo": head.get("biz_logo"), "biz_phone": head.get("biz_phone"),
        "services": [{"id": i.id, "name": i.name, "price": int(i.selling_price or 0)} for i in _services(db, owner.phone)],
        "days": days,
        "staff": _people(db, owner) if business_setting(db, owner.phone, "booking_pick_staff") else [],
        "confirm": not business_setting(db, owner.phone, "booking_auto_confirm"),
    }


def request(db, token, *, date, time, service_ids, name, phone, staff_user_id=None, note=None):
    """The customer asks for a time. Returns the appointment (requested, or
    booked if the owner books straight away)."""
    from phone_utils import normalize_phone
    owner = owner_for(db, token)
    name = " ".join((name or "").split())[:80]
    phone = normalize_phone(phone or "")
    if len(name) < 2:
        raise BookingLinkError("Enter your name.")
    if not phone or not 10 <= len(phone) <= 15:
        raise BookingLinkError("Enter your WhatsApp number.")
    try:
        start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        raise BookingLinkError("Pick a day and a time.")
    ahead = int(business_setting(db, owner.phone, "booking_days_ahead") or 14)
    if start.date() > lagos_now().date() + timedelta(days=ahead):
        raise BookingLinkError("That day is too far ahead — pick a nearer day.")
    picked = {i.id: i for i in _services(db, owner.phone)}
    chosen = [picked[s] for s in dict.fromkeys(service_ids or []) if s in picked]
    if not chosen:
        raise BookingLinkError("Pick what you'd like done.")
    staff = None
    if staff_user_id and business_setting(db, owner.phone, "booking_pick_staff"):
        staff = next((p for p in _people(db, owner) if p["id"] == staff_user_id), None)
    if start.strftime("%H:%M") not in free_times(db, owner, start.date(), staff["id"] if staff else None):
        raise BookingLinkError("Sorry, that time was just taken — pick another.")
    open_requests = db.query(Appointment).filter(Appointment.owner_phone == owner.phone,
                                                 Appointment.request_phone == phone,
                                                 Appointment.status == "requested").count()
    if open_requests >= MAX_OPEN_REQUESTS:
        raise BookingLinkError("You already have requests waiting — the business will reply soon.")
    a = Appointment(owner_phone=owner.phone, start_at=start,
                    duration_min=int(business_setting(db, owner.phone, "booking_slot_min") or 30),
                    services_json=json.dumps([{"inventory_item_id": i.id, "name": i.name,
                                               "price": int(i.selling_price or 0)} for i in chosen]),
                    staff_user_id=staff["id"] if staff else None, staff_name=staff["name"] if staff else None,
                    note=" ".join((note or "").split())[:300] or None, status="requested",
                    booked_via="link", request_name=name.title(), request_phone=phone)
    db.add(a)
    db.flush()
    if business_setting(db, owner.phone, "booking_auto_confirm"):
        confirm(db, a)
    return a


def _customer_for(db, a):
    """The customer record for a link booking: same WhatsApp number, else same
    name, else a new customer."""
    from web_pos import resolve_sale_customer
    tail = (a.request_phone or "")[-10:]
    found = None
    if tail:
        found = next((c for c in db.query(Customer).filter(Customer.owner_phone == a.owner_phone,
                                                         Customer.customer_phone.like(f"%{tail}")).all()), None)
    if found:
        return found.id
    return resolve_sale_customer(db, a.owner_phone, None, a.request_name, a.request_phone)


def confirmed_text(business_name, a):
    svc = ", ".join(s["name"] for s in json.loads(a.services_json or "[]")) or "your appointment"
    when = a.start_at.strftime("%A %d %B at %I:%M %p").replace(" 0", " ")
    who = f" with {a.staff_name}" if a.staff_name else ""
    return (f"Hello {a.request_name or 'there'}, you're booked at *{business_name}*: "
            f"{svc}{who} on *{when}*.\n\nWe'll remind you the evening before. Reply here if you need to change it.")


def declined_text(business_name, a, reason=None):
    when = a.start_at.strftime("%A %d %B at %I:%M %p").replace(" 0", " ")
    why = f"\n\n{reason}" if reason else ""
    return (f"Hello {a.request_name or 'there'}, sorry — *{business_name}* can't take your booking for "
            f"{when}.{why}\n\nYou can pick another time on the booking link.")


def confirm(db, a):
    if a.status != "requested":
        raise AppointmentError("This isn't a booking request.")
    a.customer_id = a.customer_id or _customer_for(db, a)
    a.status = "booked"
    db.flush()


def decline(db, a):
    if a.status != "requested":
        raise AppointmentError("This isn't a booking request.")
    a.status = "declined"
    db.flush()


def requests(db, owner_phone, branch_id=None):
    q = db.query(Appointment).filter(Appointment.owner_phone == owner_phone, Appointment.status == "requested")
    if branch_id is not None:
        q = q.filter(Appointment.branch_id == branch_id)
    return q.order_by(Appointment.start_at).all()
