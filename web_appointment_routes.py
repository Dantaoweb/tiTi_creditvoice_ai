"""
Appointments on the web (appointments.py). Anyone who records sales can book,
move and mark appointments; "Done" records the sale like the till.
Branch staff see their branch's appointments.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Appointment, User
from web_auth import require_web_auth
from web_common import _require_can_record, _scoped_read, _send_web_receipt, _session_owner_phone


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
            return {"day": d.isoformat(), "today": lagos_now().date().isoformat(),
                    "appointments": day_list(db, owner_phone, d, branch_id=branch),
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
