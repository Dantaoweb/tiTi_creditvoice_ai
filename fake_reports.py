"""
Shops warning each other about suspected fake products.

A shop that suspects a packet reports it: the product, its barcode, the
supplier it came from and what looked wrong. A CreditVoice admin reviews every
report — nothing reaches other shops on one shop's word. When an admin
CONFIRMS it:
  • every other shop stocking that barcode is warned,
  • every other shop buying from that supplier (matched by the supplier's
    phone number, the one thing that identifies a supplier across shops) is
    warned,
  • and the barcode is flagged from then on at every till and stock form
    (barcode_insight reads confirmed_reports_for).
The reporter hears the outcome either way. A barcode can't prove a product
is fake or genuine, so warnings say "reported", never "fake".
"""
import logging

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional

from database import SessionLocal
from models import FakeReport, InventoryItem, Supplier, User, utcnow
from web_auth import require_web_auth
from web_common import _session_owner_phone, _session_user

_log = logging.getLogger(__name__)

STATUSES = ("PENDING", "CONFIRMED", "DISMISSED")


class FakeReportRequest(BaseModel):
    item_id: Optional[int] = None
    product_name: str = Field(max_length=120)
    barcode: Optional[str] = Field(default=None, max_length=48)
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = Field(default=None, max_length=120)
    supplier_phone: Optional[str] = Field(default=None, max_length=20)
    reason: str = Field(max_length=600)


class FakeReviewRequest(BaseModel):
    status: str = Field(max_length=12)          # CONFIRMED | DISMISSED
    admin_note: Optional[str] = Field(default=None, max_length=400)


def confirmed_reports_for(db, code):
    """How many reports about this barcode an admin has confirmed."""
    import barcodes
    if not (code or "").strip():
        return 0
    return db.query(FakeReport).filter(
        FakeReport.barcode.in_(barcodes.forms(code)), FakeReport.status == "CONFIRMED").count()


def pending_fake_reports(db):
    return db.query(FakeReport).filter(FakeReport.status == "PENDING").count()


def _phone_forms(phone):
    from web_auth import phone_candidates
    return phone_candidates(phone) if phone else []


def _dict(r, admin=False):
    out = {
        "id": r.id,
        "product_name": r.product_name,
        "barcode": r.barcode,
        "supplier_name": r.supplier_name,
        "reason": r.reason,
        "status": r.status,
        "admin_note": r.admin_note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "shops_warned": r.shops_warned or 0,
    }
    if admin:
        out.update({"owner_phone": r.owner_phone, "supplier_phone": r.supplier_phone,
                    "business_name": r.business_name})
    return out


def _shops_to_warn(db, report):
    """Other businesses stocking the barcode or buying from the supplier."""
    phones = set()
    if report.barcode:
        import barcodes
        for (p,) in db.query(InventoryItem.owner_phone).filter(
                InventoryItem.barcode.in_(barcodes.forms(report.barcode))).distinct():
            phones.add(p)
    forms = _phone_forms(report.supplier_phone)
    if forms:
        for (p,) in db.query(Supplier.owner_phone).filter(Supplier.phone.in_(forms)).distinct():
            phones.add(p)
    phones.discard(report.owner_phone)
    phones.discard(None)
    return sorted(phones)


def _warn_shops(db, report):
    from proactive_scheduler import _notify
    shops = _shops_to_warn(db, report)
    what = report.product_name.title()
    via = []
    if report.barcode:
        via.append(f"barcode {report.barcode}")
    if report.supplier_name:
        via.append(f"supplied by {report.supplier_name}")
    body = (f"Another shop reported suspected fake {what} ({', '.join(via) or 'no barcode'}), "
            "and the CreditVoice team confirmed the report. Check this product in your stock "
            "before you sell it.")
    if report.admin_note:
        body += f"\n\nWhat to look for: {report.admin_note}"
    for phone in shops:
        try:
            _notify(db, phone, "fake_warning", "⚠️ Suspected fake product reported", body, link="/inventory")
        except Exception:
            _log.exception("could not warn %s about report %s", phone, report.id)
    return len(shops)


