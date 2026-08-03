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
                    {"id": b.id, "name": b.name, "address": b.address,
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

            name = payload.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Branch name is required.")
            existing = db.query(Branch).filter(
                Branch.owner_phone == owner_phone,
                Branch.name == name,
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="A branch with that name already exists.")
            is_first = db.query(Branch).filter(Branch.owner_phone == owner_phone).count() == 0
            branch = Branch(owner_phone=owner_phone, name=name,
                            address=(payload.address or "").strip() or None, is_default=is_first)
            db.add(branch)
            db.commit()
            return {"id": branch.id, "name": branch.name, "address": branch.address,
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

            # Re-home first, so nothing is left pointing at a branch that no
            # longer exists (that data would become invisible under isolation,
            # and the dangling FK would block the delete). Branch ids are unique
            # across owners, so filtering on branch_id alone is safe.
            for _model in (Customer, InventoryItem, Transaction):
                db.query(_model).filter(_model.branch_id == branch_id).update(
                    {"branch_id": new_default}, synchronize_session=False
                )
            db.query(User).filter(User.branch_id == branch_id).update(
                {"branch_id": new_default}, synchronize_session=False
            )
            db.commit()

            from audit import audit
            audit(db, action="DELETE_BRANCH", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"branch:{branch_id}:{branch.name}")
            db.delete(branch)
            if was_default and target:
                target.is_default = True
            db.commit()
            return {"ok": True, "reassigned_to_branch_id": new_default}
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
            if payload.name and payload.name.strip():
                branch.name = payload.name.strip()
            branch.address = (payload.address or "").strip() or None
            db.commit()
            return {"id": branch.id, "name": branch.name, "address": branch.address,
                    "is_default": bool(branch.is_default)}
        finally:
            db.close()
