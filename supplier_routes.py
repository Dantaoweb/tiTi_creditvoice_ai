"""
Verified Supplier Directory + Opportunities API routes.

Registered in web_routes.py via register_supplier_routes(app).
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, List

from database import SessionLocal
from models import (
    Opportunity,
    SupplierContactMessage,
    User,
    VerifiedSupplier,
    VerifiedSupplierProduct,
)

NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu",
    "FCT Abuja", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina",
    "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo",
    "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
]

SUPPLIER_TYPES = [
    ("producer",               "Producer / Farmer"),
    ("manufacturer",           "Manufacturer"),
    ("importer",               "Importer"),
    ("authorized_distributor", "Authorised Distributor"),
    ("wholesaler",             "Wholesaler / Big Dealer"),
]


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_owner(db: Session, request):
    """Resolve owner phone from auth cookie or raise 401."""
    from web_auth import get_current_user_phone
    phone = get_current_user_phone(request)
    if not phone:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return phone


def _require_admin(db: Session, phone: str):
    user = db.query(User).filter(User.phone == phone).first()
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")


# ── Pydantic models ────────────────────────────────────────────────────────────

class SupplierProductIn(BaseModel):
    product_name:    str  = Field(max_length=120)
    category:        str  = Field(default="", max_length=80)
    available_sizes: list = Field(default_factory=list)
    min_order_qty:   Optional[float] = None
    min_order_unit:  str  = Field(default="", max_length=40)
    price_range:     str  = Field(default="", max_length=120)
    quality_notes:   str  = Field(default="", max_length=400)


class SupplierApplyIn(BaseModel):
    supplier_type:  str  = Field(max_length=40)
    bio:            str  = Field(default="", max_length=800)
    states_covered: list = Field(default_factory=list)
    can_deliver:    bool = False
    delivery_notes: str  = Field(default="", max_length=400)
    cac_number:     str  = Field(default="", max_length=80)
    products:       List[SupplierProductIn] = Field(default_factory=list)


class ContactMessageIn(BaseModel):
    product_interest: str  = Field(default="", max_length=120)
    message:          str  = Field(max_length=1000)


class OpportunityIn(BaseModel):
    title:        str  = Field(max_length=200)
    partner_name: str  = Field(default="", max_length=120)
    category:     str  = Field(default="general", max_length=60)
    description:  str  = Field(max_length=2000)
    link_url:     str  = Field(default="", max_length=500)
    is_active:    bool = True


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _supplier_dict(db: Session, vs: VerifiedSupplier, include_products=True):
    user = db.query(User).filter(User.phone == vs.owner_phone).first()
    products = []
    if include_products:
        rows = db.query(VerifiedSupplierProduct).filter(
            VerifiedSupplierProduct.supplier_id == vs.id
        ).all()
        products = [
            {
                "id": p.id,
                "product_name": p.product_name,
                "category": p.category or "",
                "available_sizes": json.loads(p.available_sizes or "[]"),
                "min_order_qty": p.min_order_qty,
                "min_order_unit": p.min_order_unit or "",
                "price_range": p.price_range or "",
                "quality_notes": p.quality_notes or "",
            }
            for p in rows
        ]
    return {
        "id": vs.id,
        "owner_phone": vs.owner_phone,
        "business_name": (user.business_type_label or user.name or vs.owner_phone) if user else vs.owner_phone,
        "supplier_type": vs.supplier_type,
        "supplier_type_label": dict(SUPPLIER_TYPES).get(vs.supplier_type, vs.supplier_type),
        "bio": vs.bio or "",
        "states_covered": json.loads(vs.states_covered or "[]"),
        "can_deliver": bool(vs.can_deliver),
        "delivery_notes": vs.delivery_notes or "",
        "cac_number": vs.cac_number or "",
        "verification_status": vs.verification_status,
        "rejection_reason": vs.rejection_reason or "",
        "reviewed_at": vs.reviewed_at.isoformat() if vs.reviewed_at else None,
        "created_at": vs.created_at.isoformat() if vs.created_at else None,
        "products": products,
    }


# ── Route registration ─────────────────────────────────────────────────────────

def register_supplier_routes(app, get_db=None):
    from fastapi import Request

    # ── Meta / constants ───────────────────────────────────────────────────────

    @app.get("/app/api/verified-suppliers/meta")
    def supplier_meta():
        return {
            "states": NIGERIAN_STATES,
            "supplier_types": [{"key": k, "label": l} for k, l in SUPPLIER_TYPES],
        }

    # ── Directory: browse approved suppliers ──────────────────────────────────

    @app.get("/app/api/verified-suppliers/directory")
    def supplier_directory(
        request: Request,
        product: str = "",
        state: str = "",
        supplier_type: str = "",
    ):
        db = SessionLocal()
        try:
            q = db.query(VerifiedSupplier).filter(
                VerifiedSupplier.verification_status == "approved"
            )
            results = q.order_by(VerifiedSupplier.created_at.desc()).all()

            # Filter by state (JSON text contains check)
            if state:
                results = [r for r in results if state in (r.states_covered or "")]

            # Filter by supplier_type
            if supplier_type:
                results = [r for r in results if r.supplier_type == supplier_type]

            # Filter by product name (check products table)
            if product:
                plow = product.lower()
                filtered = []
                for r in results:
                    prods = db.query(VerifiedSupplierProduct).filter(
                        VerifiedSupplierProduct.supplier_id == r.id
                    ).all()
                    if any(plow in (p.product_name or "").lower() for p in prods):
                        filtered.append(r)
                results = filtered

            return {
                "suppliers": [_supplier_dict(db, r) for r in results],
                "total": len(results),
            }
        finally:
            db.close()

    # ── Own profile (get) ──────────────────────────────────────────────────────

    @app.get("/app/api/verified-suppliers/profile")
    def get_supplier_profile(request: Request):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            vs = db.query(VerifiedSupplier).filter(
                VerifiedSupplier.owner_phone == phone
            ).first()
            if not vs:
                return {"profile": None}
            return {"profile": _supplier_dict(db, vs)}
        finally:
            db.close()

    # ── Apply for supplier status ──────────────────────────────────────────────

    @app.post("/app/api/verified-suppliers/apply")
    def apply_supplier(request: Request, payload: SupplierApplyIn):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)

            # Supplier status is a PRO feature
            user = db.query(User).filter(User.phone == phone).first()
            plan = (user.subscription_plan or "BASIC").upper() if user else "BASIC"
            if plan not in ("PRO",):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Verified Supplier status is a PRO feature. "
                        "Upgrade to PRO to list your business in the supplier directory "
                        "and get recommended to retailers across Nigeria."
                    ),
                )

            existing = db.query(VerifiedSupplier).filter(
                VerifiedSupplier.owner_phone == phone
            ).first()
            if existing and existing.verification_status in ("pending", "approved"):
                raise HTTPException(
                    status_code=400,
                    detail="You already have a pending or approved application."
                )

            if payload.supplier_type not in dict(SUPPLIER_TYPES):
                raise HTTPException(status_code=400, detail="Invalid supplier type.")

            if not payload.products:
                raise HTTPException(
                    status_code=400,
                    detail="Add at least one product you supply."
                )

            # Upsert (re-apply after rejection)
            if existing:
                existing.supplier_type    = payload.supplier_type
                existing.bio              = payload.bio or None
                existing.states_covered   = json.dumps(payload.states_covered)
                existing.can_deliver      = payload.can_deliver
                existing.delivery_notes   = payload.delivery_notes or None
                existing.cac_number       = payload.cac_number or None
                existing.verification_status = "pending"
                existing.rejection_reason = None
                existing.updated_at       = _utcnow()
                vs = existing
                # Clear old products
                db.query(VerifiedSupplierProduct).filter(
                    VerifiedSupplierProduct.supplier_id == vs.id
                ).delete()
            else:
                vs = VerifiedSupplier(
                    id             = str(uuid.uuid4()),
                    owner_phone    = phone,
                    supplier_type  = payload.supplier_type,
                    bio            = payload.bio or None,
                    states_covered = json.dumps(payload.states_covered),
                    can_deliver    = payload.can_deliver,
                    delivery_notes = payload.delivery_notes or None,
                    cac_number     = payload.cac_number or None,
                )
                db.add(vs)
                db.flush()

            for p in payload.products:
                db.add(VerifiedSupplierProduct(
                    id              = str(uuid.uuid4()),
                    supplier_id     = vs.id,
                    product_name    = p.product_name,
                    category        = p.category or None,
                    available_sizes = json.dumps(p.available_sizes),
                    min_order_qty   = p.min_order_qty,
                    min_order_unit  = p.min_order_unit or None,
                    price_range     = p.price_range or None,
                    quality_notes   = p.quality_notes or None,
                ))

            db.commit()
            return {"ok": True, "message": "Application submitted. Admin will review within 48 hours."}
        finally:
            db.close()

    # ── Update own profile (approved suppliers only) ───────────────────────────

    @app.put("/app/api/verified-suppliers/profile")
    def update_supplier_profile(request: Request, payload: SupplierApplyIn):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            vs = db.query(VerifiedSupplier).filter(
                VerifiedSupplier.owner_phone == phone,
                VerifiedSupplier.verification_status == "approved",
            ).first()
            if not vs:
                raise HTTPException(status_code=404, detail="No approved profile found.")

            vs.bio            = payload.bio or None
            vs.states_covered = json.dumps(payload.states_covered)
            vs.can_deliver    = payload.can_deliver
            vs.delivery_notes = payload.delivery_notes or None
            vs.cac_number     = payload.cac_number or None
            vs.updated_at     = _utcnow()

            db.query(VerifiedSupplierProduct).filter(
                VerifiedSupplierProduct.supplier_id == vs.id
            ).delete()
            for p in payload.products:
                db.add(VerifiedSupplierProduct(
                    id              = str(uuid.uuid4()),
                    supplier_id     = vs.id,
                    product_name    = p.product_name,
                    category        = p.category or None,
                    available_sizes = json.dumps(p.available_sizes),
                    min_order_qty   = p.min_order_qty,
                    min_order_unit  = p.min_order_unit or None,
                    price_range     = p.price_range or None,
                    quality_notes   = p.quality_notes or None,
                ))

            db.commit()
            return {"ok": True}
        finally:
            db.close()

    # ── Contact a supplier ─────────────────────────────────────────────────────

    @app.post("/app/api/verified-suppliers/{supplier_id}/contact")
    def contact_supplier(request: Request, supplier_id: str, payload: ContactMessageIn):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            vs = db.query(VerifiedSupplier).filter(
                VerifiedSupplier.id == supplier_id,
                VerifiedSupplier.verification_status == "approved",
            ).first()
            if not vs:
                raise HTTPException(status_code=404, detail="Supplier not found.")

            if vs.owner_phone == phone:
                raise HTTPException(status_code=400, detail="You cannot message yourself.")

            user = db.query(User).filter(User.phone == phone).first()
            biz = (user.business_type_label or user.name or phone) if user else phone

            db.add(SupplierContactMessage(
                id                 = str(uuid.uuid4()),
                supplier_id        = supplier_id,
                from_phone         = phone,
                from_business_name = biz,
                product_interest   = payload.product_interest or None,
                message            = payload.message,
            ))
            db.commit()
            return {"ok": True, "message": "Message sent to supplier."}
        finally:
            db.close()

    # ── Supplier inbox (own messages received) ─────────────────────────────────

    @app.get("/app/api/verified-suppliers/inbox")
    def supplier_inbox(request: Request):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            vs = db.query(VerifiedSupplier).filter(
                VerifiedSupplier.owner_phone == phone,
                VerifiedSupplier.verification_status == "approved",
            ).first()
            if not vs:
                return {"messages": [], "unread": 0}

            msgs = db.query(SupplierContactMessage).filter(
                SupplierContactMessage.supplier_id == vs.id
            ).order_by(SupplierContactMessage.created_at.desc()).all()

            return {
                "messages": [
                    {
                        "id": m.id,
                        "from_business_name": m.from_business_name or m.from_phone,
                        "product_interest": m.product_interest or "",
                        "message": m.message,
                        "status": m.status,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in msgs
                ],
                "unread": sum(1 for m in msgs if m.status == "unread"),
            }
        finally:
            db.close()

    @app.patch("/app/api/verified-suppliers/messages/{msg_id}/read")
    def mark_message_read(request: Request, msg_id: str):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            vs = db.query(VerifiedSupplier).filter(
                VerifiedSupplier.owner_phone == phone
            ).first()
            if not vs:
                raise HTTPException(status_code=404)
            msg = db.query(SupplierContactMessage).filter(
                SupplierContactMessage.id == msg_id,
                SupplierContactMessage.supplier_id == vs.id,
            ).first()
            if msg:
                msg.status = "read"
                db.commit()
            return {"ok": True}
        finally:
            db.close()

    # ── Opportunities (public read) ────────────────────────────────────────────

    @app.get("/app/api/opportunities")
    def list_opportunities():
        db = SessionLocal()
        try:
            opps = db.query(Opportunity).filter(
                Opportunity.is_active == True
            ).order_by(Opportunity.created_at.desc()).all()
            return {
                "opportunities": [
                    {
                        "id": o.id,
                        "title": o.title,
                        "partner_name": o.partner_name or "",
                        "category": o.category or "general",
                        "description": o.description,
                        "link_url": o.link_url or "",
                        "created_at": o.created_at.isoformat() if o.created_at else None,
                    }
                    for o in opps
                ]
            }
        finally:
            db.close()

    # ── Admin: list supplier applications ─────────────────────────────────────

    @app.get("/app/api/admin/supplier-applications")
    def admin_supplier_applications(request: Request, status: str = "pending"):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            _require_admin(db, phone)
            q = db.query(VerifiedSupplier)
            if status != "all":
                q = q.filter(VerifiedSupplier.verification_status == status)
            rows = q.order_by(VerifiedSupplier.created_at.desc()).all()
            return {"applications": [_supplier_dict(db, r) for r in rows]}
        finally:
            db.close()

    @app.post("/app/api/admin/supplier-applications/{supplier_id}/approve")
    def admin_approve_supplier(request: Request, supplier_id: str):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            _require_admin(db, phone)
            vs = db.query(VerifiedSupplier).filter(VerifiedSupplier.id == supplier_id).first()
            if not vs:
                raise HTTPException(status_code=404)
            vs.verification_status = "approved"
            vs.rejection_reason    = None
            vs.reviewed_at         = _utcnow()
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/admin/supplier-applications/{supplier_id}/reject")
    def admin_reject_supplier(request: Request, supplier_id: str, payload: RejectIn):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            _require_admin(db, phone)
            vs = db.query(VerifiedSupplier).filter(VerifiedSupplier.id == supplier_id).first()
            if not vs:
                raise HTTPException(status_code=404)
            vs.verification_status = "rejected"
            vs.rejection_reason    = payload.reason or None
            vs.reviewed_at         = _utcnow()
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    # ── Admin: opportunities CRUD ─────────────────────────────────────────────

    @app.get("/app/api/admin/opportunities")
    def admin_list_opportunities(request: Request):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            _require_admin(db, phone)
            opps = db.query(Opportunity).order_by(Opportunity.created_at.desc()).all()
            return {
                "opportunities": [
                    {
                        "id": o.id, "title": o.title,
                        "partner_name": o.partner_name or "",
                        "category": o.category or "general",
                        "description": o.description,
                        "link_url": o.link_url or "",
                        "is_active": bool(o.is_active),
                        "created_at": o.created_at.isoformat() if o.created_at else None,
                    }
                    for o in opps
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/admin/opportunities")
    def admin_create_opportunity(request: Request, payload: OpportunityIn):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            _require_admin(db, phone)
            opp = Opportunity(
                id           = str(uuid.uuid4()),
                title        = payload.title,
                partner_name = payload.partner_name or None,
                category     = payload.category or "general",
                description  = payload.description,
                link_url     = payload.link_url or None,
                is_active    = payload.is_active,
            )
            db.add(opp)
            db.commit()
            return {"ok": True, "id": opp.id}
        finally:
            db.close()

    @app.put("/app/api/admin/opportunities/{opp_id}")
    def admin_update_opportunity(request: Request, opp_id: str, payload: OpportunityIn):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            _require_admin(db, phone)
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            if not opp:
                raise HTTPException(status_code=404)
            opp.title        = payload.title
            opp.partner_name = payload.partner_name or None
            opp.category     = payload.category or "general"
            opp.description  = payload.description
            opp.link_url     = payload.link_url or None
            opp.is_active    = payload.is_active
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.delete("/app/api/admin/opportunities/{opp_id}")
    def admin_delete_opportunity(request: Request, opp_id: str):
        db = SessionLocal()
        try:
            phone = _get_owner(db, request)
            _require_admin(db, phone)
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            if opp:
                db.delete(opp)
                db.commit()
            return {"ok": True}
        finally:
            db.close()
