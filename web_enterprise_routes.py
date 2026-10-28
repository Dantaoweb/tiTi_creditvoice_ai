"""
Enterprise — "Let's talk" for large businesses (malls, chains, distributors,
lots of data). There's no price in the app: the enquiry is saved, the admins
are told, and an admin calls them to agree one (then puts them on Premium).
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import SessionLocal
from models import EnterpriseEnquiry, User
from web_auth import require_web_auth


class EnquiryRequest(BaseModel):
    name: str = Field(max_length=100)
    business: str = Field(max_length=120)
    phone: str = Field(max_length=30)
    email: Optional[str] = Field(default=None, max_length=120)
    branches: Optional[str] = Field(default=None, max_length=60)
    message: Optional[str] = Field(default=None, max_length=1000)
    source: Optional[str] = Field(default="landing", max_length=20)


class EnquiryUpdate(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    admin_note: Optional[str] = Field(default=None, max_length=300)


def _row(e):
    return {"id": e.id, "name": e.name, "business": e.business, "phone": e.phone, "email": e.email,
            "branches": e.branches, "message": e.message, "source": e.source, "user_phone": e.user_phone,
            "status": e.status, "admin_note": e.admin_note,
            "created_at": e.created_at.isoformat() if e.created_at else None}


def pending_enquiries(db):
    """Enquiries nobody has called yet."""
    return db.query(EnterpriseEnquiry).filter(EnterpriseEnquiry.status == "NEW").count()


def register_enterprise_routes(app):
    def _require_admin(db, session):
        from admin import is_app_admin
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only.")
        return user

    @app.post("/app/api/public/enterprise-enquiry")
    def public_enterprise_enquiry(payload: EnquiryRequest, request: Request):
        """Public: no account needed. Throttled like the other public forms."""
        from web_pay_link_routes import _throttle
        _throttle(request, limit=10)
        name, business = " ".join(payload.name.split()), " ".join(payload.business.split())
        phone = "".join(c for c in payload.phone if c.isdigit() or c == "+")
        if len(name) < 2 or len(business) < 2:
            raise HTTPException(status_code=400, detail="Enter your name and your business.")
        if len(phone.lstrip("+")) < 10:
            raise HTTPException(status_code=400, detail="Enter a phone number we can call.")
        email = (payload.email or "").strip() or None
        if email and ("@" not in email or "." not in email.split("@")[-1]):
            raise HTTPException(status_code=400, detail="That email doesn't look right.")
        db = SessionLocal()
        try:
            e = EnterpriseEnquiry(name=name, business=business, phone=phone, email=email,
                                  branches=(payload.branches or "").strip() or None,
                                  message=(payload.message or "").strip() or None,
                                  source=payload.source if payload.source in ("landing", "upgrade") else "landing",
                                  status="NEW")
            db.add(e)
            db.commit()
            from admin_alerts import notify_admins
            notify_admins(db, "enterprise_enquiry", f"🏢 Enterprise enquiry: {business}",
                          f"{name} · {phone}{' · ' + e.branches + ' branches' if e.branches else ''}. Call them to agree a price.",
                          tab="Enquiries")
            return {"ok": True}
        finally:
            db.close()

    @app.get("/app/api/admin/enquiries")
    def admin_enquiries(status: str = "", session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            q = db.query(EnterpriseEnquiry)
            if status:
                q = q.filter(EnterpriseEnquiry.status == status.upper())
            counts = {}
            for s, in db.query(EnterpriseEnquiry.status):
                counts[s] = counts.get(s, 0) + 1
            return {"enquiries": [_row(e) for e in q.order_by(EnterpriseEnquiry.created_at.desc()).limit(300)],
                    "counts": counts}
        finally:
            db.close()

    @app.patch("/app/api/admin/enquiries/{enquiry_id}")
    def admin_update_enquiry(enquiry_id: int, payload: EnquiryUpdate, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            e = db.query(EnterpriseEnquiry).filter(EnterpriseEnquiry.id == enquiry_id).first()
            if not e:
                raise HTTPException(status_code=404, detail="Enquiry not found.")
            if payload.status:
                if payload.status.upper() not in ("NEW", "CONTACTED", "CLOSED"):
                    raise HTTPException(status_code=400, detail="Unknown status.")
                e.status = payload.status.upper()
            if payload.admin_note is not None:
                e.admin_note = payload.admin_note.strip() or None
            db.commit()
            return _row(e)
        finally:
            db.close()
