"""
Thrift / Ajo routes: summary (group + personal), personal-save, add-participant.

Split out of web_routes.py. Register with register_thrift_routes(app);
shared helpers come from web_common.
"""
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Transaction, Customer
from reports import get_owner_transaction_query
from web_auth import require_web_auth
from web_common import _session_owner_phone, _money, _iso


class ThriftSaveRequest(BaseModel):
    amount: int
    note: Optional[str] = Field(default=None, max_length=500)


class ThriftParticipantRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)


class SavingsPlanRequest(BaseModel):
    frequency: str = Field(max_length=20)
    goal_amount: Optional[int] = None


def register_thrift_routes(app):

    @app.get("/app/api/thrift/summary")
    def web_thrift_summary(
        period: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """Return thrift data split into group contributions and personal savings."""
        import sqlalchemy as _sa
        from collections import defaultdict
        import logging as _log
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            base = get_owner_transaction_query(db, owner_phone, period_key)

            # Group thrift: customer-linked transactions with thrift/ajo/esusu/contribution keywords
            group_filter = _sa.and_(
                Transaction.customer_id != None,
                _sa.or_(
                    Transaction.product.ilike("%thrift%"),
                    Transaction.product.ilike("%ajo%"),
                    Transaction.product.ilike("%esusu%"),
                    Transaction.product.ilike("%contribut%"),
                ),
            )
            # Personal savings: DIRECT type with personal_savings product OR savings/thrift/ajo with no customer
            personal_filter = _sa.or_(
                _sa.and_(Transaction.type == "DIRECT", Transaction.product.ilike("%personal_saving%")),
                _sa.and_(Transaction.type == "DIRECT", Transaction.product.ilike("%personal saving%")),
                _sa.and_(
                    Transaction.customer_id == None,
                    Transaction.type == "DIRECT",
                    _sa.or_(
                        Transaction.product.ilike("%saving%"),
                        Transaction.product.ilike("%thrift%"),
                        Transaction.product.ilike("%ajo%"),
                    ),
                ),
            )

            group_rows    = base.filter(group_filter).order_by(Transaction.created_at.desc()).all()
            personal_rows = base.filter(personal_filter).order_by(Transaction.created_at.desc()).all()

            # Customer lookup for group rows
            cust_ids  = list({r.customer_id for r in group_rows if r.customer_id})
            customers: dict = {}
            if cust_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()}

            def _tx(tx, name):
                return {
                    "id": tx.id,
                    "customer_id": tx.customer_id,
                    "customer_name": name,
                    "amount": _money(tx.amount),
                    "product": (tx.product or "").replace("personal_savings", "").replace("personal savings", "").strip(": ") or None,
                    "created_at": _iso(tx.created_at),
                }

            group_tx_list    = [_tx(tx, customers[tx.customer_id].name if customers.get(tx.customer_id) else "Unknown") for tx in group_rows]
            personal_tx_list = [_tx(tx, "Me") for tx in personal_rows]

            # Participant totals (group)
            totals: dict = defaultdict(lambda: {"name": "Unknown", "count": 0, "total": 0})
            for tx in group_rows:
                key = tx.customer_id
                c = customers.get(key)
                totals[key]["name"]  = c.name if c else "Unknown"
                totals[key]["count"] += 1
                totals[key]["total"] += int(tx.amount or 0)
            participants = sorted(
                [{"id": k, **v} for k, v in totals.items()],
                key=lambda p: p["total"], reverse=True,
            )

            group_total    = sum(int(tx.amount or 0) for tx in group_rows)
            personal_total = sum(int(tx.amount or 0) for tx in personal_rows)
            return {
                "group": {
                    "transactions": group_tx_list,
                    "participants": participants,
                    "total": group_total,
                    "count": len(group_rows),
                },
                "personal": {
                    "transactions": personal_tx_list,
                    "total": personal_total,
                    "count": len(personal_rows),
                },
            }
        except Exception as _e:
            _log.getLogger("creditvoice.thrift").exception("thrift/summary error")
            raise HTTPException(status_code=500, detail=f"Thrift summary failed: {_e}")
        finally:
            db.close()

    @app.post("/app/api/thrift/save")
    def web_thrift_personal_save(
        payload: ThriftSaveRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Record a personal savings entry (no participant needed)."""
        db = SessionLocal()
        try:
            if payload.amount <= 0:
                raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
            note = f": {payload.note}" if payload.note else ""
            tx = Transaction(
                customer_id=None,
                type="DIRECT",
                amount=payload.amount,
                product=f"personal_savings{note}",
                recorded_by_id=session["user_id"],
                message_id=f"web-save-{uuid.uuid4()}",
            )
            db.add(tx)
            db.commit()
            return {"ok": True, "id": tx.id, "amount": _money(payload.amount)}
        finally:
            db.close()

    @app.get("/app/api/savings/plan")
    def web_savings_plan(session: dict = Depends(require_web_auth)):
        """The personal-savings plan: frequency, goal, progress and next-due."""
        import savings
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            return savings.savings_summary(db, owner_phone)
        finally:
            db.close()

    @app.post("/app/api/savings/plan")
    def web_set_savings_plan(payload: SavingsPlanRequest, session: dict = Depends(require_web_auth)):
        import savings
        db = SessionLocal()
        try:
            if payload.frequency not in savings.FREQUENCIES:
                raise HTTPException(status_code=400, detail="Pick a frequency: daily, weekly or monthly.")
            if payload.goal_amount is not None and payload.goal_amount < 0:
                raise HTTPException(status_code=400, detail="Goal amount can't be negative.")
            owner_phone = _session_owner_phone(db, session)
            savings.set_plan(db, owner_phone, payload.frequency, payload.goal_amount)
            return savings.savings_summary(db, owner_phone)
        finally:
            db.close()

    @app.post("/app/api/thrift/participants")
    def web_thrift_add_participant(
        payload: ThriftParticipantRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Add a thrift participant (creates a customer record)."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            # Check for duplicate
            existing = db.query(Customer).filter(
                Customer.owner_phone == owner_phone,
                Customer.name == payload.name.strip().lower(),
            ).first()
            if existing:
                return {"id": existing.id, "name": existing.name, "existing": True}
            customer = Customer(
                owner_phone=owner_phone,
                name=payload.name.strip().lower(),
                customer_phone=payload.phone,
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
            return {"id": customer.id, "name": customer.name, "existing": False}
        finally:
            db.close()
