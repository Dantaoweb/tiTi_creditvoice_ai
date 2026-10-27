"""
Appointments on the web (appointments.py). Anyone who records sales can book,
move and mark appointments; "Done" records the sale like the till.
Branch staff see their branch's appointments.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Appointment, User
from web_auth import require_web_auth
from web_common import (
    _add_notification, _require_can_record, _scoped_read, _send_web_receipt, _session_owner_phone,
)


class ServiceIn(BaseModel):
    inventory_item_id: Optional[int] = None
    name: Optional[str] = Field(default=None, max_length=120)
    price: Optional[int] = None


class AppointmentRequest(BaseModel):
    date: str = Field(max_length=10)                    # YYYY-MM-DD
    time: str = Field(max_length=5)                     # HH:MM (Nigeria time)
    duration_min: int = 30
    services: List[ServiceIn] = Field(default_factory=list, max_length=20)
    customer_id: Optional[int] = None
    customer_name: Optional[str] = Field(default=None, max_length=120)
    customer_phone: Optional[str] = Field(default=None, max_length=20)
    staff_user_id: Optional[str] = Field(default=None, max_length=64)
    staff_name: Optional[str] = Field(default=None, max_length=80)
    note: Optional[str] = Field(default=None, max_length=300)


class StatusRequest(BaseModel):
    status: str = Field(max_length=20)


class DeclineRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


class PublicBookRequest(BaseModel):
    date: str = Field(max_length=10)
    time: str = Field(max_length=5)
    service_ids: List[int] = Field(default_factory=list, max_length=20)
    name: str = Field(max_length=80)
    phone: str = Field(max_length=20)
    staff_user_id: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=300)


class DoneRequest(BaseModel):
    paid: int = 0
    services: Optional[List[ServiceIn]] = None


def register_appointment_routes(app):
    from appointments import (
        AppointmentError, book, complete, day_list, lagos_now, parse_start, row, set_status,
    )

    def _load(db, session, appt_id):
        a = db.query(Appointment).filter(Appointment.id == appt_id,
                                         Appointment.owner_phone == _session_owner_phone(db, session)).first()
        branch, _rec = _scoped_read(db, session)
        if not a or (branch is not None and a.branch_id != branch):
            raise HTTPException(status_code=404, detail="Appointment not found.")
        return a

    def _run(db, fn):
        try:
            out = fn()
        except AppointmentError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:                 # e.g. from the sale
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        db.commit()
        return out

    def _with_clash(db, a, clash):
        out = row(db, a)
        out["clashes"] = [{"time": c.start_at.strftime("%H:%M"), "customer": row(db, c)["customer"]["name"]}
                          for c in clash]
        return out

    @app.get("/app/api/appointments")
    def web_appointments(day: Optional[str] = Query(default=None, max_length=10),
                         session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            d = datetime.strptime(day, "%Y-%m-%d").date() if day else lagos_now().date()
            branch, _rec = _scoped_read(db, session)
            owner_phone = _session_owner_phone(db, session)
            owner = db.query(User).filter(User.phone == owner_phone).first()
            staff = db.query(User).filter(User.parent_id == owner.id).all() if owner else []
            from booking_link import requests
            return {"day": d.isoformat(), "today": lagos_now().date().isoformat(),
                    "appointments": day_list(db, owner_phone, d, branch_id=branch),
                    "requests": [row(db, a) for a in requests(db, owner_phone, branch_id=branch)],
                    "staff": [{"id": u.id, "name": (u.name or "").title()} for u in staff]
                             + ([{"id": owner.id, "name": (owner.name or "Me").title()}] if owner else [])}
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date.")
        finally:
            db.close()

    @app.post("/app/api/appointments")
    def web_book(payload: AppointmentRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_can_record(db, session, count_sale=False)
            branch, _rec = _scoped_read(db, session)
            a, clash = _run(db, lambda: book(
                db, _session_owner_phone(db, session), user.id, start_at=parse_start(payload.date, payload.time),
                duration_min=payload.duration_min, services=[s.model_dump() for s in payload.services],
                customer_id=payload.customer_id, customer_name=payload.customer_name,
                customer_phone=payload.customer_phone, staff_user_id=payload.staff_user_id,
                staff_name=payload.staff_name, note=payload.note, branch_id=branch))
            return _with_clash(db, a, clash)
        finally:
            db.close()

    @app.put("/app/api/appointments/{appt_id}")
    def web_move(appt_id: int, payload: AppointmentRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_can_record(db, session, count_sale=False)
            a = _load(db, session, appt_id)
            if a.status == "done":
                raise HTTPException(status_code=400, detail="This appointment is done — its sale is recorded.")
            a, clash = _run(db, lambda: book(
                db, a.owner_phone, user.id, start_at=parse_start(payload.date, payload.time),
                duration_min=payload.duration_min, services=[s.model_dump() for s in payload.services],
                customer_id=payload.customer_id, customer_name=payload.customer_name,
                customer_phone=payload.customer_phone, staff_user_id=payload.staff_user_id,
                staff_name=payload.staff_name, note=payload.note, appt=a))
            return _with_clash(db, a, clash)
        finally:
            db.close()

    @app.post("/app/api/appointments/{appt_id}/status")
    def web_status(appt_id: int, payload: StatusRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            a = _load(db, session, appt_id)
            _run(db, lambda: set_status(db, a, payload.status))
            return row(db, a)
        finally:
            db.close()

    @app.post("/app/api/appointments/{appt_id}/done")
    def web_done(appt_id: int, payload: DoneRequest, session: dict = Depends(require_web_auth)):
        """Done: the sale is recorded (receipt to the customer on WhatsApp)."""
        db = SessionLocal()
        try:
            user = _require_can_record(db, session)
            a = _load(db, session, appt_id)
            result = _run(db, lambda: complete(
                db, a, user.id, payload.paid,
                services=[s.model_dump() for s in payload.services] if payload.services is not None else None))
            _send_web_receipt(db, a.owner_phone, result.get("receipt_id"))
            return {**row(db, a), "receipt_id": result.get("receipt_id")}
        finally:
            db.close()

    # ── The customer booking link (booking_link.py) ──────────────────────────
    def _biz_name(db, owner_phone):
        from business_templates import business_display_name
        owner = db.query(User).filter(User.phone == owner_phone).first()
        return business_display_name(owner) if owner else "us"

    def _tell(phone, text):
        from whatsapp_client import send_whatsapp_message
        try:
            send_whatsapp_message(phone, text)
        except Exception as e:                  # the booking stands even if WhatsApp fails
            print(f"[booking] WhatsApp to customer failed: {e}", flush=True)

    @app.get("/app/api/appointments/booking-link")
    def web_booking_link(session: dict = Depends(require_web_auth)):
        from app_settings import business_setting
        from booking_link import link_for
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            owner = db.query(User).filter(User.phone == owner_phone).first()
            return {"link": link_for(owner) if owner else None,
                    "on": bool(business_setting(db, owner_phone, "booking_link")), "biz_name": _biz_name(db, owner_phone)}
        finally:
            db.close()

    @app.post("/app/api/appointments/{appt_id}/confirm")
    def web_confirm_request(appt_id: int, session: dict = Depends(require_web_auth)):
        from booking_link import confirm, confirmed_text
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            a = _load(db, session, appt_id)
            _run(db, lambda: confirm(db, a))
            if a.request_phone:
                _tell(a.request_phone, confirmed_text(_biz_name(db, a.owner_phone), a))
            return row(db, a)
        finally:
            db.close()

    @app.post("/app/api/appointments/{appt_id}/decline")
    def web_decline_request(appt_id: int, payload: DeclineRequest, session: dict = Depends(require_web_auth)):
        from booking_link import decline, declined_text
        db = SessionLocal()
        try:
            _require_can_record(db, session, count_sale=False)
            a = _load(db, session, appt_id)
            _run(db, lambda: decline(db, a))
            if a.request_phone:
                _tell(a.request_phone, declined_text(_biz_name(db, a.owner_phone), a, (payload.reason or "").strip()))
            return row(db, a)
        finally:
            db.close()

    @app.get("/app/api/public/book/{token}")
    def public_booking_page(token: str):
        from booking_link import BookingLinkError, page
        db = SessionLocal()
        try:
            return page(db, token)
        except BookingLinkError as e:
            raise HTTPException(status_code=404, detail=str(e))
        finally:
            db.close()

    @app.get("/app/api/public/book/{token}/times")
    def public_booking_times(token: str, date: str = Query(max_length=10),
                             staff: Optional[str] = Query(default=None, max_length=64)):
        from app_settings import business_setting
        from booking_link import BookingLinkError, free_times, owner_for
        db = SessionLocal()
        try:
            owner = owner_for(db, token)
            d = datetime.strptime(date, "%Y-%m-%d").date()
            if not business_setting(db, owner.phone, "booking_pick_staff"):
                staff = None
            return {"times": free_times(db, owner, d, staff or None)}
        except BookingLinkError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date.")
        finally:
            db.close()

    @app.post("/app/api/public/book/{token}")
    def public_booking_request(token: str, payload: PublicBookRequest, request: Request):
        from booking_link import BookingLinkError, confirmed_text
        from booking_link import request as ask
        from web_pay_link_routes import _throttle
        _throttle(request)
        db = SessionLocal()
        try:
            try:
                a = ask(db, token, date=payload.date, time=payload.time, service_ids=payload.service_ids,
                        name=payload.name, phone=payload.phone, staff_user_id=payload.staff_user_id,
                        note=payload.note)
            except (BookingLinkError, AppointmentError) as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            out = row(db, a)
            when = a.start_at.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")
            what = ", ".join(x["name"] for x in out["services"])
            if a.status == "requested":
                _add_notification(db, a.owner_phone, "booking_request", f"📅 {a.request_name} asks to book {when}",
                                  f"{what}. Confirm or decline it in Appointments.", link="/appointments")
            else:
                _add_notification(db, a.owner_phone, "booking_new", f"📅 New booking: {a.request_name}, {when}",
                                  f"{what} — booked from your booking link.", link="/appointments")
            db.commit()
            if a.status == "booked":
                _tell(a.request_phone, confirmed_text(_biz_name(db, a.owner_phone), a))
            return {"status": a.status, "date": out["date"], "time": out["time"], "services": what}
        finally:
            db.close()
