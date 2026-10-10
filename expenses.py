"""
Business expenses — rent, salaries, transport… — so profit can be net of them.

Two ways in, one ledger:
  • the owner (or an authorised staff) records an expense directly, and
  • anyone shares one as a Note (category "expense" with an amount) — that is
    how staff tell the boss what they spent. Those wait in "To review" until
    the boss approves them as an expense (choosing the type and date) or marks
    them "not an expense". Only approved ones count.

Buying stock is NOT an expense here: it is already the cost of goods in gross
profit, and counting it again would make profit look smaller than it is.

Everything is for the owner and authorised staff (_can_see_profit), and
follows branches like the rest of the books.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func

from database import SessionLocal
from models import BusinessNote, Expense, User
from web_auth import require_web_auth
from web_common import _can_see_profit, _iso, _scoped_read, _session_owner_phone, _session_user

CATEGORIES = {
    "rent": "Rent",
    "salaries": "Salaries & wages",
    "transport": "Transport",
    "fuel": "Fuel & generator",
    "electricity": "Electricity",
    "phone": "Phone & data",
    "repairs": "Repairs",
    "taxes": "Taxes & levies",
    "other": "Other",
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def expenses_between(db, owner_phone, start=None, end=None, branch_id=None):
    """Total approved expenses in a date range (by the day they were spent)."""
    q = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(Expense.owner_phone == owner_phone)
    if branch_id is not None:
        q = q.filter(Expense.branch_id == branch_id)
    if start is not None:
        q = q.filter(Expense.spent_on >= start, Expense.spent_on < end)
    return int(q.scalar() or 0)


def expenses_for_period(db, owner_phone, period=None, branch_id=None):
    """Total for a Dashboard period key (TODAY, THIS_WEEK, … or None = all time)."""
    from reports import get_period_range
    start, end = get_period_range(period) if period else (None, None)
    return expenses_between(db, owner_phone, start, end, branch_id)


def notes_to_review(db, owner_phone):
    """Expense notes with an amount the boss hasn't decided on yet."""
    return (db.query(BusinessNote)
            .filter(BusinessNote.owner_phone == owner_phone,
                    BusinessNote.category == "expense",
                    BusinessNote.amount.isnot(None),
                    BusinessNote.amount > 0,
                    BusinessNote.expense_status.is_(None))
            .order_by(BusinessNote.created_at.desc()).all())


def _expense_dict(e, names):
    return {
        "id": e.id,
        "category": e.category,
        "category_label": CATEGORIES.get(e.category, e.category.title()),
        "amount": e.amount,
        "spent_on": e.spent_on.date().isoformat() if e.spent_on else None,
        "note": e.note,
        "branch_id": e.branch_id,
        "recorded_by": names.get(e.recorded_by_id),
        "from_note": e.source_note_id is not None,
        "created_at": _iso(e.created_at),
    }


class ExpenseIn(BaseModel):
    amount: int = Field(gt=0)
    category: str = Field(max_length=20)
    spent_on: Optional[str] = Field(default=None, max_length=10)     # YYYY-MM-DD, default today
    note: Optional[str] = Field(default=None, max_length=300)
    branch_id: Optional[int] = None


class ApproveNoteIn(BaseModel):
    category: str = Field(max_length=20)
    spent_on: Optional[str] = Field(default=None, max_length=10)
    amount: Optional[int] = Field(default=None, gt=0)                # correct it if the note was off


def _day(text):
    if not text:
        return _now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="The date must look like 2026-10-10.")


def _category(key):
    key = (key or "").strip().lower()
    if key not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Choose a type of expense.")
    return key