def register_fake_report_routes(app):

    @app.post("/app/api/fake-reports")
    def report_fake(payload: FakeReportRequest, session: dict = Depends(require_web_auth)):
        """A shop reports a product it suspects is fake. Admins review it."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            user = _session_user(db, session)
            reason = payload.reason.strip()
            if not reason:
                raise HTTPException(status_code=400, detail="Say what looked wrong.")
            import barcodes
            name = payload.product_name.strip()
            barcode = barcodes.clean(payload.barcode) or None
            if payload.item_id:
                item = db.query(InventoryItem).filter(
                    InventoryItem.id == payload.item_id, InventoryItem.owner_phone == owner_phone).first()
                if not item:
                    raise HTTPException(status_code=404, detail="Product not found.")
                name = name or item.name
                barcode = barcode or item.barcode
            sup_name = (payload.supplier_name or "").strip() or None
            sup_phone = (payload.supplier_phone or "").strip() or None
            if payload.supplier_id:
                sup = db.query(Supplier).filter(
                    Supplier.id == payload.supplier_id, Supplier.owner_phone == owner_phone).first()
                if not sup:
                    raise HTTPException(status_code=404, detail="Supplier not found.")
                sup_name, sup_phone = sup.name, sup.phone
            owner = db.query(User).filter(User.phone == owner_phone).first()
            biz = (owner.business_type_label or owner.name) if owner else owner_phone
            r = FakeReport(
                owner_phone=owner_phone, reporter_user_id=user.id if user else None,
                business_name=biz, item_id=payload.item_id, product_name=name, barcode=barcode,
                supplier_name=sup_name, supplier_phone=sup_phone, reason=reason, status="PENDING",
            )
            db.add(r)
            db.commit()
            db.refresh(r)

            from admin_alerts import notify_admins
            notify_admins(
                db, "fake_report", "🚩 Suspected fake reported",
                f"{biz} reports suspected fake {name.title()}"
                + (f" (barcode {barcode})" if barcode else "")
                + (f", supplied by {sup_name}" if sup_name else "")
                + f": “{reason[:160]}”",
                tab="Fakes",
            )
            return _dict(r)
        finally:
            db.close()

    @app.get("/app/api/fake-reports/mine")
    def my_fake_reports(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            rows = (db.query(FakeReport).filter(FakeReport.owner_phone == owner_phone)
                    .order_by(FakeReport.created_at.desc()).limit(100).all())
            return {"reports": [_dict(r) for r in rows]}
        finally:
            db.close()

    import barcodes

    def _require_admin(db, session):
        from admin import is_app_admin
        user = _session_user(db, session)
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only")
        return user

    @app.get("/app/api/admin/fake-reports")
    def admin_fake_reports(status: str = Query(default="PENDING", max_length=12),
                           session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            q = db.query(FakeReport)
            if status and status.upper() in STATUSES:
                q = q.filter(FakeReport.status == status.upper())
            rows = q.order_by(FakeReport.created_at.desc()).limit(300).all()
            out = []
            for r in rows:
                d = _dict(r, admin=True)
                # What confirming would do, so the admin decides knowing it.
                d["would_warn"] = len(_shops_to_warn(db, r)) if r.status == "PENDING" else None
                d["other_reports"] = (db.query(FakeReport).filter(
                    FakeReport.id != r.id, FakeReport.barcode.in_(barcodes.forms(r.barcode))).count()
                    if r.barcode else 0)
                out.append(d)
            counts = {s: db.query(FakeReport).filter(FakeReport.status == s).count() for s in STATUSES}
            return {"reports": out, "counts": counts}
        finally:
            db.close()

    @app.patch("/app/api/admin/fake-reports/{report_id}")
    def admin_review_fake_report(report_id: int, payload: FakeReviewRequest,
                                 session: dict = Depends(require_web_auth)):
        """Confirm (warn other shops) or dismiss a report. Decided once."""
        from proactive_scheduler import _notify
        db = SessionLocal()
        try:
            admin_user = _require_admin(db, session)
            r = db.query(FakeReport).filter(FakeReport.id == report_id).first()
            if not r:
                raise HTTPException(status_code=404, detail="Report not found.")
            status = payload.status.upper()
            if status not in ("CONFIRMED", "DISMISSED"):
                raise HTTPException(status_code=400, detail="Confirm or dismiss it.")
            if r.status != "PENDING":
                raise HTTPException(status_code=409, detail=f"Already {r.status.lower()}.")
            r.status = status
            r.admin_note = (payload.admin_note or "").strip() or None
            r.reviewed_at = utcnow()
            r.reviewed_by = admin_user.phone
            db.commit()

            if status == "CONFIRMED":
                r.shops_warned = _warn_shops(db, r)
                db.commit()
                told = ("Thank you — the CreditVoice team confirmed your report about "
                        f"{r.product_name.title()}. Other shops stocking it or buying from the same "
                        f"supplier have been warned ({r.shops_warned}).")
            else:
                told = (f"We looked into your report about {r.product_name.title()} and couldn't "
                        "confirm it." + (f"\n\n{r.admin_note}" if r.admin_note else "")
                        + "\n\nThank you for reporting — keep them coming.")
            try:
                _notify(db, r.owner_phone, "fake_report_outcome", "Your fake product report", told,
                        link="/inventory")
            except Exception:
                _log.exception("could not tell the reporter about report %s", r.id)
            return _dict(r, admin=True)
        finally:
            db.close()
