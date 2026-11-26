"""
Branch routes: list, create, delete (with re-homing), set-default, update.

Split out of web_routes.py. Register with register_branch_routes(app);
shared helpers come from web_common. Branch management is owner-only — branches
drive data isolation, so staff must not create/remove/re-default them.
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, Branch, Customer, InventoryItem, Transaction
from web_auth import require_web_auth
from web_common import _iso, _session_user


class CreateBranchRequest(BaseModel):
    name: str = Field(max_length=60)
    address: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=40)     # on this branch's receipts


def _clean_phone(text):
    """A branch's phone for its receipts: one or two numbers, or none."""
    from printables import clean_receipt_phones
    try:
        return clean_receipt_phones(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _tidy(name):
    return " ".join((name or "").split())


def _name_taken(db, owner_phone, name, except_id=None):
    """Another branch already has this name — capitals and spaces ignored."""
    from sqlalchemy import func
    q = db.query(Branch).filter(Branch.owner_phone == owner_phone, func.lower(Branch.name) == name.lower())
    if except_id is not None:
        q = q.filter(Branch.id != except_id)
    return q.first() is not None


def _branch_columns():
    """Every column, in every table, that points at a branch."""
    from database import Base
    out = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if any(fk.column.table.name == Branch.__tablename__ for fk in col.foreign_keys):
                out.append((table, col))
    return out


def register_branch_routes(app):

    @app.get("/app/api/branches")
    def web_branches(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_phone = session["phone"]
            if user and user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else owner_phone
            rows = db.query(Branch).filter(Branch.owner_phone == owner_phone).order_by(Branch.created_at).all()
            return {
                "branches": [
                    {"id": b.id, "name": b.name, "address": b.address, "phone": b.phone,
                     "is_default": bool(b.is_default), "created_at": _iso(b.created_at)}
                    for b in rows
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/branches")
    def web_create_branch(payload: CreateBranchRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            # Branch management is owner-only: branches drive data isolation, so
            # staff must not be able to create/remove/re-default them.
            user = _session_user(db, session)
            if not user or user.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can manage branches.")
            owner_phone = user.phone

            # Branches are a Pro/Premium feature. Pro is capped at 1 branch;
            # Premium is unlimited. (Existing branches on lower plans are kept —
            # this only guards adding a new one.)
            from subscriptions import (
                get_business_subscription, ensure_feature_allowed, check_branch_limit,
            )
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "BRANCHES", "Branches")
            if not allowed:
                raise HTTPException(status_code=403, detail=upgrade_msg)
            subscription = get_business_subscription(db, user)
            within, limit_msg = check_branch_limit(db, user, subscription)
            if not within:
                raise HTTPException(status_code=403, detail=limit_msg)

            name = _tidy(payload.name)
            if not name:
                raise HTTPException(status_code=400, detail="Branch name is required.")
            if _name_taken(db, owner_phone, name):
                raise HTTPException(status_code=400, detail="You already have a branch with that name.")
            is_first = db.query(Branch).filter(Branch.owner_phone == owner_phone).count() == 0
            branch = Branch(owner_phone=owner_phone, name=name,
                            address=(payload.address or "").strip() or None,
                            phone=_clean_phone(payload.phone), is_default=is_first)
            db.add(branch)
            db.commit()
            return {"id": branch.id, "name": branch.name, "address": branch.address, "phone": branch.phone,
                    "is_default": bool(branch.is_default)}
        finally:
            db.close()

    @app.delete("/app/api/branches/{branch_id}")
    def web_delete_branch(branch_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user or user.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can manage branches.")
            owner_phone = user.phone
            branch = db.query(Branch).filter(Branch.id == branch_id, Branch.owner_phone == owner_phone).first()
            if not branch:
                raise HTTPException(status_code=404, detail="Branch not found.")
            was_default = branch.is_default

            # Which branch should everything fall back to (excluding this one)?
            remaining = db.query(Branch).filter(
                Branch.owner_phone == owner_phone, Branch.id != branch_id
            )
            target = (
                remaining.order_by(Branch.created_at).first()
                if was_default
                else remaining.filter(Branch.is_default == True).first()
            )
            new_default = target.id if target else None

            # Stock on its way to or from it: settle that first
            from models import StockTransfer
            if db.query(StockTransfer).filter(
                    StockTransfer.status == "on_the_way",
                    (StockTransfer.from_branch_id == branch_id) | (StockTransfer.to_branch_id == branch_id)).first():
                raise HTTPException(status_code=400, detail=(
                    "Stock is on its way to or from this branch. Receive or cancel that transfer first "
                    "(Inventory → Transfers)."))

            # Products both branches have will sit twice in the one kept — say so
            from similar_products import squashed
            kept_names = {squashed(i.name) for i in db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner_phone, InventoryItem.branch_id == new_default,
                InventoryItem.removed_at.is_(None)).all()} if new_default else set()
            twice = sum(1 for i in db.query(InventoryItem).filter(
                InventoryItem.branch_id == branch_id, InventoryItem.removed_at.is_(None)).all()
                if squashed(i.name) in kept_names)

            # Re-home EVERYTHING that points at it — customers, stock, sales,
            # staff, invoices, waybills, expenses, held sales, counts… — so
            # nothing becomes invisible under isolation and no link blocks the
            # delete. Transfers keep their history: the gone branch shows as
            # "Deleted branch". Branch ids are unique across owners, so
            # filtering on the id alone is safe.
            for table, col in _branch_columns():
                value = None if table.name == "stock_transfers" else new_default
                db.execute(table.update().where(col == branch_id).values({col.name: value}))
            db.commit()

            from audit import audit
            audit(db, action="DELETE_BRANCH", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"branch:{branch_id}:{branch.name}")
            db.delete(branch)
            if was_default and target:
                target.is_default = True
            db.commit()
            return {"ok": True, "reassigned_to_branch_id": new_default, "products_twice": twice}
        finally:
            db.close()

    @app.post("/app/api/branches/{branch_id}/default")
    def web_set_default_branch(branch_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user or user.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can manage branches.")
            owner_phone = user.phone
            db.query(Branch).filter(Branch.owner_phone == owner_phone).update({"is_default": False})
            branch = db.query(Branch).filter(Branch.id == branch_id, Branch.owner_phone == owner_phone).first()
            if not branch:
                raise HTTPException(status_code=404, detail="Branch not found.")
            branch.is_default = True
            db.commit()
            return {"ok": True, "default_branch_id": branch_id}
        finally:
            db.close()

    @app.put("/app/api/branches/{branch_id}")
    def web_update_branch(branch_id: int, payload: CreateBranchRequest, session: dict = Depends(require_web_auth)):
        """Owner edits a branch's name/address (shown on that branch's receipts)."""
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user or user.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can manage branches.")
            branch = db.query(Branch).filter(
                Branch.id == branch_id, Branch.owner_phone == user.phone
            ).first()
            if not branch:
                raise HTTPException(status_code=404, detail="Branch not found.")
            if payload.name and _tidy(payload.name):
                if _name_taken(db, user.phone, _tidy(payload.name), except_id=branch.id):
                    raise HTTPException(status_code=400, detail="You already have a branch with that name.")
                branch.name = _tidy(payload.name)
            branch.address = (payload.address or "").strip() or None
            if payload.phone is not None:
                branch.phone = _clean_phone(payload.phone)
            db.commit()
            return {"id": branch.id, "name": branch.name, "address": branch.address, "phone": branch.phone,
                    "is_default": bool(branch.is_default)}
        finally:
            db.close()