def register_expense_routes(app):

    def _guard(db, session):
        if not _can_see_profit(db, session):
            raise HTTPException(status_code=403,
                                detail="Expenses are for the business owner and authorised staff.")
        return _session_owner_phone(db, session)

    def _branch_for_new(db, session, owner_phone, requested):
        scope_branch, _rec = _scoped_read(db, session)
        if scope_branch is not None:
            return scope_branch                      # a branch admin records into their branch
        return requested

    def _load(db, session, expense_id):
        owner_phone = _guard(db, session)
        e = db.query(Expense).filter(Expense.id == expense_id, Expense.owner_phone == owner_phone).first()
        scope_branch, _rec = _scoped_read(db, session)
        if not e or (scope_branch is not None and e.branch_id != scope_branch):
            raise HTTPException(status_code=404, detail="Expense not found.")
        return e

    @app.get("/app/api/expenses")
    def list_expenses(period: Optional[str] = Query(default=None, max_length=20),
                      branch_id: Optional[int] = Query(default=None),
                      session: dict = Depends(require_web_auth)):
        from reports import get_period_range
        db = SessionLocal()
        try:
            owner_phone = _guard(db, session)
            eff_branch, _rec = _scoped_read(db, session, branch_id)
            period_key = period.upper() if period else None
            q = db.query(Expense).filter(Expense.owner_phone == owner_phone)
            if eff_branch is not None:
                q = q.filter(Expense.branch_id == eff_branch)
            if period_key:
                start, end = get_period_range(period_key)
                if start:
                    q = q.filter(Expense.spent_on >= start, Expense.spent_on < end)
            rows = q.order_by(Expense.spent_on.desc(), Expense.id.desc()).limit(500).all()
            ids = {r.recorded_by_id for r in rows if r.recorded_by_id}
            names = {u.id: u.name for u in db.query(User).filter(User.id.in_(list(ids)))} if ids else {}
            by_cat = {}
            for r in rows:
                by_cat[r.category] = by_cat.get(r.category, 0) + (r.amount or 0)

            review = notes_to_review(db, owner_phone)
            authors = {n.created_by_id for n in review if n.created_by_id}
            anames = {u.id: u.name for u in db.query(User).filter(User.id.in_(list(authors)))} if authors else {}
            return {
                "expenses": [_expense_dict(r, names) for r in rows],
                "total": sum(by_cat.values()),
                "by_category": sorted(
                    [{"category": k, "label": CATEGORIES.get(k, k.title()), "amount": v} for k, v in by_cat.items()],
                    key=lambda x: x["amount"], reverse=True),
                "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()],
                "to_review": [{
                    "note_id": n.id, "body": n.body, "amount": n.amount,
                    "shared_by": anames.get(n.created_by_id) or "You",
                    "created_at": _iso(n.created_at),
                } for n in review],
            }
        finally:
            db.close()

    @app.post("/app/api/expenses")
    def add_expense(payload: ExpenseIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _guard(db, session)
            user = _session_user(db, session)
            e = Expense(
                owner_phone=owner_phone, category=_category(payload.category), amount=payload.amount,
                spent_on=_day(payload.spent_on), note=(payload.note or "").strip() or None,
                branch_id=_branch_for_new(db, session, owner_phone, payload.branch_id),
                recorded_by_id=user.id if user else None, created_at=_now(),
            )
            db.add(e)
            db.commit()
            return {"ok": True, "id": e.id}
        finally:
            db.close()

    @app.put("/app/api/expenses/{expense_id}")
    def edit_expense(expense_id: int, payload: ExpenseIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            e = _load(db, session, expense_id)
            e.category = _category(payload.category)
            e.amount = payload.amount
            e.spent_on = _day(payload.spent_on)
            e.note = (payload.note or "").strip() or None
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.delete("/app/api/expenses/{expense_id}")
    def delete_expense(expense_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            e = _load(db, session, expense_id)
            # A note it came from goes back to "to review", so it isn't lost.
            if e.source_note_id:
                note = db.query(BusinessNote).filter(BusinessNote.id == e.source_note_id).first()
                if note:
                    note.expense_status = None
            db.delete(e)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    def _review_note(db, session, note_id):
        owner_phone = _guard(db, session)
        note = db.query(BusinessNote).filter(
            BusinessNote.id == note_id, BusinessNote.owner_phone == owner_phone,
            BusinessNote.category == "expense").first()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found.")
        if note.expense_status:
            raise HTTPException(status_code=409, detail="That note was already reviewed.")
        return owner_phone, note

    def _tell_author(db, note, owner_phone, text):
        """The staff who shared it hears the decision."""
        if not note.created_by_id:
            return
        author = db.query(User).filter(User.id == note.created_by_id).first()
        if not author or author.phone == owner_phone:
            return
        try:
            from web_common import _add_notification
            _add_notification(db, author.phone, "expense_review", "Your expense note", text, link="/notes")
            db.commit()
        except Exception:
            pass

    @app.post("/app/api/expenses/from-note/{note_id}")
    def approve_note(note_id: int, payload: ApproveNoteIn, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone, note = _review_note(db, session, note_id)
            user = _session_user(db, session)
            author = db.query(User).filter(User.id == note.created_by_id).first() if note.created_by_id else None
            e = Expense(
                owner_phone=owner_phone, category=_category(payload.category),
                amount=payload.amount or note.amount,
                spent_on=_day(payload.spent_on) if payload.spent_on else (note.created_at or _now()),
                note=(note.body or "")[:300],
                branch_id=getattr(author, "branch_id", None),
                recorded_by_id=user.id if user else None, created_at=_now(), source_note_id=note.id,
            )
            db.add(e)
            note.expense_status = "APPROVED"
            db.commit()
            _tell_author(db, note, owner_phone,
                         f"Your expense of N{e.amount:,} was approved and added to Expenses.")
            return {"ok": True, "id": e.id}
        finally:
            db.close()

    @app.post("/app/api/expenses/notes/{note_id}/dismiss")
    def dismiss_note(note_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone, note = _review_note(db, session, note_id)
            note.expense_status = "DISMISSED"
            db.commit()
            _tell_author(db, note, owner_phone,
                         f"Your note of N{note.amount:,} was reviewed and not counted as a business expense.")
            return {"ok": True}
        finally:
            db.close()
