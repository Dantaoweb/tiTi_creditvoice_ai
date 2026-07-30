"""
Business notes routes: list, create (with owner notification), delete.

Split out of web_routes.py. Register with register_notes_routes(app);
shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import require_web_auth
from web_common import _iso, _session_owner_phone, _add_notification


class CreateNoteRequest(BaseModel):
    body: str = Field(max_length=2000)
    category: str = Field(default="memo", max_length=30)
    amount: Optional[int] = None
    visibility: str = Field(default="owner_only", max_length=30)
    owner_phone: Optional[str] = Field(default=None, max_length=20)


def register_notes_routes(app):

    @app.get("/app/api/notes")
    def web_notes(
        category: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            from models import BusinessNote
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner:
                return {"notes": []}
            owner_phone = owner.phone if owner.parent_id is None else (
                db.query(User).filter(User.id == owner.parent_id).first() or owner
            ).phone
            is_staff = owner.parent_id is not None
            query = db.query(BusinessNote).filter(BusinessNote.owner_phone == owner_phone)
            if is_staff:
                query = query.filter(BusinessNote.visibility == "all")
            if category:
                query = query.filter(BusinessNote.category == category)
            notes = query.order_by(BusinessNote.created_at.desc()).limit(100).all()
            return {
                "notes": [
                    {
                        "id": n.id,
                        "body": n.body,
                        "category": n.category,
                        "amount": n.amount,
                        "visibility": n.visibility,
                        "created_at": _iso(n.created_at),
                    }
                    for n in notes
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/notes")
    def web_create_note(payload: CreateNoteRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessNote
            from partner_commands import _utcnow
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner:
                raise HTTPException(status_code=403, detail="Not authenticated.")
            owner_phone = _session_owner_phone(db, session)
            now = _utcnow()
            note = BusinessNote(
                owner_phone=owner_phone,
                body=payload.body.strip(),
                category=payload.category,
                amount=payload.amount,
                visibility=payload.visibility,
                created_by_id=owner.id,
                created_at=now,
                updated_at=now,
            )
            db.add(note)
            # In-app notification so notes (theirs or a staff's) show in the feed.
            _add_notification(
                db, owner_phone, "note",
                f"New note ({payload.category})",
                f"{(owner.name or 'Someone').title()} added a note: {payload.body.strip()[:80]}",
            )
            db.commit()
            db.refresh(note)
            return {"ok": True, "id": note.id}
        finally:
            db.close()

    @app.delete("/app/api/notes/{note_id}")
    def web_delete_note(note_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessNote
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            owner_phone = owner.phone if owner.parent_id is None else (
                db.query(User).filter(User.id == owner.parent_id).first() or owner
            ).phone
            note = db.query(BusinessNote).filter(
                BusinessNote.id == note_id,
                BusinessNote.owner_phone == owner_phone,
            ).first()
            if not note:
                raise HTTPException(status_code=404, detail="Note not found.")
            from audit import audit
            audit(db, action="DELETE_NOTE", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"note:{note_id}")
            db.delete(note)
            db.commit()
            return {"ok": True}
        finally:
            db.close()
