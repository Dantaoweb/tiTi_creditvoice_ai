"""
Customer, delivery, and transaction routes: customer list/add/history/pay,
structured profile get/save, transaction due-date & service-date edits, the
deliveries board + notify, and the transactions list + void.

Split out of web_routes.py. Register with register_customer_routes(app); shared
helpers come from web_common.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_

from database import SessionLocal
from models import User, Customer, Transaction, Branch
from reports import get_balance, get_owner_transaction_query
from web_auth import require_web_auth
from web_common import (
    _session_owner_phone, _owner_filter, _scoped_read, _money, _iso,
    _session_user, _send_web_receipt, _add_notification, _require_can_record,
    _like_pattern,
)


class AddCustomerRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    name: str = Field(max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)


class EditCustomerRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)


class RecordPaymentRequest(BaseModel):
    amount: int
    note: Optional[str] = Field(default=None, max_length=500)
    branch_id: Optional[int] = None


class SetTransactionDueDateRequest(BaseModel):
    due_date: Optional[str] = None  # ISO date string "YYYY-MM-DD" or null to clear


class CustomerProfileRequest(BaseModel):
    values: dict = Field(default_factory=dict)


class SetServiceDateRequest(BaseModel):
    service_date: Optional[str] = None


class DeliveryNotifyRequest(BaseModel):
    message: str = Field(max_length=1000)


class VoidTxRequest(BaseModel):
    reason: str = Field(default="", max_length=300)


def register_customer_routes(app):

    # ── Customers ────────────────────────────────────────────────────────
    def _scoped_customer_query(db, session):
        """Customers this viewer may see. Branch isolation: a branch staff sees
        their branch's customers; an unassigned staff sees only customers
        they've recorded a sale for."""
        owner_phone = _session_owner_phone(db, session)
        query = _owner_filter(db.query(Customer), Customer, owner_phone)
        eff_branch, rec = _scoped_read(db, session)
        if eff_branch is not None:
            query = query.filter(Customer.branch_id == eff_branch)
        elif rec is not None:
            query = query.filter(Customer.id.in_(
                db.query(Transaction.customer_id).filter(Transaction.recorded_by_id == rec)
            ))
        return query

    def _earliest_due_query(db):
        """(customer_id, earliest due date) over unvoided credit sales."""
        return db.query(
            Transaction.customer_id, func.min(Transaction.due_date),
        ).filter(
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None),
            Transaction.is_voided.isnot(True),
        ).group_by(Transaction.customer_id)

    def _naive_utcnow():
        return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC to match DB

    @app.get("/app/api/customers/summary")
    def web_customers_summary(session: dict = Depends(require_web_auth)):
        """Whole-list counts for the Customers page and Debtors tab. Computed on
        the server so they cover every customer, not just the loaded page."""
        db = SessionLocal()
        try:
            query = _scoped_customer_query(db, session)
            debtors = query.filter(Customer.balance > 0)
            debtor_ids = debtors.with_entities(Customer.id)
            overdue = _earliest_due_query(db).filter(
                Transaction.customer_id.in_(debtor_ids),
            ).having(func.min(Transaction.due_date) < _naive_utcnow()).count()
            return {
                "total": query.count(),
                "debtors": debtors.count(),
                "outstanding": _money(debtors.with_entities(func.sum(Customer.balance)).scalar()),
                "overdue": overdue,
            }
        finally:
            db.close()

    @app.get("/app/api/customers")
    def web_customers(
        session: dict = Depends(require_web_auth),
        q: str = Query(default="", max_length=120),
        debtors: bool = False,
        sort: str = Query(default="", pattern="^(|newest|name|balance)$"),
        dir: str = Query(default="", pattern="^(|asc|desc)$"),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        """One page of customers. `q` searches name + phone across ALL customers
        (not just the loaded page); `debtors` keeps only those who owe. Default
        order: newest first, or biggest debt first for debtors."""
        db = SessionLocal()
        try:
            now = _naive_utcnow()
            query = _scoped_customer_query(db, session)
            term = q.strip().lower()
            if term:
                conds = [
                    func.lower(Customer.name).like(_like_pattern(term), escape="\\"),
                    Customer.customer_phone.like(_like_pattern(term), escape="\\"),
                ]
                # "0803…" should find a number stored as "234803…".
                if term.isdigit() and term.startswith("0") and len(term) > 1:
                    conds.append(Customer.customer_phone.like(_like_pattern(term[1:]), escape="\\"))
                query = query.filter(or_(*conds))
            if debtors:
                query = query.filter(Customer.balance > 0)
            total = query.count()

            sort = sort or ("balance" if debtors else "newest")
            if sort == "name":
                col, default_dir = func.lower(Customer.name), "asc"
            elif sort == "balance":
                col, default_dir = func.coalesce(Customer.balance, 0), "desc"
            else:
                col, default_dir = Customer.created_at, "desc"
            order = [col.asc() if (dir or default_dir) == "asc" else col.desc()]
            if term and not dir:
                # Searching: exact name first, then names starting with the term,
                # so "tunde" is never pushed off a short result list by "mama tunde".
                name_l = func.lower(Customer.name)
                order = [case((name_l == term, 0), (name_l.like(term + "%"), 1), else_=2), name_l.asc()]
            rows = query.order_by(*order, Customer.id.desc()).offset(offset).limit(limit).all()

            # Due dates for the whole page in ONE query (was one query per debtor).
            ids = [c.id for c in rows]
            due_by_id = dict(_earliest_due_query(db).filter(Transaction.customer_id.in_(ids)).all()) if ids else {}

            result = []
            for c in rows:
                # Denormalized column — already on the row; NULL falls back to the sum
                bal = _money(c.balance if c.balance is not None else get_balance(db, c.id))
                next_due = due_by_id.get(c.id) if bal > 0 else None
                has_overdue = bool(next_due and next_due < now)
                result.append({
                    "id": c.id,
                    "name": c.name,
                    "phone": c.customer_phone,
                    "owner_phone": c.owner_phone,
                    "balance": bal,
                    "has_overdue": has_overdue,
                    "next_due": _iso(next_due),
                    "created_at": _iso(c.created_at),
                })
            return {
                "customers": result,
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(rows) < total,
            }
        finally:
            db.close()

    @app.post("/app/api/customers")
    def web_add_customer(
        payload: AddCustomerRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            # Case-insensitive: "Mama Bola" and "mama bola" are the same person.
            existing = db.query(Customer).filter(
                Customer.owner_phone == owner_phone,
                func.lower(Customer.name) == payload.name.strip().lower(),
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="A customer with this name already exists.")
            from transaction_save import _get_recording_branch_id
            c = Customer(
                owner_phone=owner_phone,
                name=payload.name.strip(),
                customer_phone=(payload.phone or "").strip() or None,
                # Tag to the creator's branch (or the business default) so it
                # lands in the right branch under isolation.
                branch_id=_get_recording_branch_id(db, owner_phone, _session_user(db, session)),
            )
            db.add(c)
            db.commit()
            db.refresh(c)
            return {"id": c.id, "name": c.name, "phone": c.customer_phone, "balance": 0}
        finally:
            db.close()

    @app.put("/app/api/customers/{customer_id}")
    def web_edit_customer(
        customer_id: int,
        payload: EditCustomerRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Rename a customer (and/or update their phone). Owner-scoped like the
        other customer mutations; blocks renaming onto another customer's name."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")

            if payload.name is not None:
                new_name = payload.name.strip()
                if not new_name:
                    raise HTTPException(status_code=400, detail="Name cannot be empty.")
                clash = db.query(Customer).filter(
                    Customer.owner_phone == owner_phone,
                    func.lower(Customer.name) == new_name.lower(),
                    Customer.id != customer_id,
                ).first()
                if clash:
                    raise HTTPException(status_code=409, detail="Another customer already has this name.")
                customer.name = new_name

            if payload.phone is not None:
                customer.customer_phone = payload.phone.strip() or None

            db.commit()
            return {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.customer_phone,
            }
        finally:
            db.close()

    @app.get("/app/api/customers/{customer_id}/history")
    def web_customer_history(customer_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")
            txs = (
                db.query(Transaction)
                .filter(
                    Transaction.customer_id == customer_id,
                    Transaction.is_voided != True,
                )
                .order_by(Transaction.created_at.desc())
                .limit(100)
                .all()
            )
            user_ids = [tx.recorded_by_id for tx in txs if tx.recorded_by_id]
            users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
            return {
                "customer": {
                    "id": customer.id,
                    "name": customer.name,
                    "phone": customer.customer_phone,
                    "balance": _money(get_balance(db, customer_id)),
                },
                "transactions": [
                    {
                        "id": tx.id,
                        "type": tx.type,
                        "amount": _money(tx.amount),
                        "product": tx.product,
                        "created_at": _iso(tx.created_at),
                        "due_date": _iso(tx.due_date),
                        "recorded_by": users[tx.recorded_by_id].name if users.get(tx.recorded_by_id) else None,
                    }
                    for tx in txs
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/customers/{customer_id}/pay")
    def web_customer_pay(
        customer_id: int,
        payload: RecordPaymentRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            # A debt repayment must never be blocked by the monthly sales cap.
            _require_can_record(db, session, count_sale=False)
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")
            from web_pos import next_receipt_number
            tx = Transaction(
                customer_id=customer_id,
                type="PAY",
                amount=payload.amount,
                product=payload.note or "Payment",
                recorded_by_id=session["user_id"],
                message_id=f"web-pay-{uuid.uuid4()}",
                branch_id=payload.branch_id,
                # Debt payments get their own per-business receipt number too, so
                # the payment receipt reads "Receipt #4" like sales — not the raw
                # global transaction id the per-business feature exists to hide.
                receipt_number=next_receipt_number(db, owner_phone),
            )
            db.add(tx)
            db.commit()
            new_balance = _money(get_balance(db, customer_id))
            # Send the customer their payment receipt on WhatsApp
            _send_web_receipt(db, owner_phone, tx.id)
            return {"id": tx.id, "amount": payload.amount, "new_balance": new_balance}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Could not record payment: {exc}")
        finally:
            db.close()

    @app.get("/app/api/customers/{customer_id}/profile")
    def web_customer_profile(customer_id: int, session: dict = Depends(require_web_auth)):
        """Return the structured profile field definitions (per business type)
        and the customer's saved values."""
        import json as _json
        from business_templates import customer_profile_fields_for_user
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            fields = customer_profile_fields_for_user(owner_user)
            try:
                values = _json.loads(customer.profile_json) if customer.profile_json else {}
            except (ValueError, TypeError):
                values = {}
            return {"customer_id": customer.id, "name": customer.name, "fields": fields, "values": values}
        finally:
            db.close()

    @app.post("/app/api/customers/{customer_id}/profile")
    def web_save_customer_profile(
        customer_id: int,
        payload: CustomerProfileRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Save the customer's structured profile values (validated against the
        business-type field set; unknown keys are dropped)."""
        import json as _json
        from business_templates import customer_profile_fields_for_user
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            allowed = {f["key"] for f in customer_profile_fields_for_user(owner_user)}
            clean = {
                k: str(v).strip()
                for k, v in (payload.values or {}).items()
                if k in allowed and str(v).strip()
            }
            customer.profile_json = _json.dumps(clean) if clean else None
            db.commit()
            return {"customer_id": customer.id, "values": clean}
        finally:
            db.close()

    @app.put("/app/api/transactions/{tx_id}/due-date")
    def web_set_transaction_due_date(
        tx_id: int,
        payload: SetTransactionDueDateRequest,
        session: dict = Depends(require_web_auth),
    ):
        from datetime import datetime as _dt
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx or not tx.customer_id:
                raise HTTPException(status_code=404, detail="Transaction not found.")
            customer = db.query(Customer).filter(
                Customer.id == tx.customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=403, detail="Not authorized.")
            tx.due_date = _dt.fromisoformat(payload.due_date) if payload.due_date else None
            db.commit()
            return {"id": tx.id, "due_date": _iso(tx.due_date)}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Could not update due date: {exc}")
        finally:
            db.close()

    @app.put("/app/api/transactions/{tx_id}/service-date")
    def web_set_transaction_service_date(
        tx_id: int,
        payload: SetServiceDateRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Edit the promised delivery / ready-by date on a sale."""
        from datetime import datetime as _dt
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Transaction not found.")
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=403, detail="Not authorized.")
            tx.service_date = _dt.fromisoformat(payload.service_date) if payload.service_date else None
            db.commit()
            return {"id": tx.id, "service_date": _iso(tx.service_date)}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Could not update delivery date: {exc}")
        finally:
            db.close()

    # ── Deliveries (jobs/orders with a promised ready date) ───────────────
    @app.get("/app/api/deliveries")
    def web_deliveries(session: dict = Depends(require_web_auth)):
        from datetime import datetime as _dt, timedelta as _td
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            cutoff = _dt.now().replace(hour=0, minute=0, second=0, microsecond=0) - _td(days=14)
            rows = (
                db.query(Transaction, Customer)
                .join(Customer, Transaction.customer_id == Customer.id)
                .filter(
                    Customer.owner_phone == owner_phone,
                    Transaction.service_date.isnot(None),
                    Transaction.is_voided.isnot(True),
                    Transaction.service_date >= cutoff,
                )
                .order_by(Transaction.service_date.asc())
                .limit(100)
                .all()
            )
            # Incoming deliveries: supplier purchases carrying a payment/delivery
            # due date that are still owing. Read-only here — payment is recorded
            # in the Suppliers menu and reminders are sent by the scheduler.
            from models import Supplier, SupplierPurchase
            incoming_rows = (
                db.query(SupplierPurchase, Supplier)
                .join(Supplier, SupplierPurchase.supplier_id == Supplier.id)
                .filter(
                    SupplierPurchase.owner_phone == owner_phone,
                    SupplierPurchase.due_date.isnot(None),
                    SupplierPurchase.total > SupplierPurchase.paid_amount,
                )
                .order_by(SupplierPurchase.due_date.asc())
                .limit(100)
                .all()
            )
            return {
                "deliveries": [
                    {
                        "id": tx.id,
                        "service_date": _iso(tx.service_date),
                        "customer": cust.name,
                        "customer_phone": cust.customer_phone,
                        "product": tx.product,
                        "created_at": _iso(tx.created_at),
                    }
                    for tx, cust in rows
                ],
                "incoming": [
                    {
                        "id": p.id,
                        "supplier": (sup.name or "").title(),
                        "product": (p.product or "").title(),
                        "quantity": p.quantity,
                        "unit": p.unit,
                        "due_date": _iso(p.due_date),
                        "balance": max(0, (p.total or 0) - (p.paid_amount or 0)),
                    }
                    for p, sup in incoming_rows
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/deliveries/{tx_id}/notify")
    def web_notify_delivery(
        tx_id: int,
        payload: DeliveryNotifyRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Send the owner-composed message to the customer's WhatsApp."""
        from whatsapp_client import send_whatsapp_message
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx or not tx.customer_id:
                raise HTTPException(status_code=404, detail="Delivery not found.")
            customer = db.query(Customer).filter(
                Customer.id == tx.customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=403, detail="Not authorized.")
            if not customer.customer_phone:
                raise HTTPException(status_code=400, detail="This customer has no phone number saved.")
            msg = (payload.message or "").strip()
            if not msg:
                raise HTTPException(status_code=400, detail="Enter a message to send.")
            try:
                send_whatsapp_message(customer.customer_phone, msg)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Could not send message: {exc}")
            return {"ok": True}
        except HTTPException:
            raise
        finally:
            db.close()

    # ── Transactions ──────────────────────────────────────────────────────
    def _tx_query(db, session, period, branch_id, q):
        """Transactions this viewer may see for the period, voided included,
        optionally narrowed by a customer-name / product search."""
        owner_phone = _session_owner_phone(db, session)
        period_key = period.upper() if period else None
        # Branch isolation: staff are scoped to their branch (or own records);
        # an owner may filter by the branch they picked.
        eff_branch, rec = _scoped_read(db, session, branch_id)
        query = get_owner_transaction_query(
            db, owner_phone, period_key, recorded_by_id=rec, include_voided=True, branch_id=eff_branch,
        )
        term = (q or "").strip().lower()
        if term:
            pat = _like_pattern(term)
            # Customer is already outer-joined by get_owner_transaction_query.
            query = query.filter(or_(
                func.lower(Customer.name).like(pat, escape="\\"),
                func.lower(Transaction.product).like(pat, escape="\\"),
            ))
        return query

    @app.get("/app/api/transactions/summary")
    def web_transactions_summary(
        period: Optional[str] = Query(default=None),
        branch_id: Optional[int] = Query(default=None),
        q: str = Query(default="", max_length=120),
        session: dict = Depends(require_web_auth),
    ):
        """How many transactions of each type match — over the WHOLE period, so
        the type filters show real counts rather than what's been loaded."""
        db = SessionLocal()
        try:
            query = _tx_query(db, session, period, branch_id, q)
            by_type = dict(
                query.with_entities(Transaction.type, func.count(Transaction.id))
                .group_by(Transaction.type).all()
            )
            by_type = {t: n for t, n in by_type.items() if t}
            return {"total": sum(by_type.values()), "by_type": by_type}
        finally:
            db.close()

    @app.get("/app/api/transactions")
    def web_transactions(
        period: Optional[str] = Query(default=None),
        branch_id: Optional[int] = Query(default=None),
        tx_type: str = Query(default="", alias="type", max_length=20),
        q: str = Query(default="", max_length=120),
        sort: str = Query(default="date", pattern="^(date|amount)$"),
        dir: str = Query(default="desc", pattern="^(asc|desc)$"),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        session: dict = Depends(require_web_auth),
    ):
        """One page of the period's transactions (newest first by default).
        `type` and `q` filter across the whole period, not just the loaded page."""
        db = SessionLocal()
        try:
            query = _tx_query(db, session, period, branch_id, q)
            if tx_type:
                query = query.filter(Transaction.type == tx_type.upper())
            total = query.count()
            col = Transaction.amount if sort == "amount" else Transaction.created_at
            order = col.asc() if dir == "asc" else col.desc()
            rows = query.order_by(order, Transaction.id.desc()).offset(offset).limit(limit).all()
            customer_ids = [r.customer_id for r in rows if r.customer_id]
            customers = {}
            if customer_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()}
            user_ids = list({uid for r in rows for uid in [r.recorded_by_id, r.voided_by_id] if uid})
            users = {}
            if user_ids:
                users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
            branch_ids = [r.branch_id for r in rows if r.branch_id]
            branches = {}
            if branch_ids:
                branches = {b.id: b for b in db.query(Branch).filter(Branch.id.in_(branch_ids)).all()}
            return {
                "transactions": [
                    {
                        "id": tx.id,
                        "type": tx.type,
                        "amount": _money(tx.amount),
                        "product": tx.product,
                        "quantity": tx.quantity,
                        "unit": tx.unit,
                        "unit_price": _money(tx.unit_price),
                        "customer": customers[tx.customer_id].name if customers.get(tx.customer_id) else "Direct sale",
                        "recorded_by": users[tx.recorded_by_id].name if users.get(tx.recorded_by_id) else None,
                        "due_date": _iso(tx.due_date),
                        "created_at": _iso(tx.created_at),
                        "is_voided": bool(tx.is_voided),
                        "void_reason": tx.void_reason,
                        "voided_by": users[tx.voided_by_id].name if tx.voided_by_id and users.get(tx.voided_by_id) else None,
                        "voided_at": _iso(tx.voided_at),
                        "branch_id": tx.branch_id,
                        "branch_name": branches[tx.branch_id].name if tx.branch_id and branches.get(tx.branch_id) else None,
                    }
                    for tx in rows
                ],
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(rows) < total,
            }
        finally:
            db.close()

    @app.post("/app/api/transactions/{tx_id}/void")
    def web_void_transaction(
        tx_id: int,
        payload: VoidTxRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Void a transaction from the web (mirrors the WhatsApp 'void' command):
        marks it voided so it drops out of balances/reports, records who/why, and
        alerts the owner when a staff member does it."""
        from reports import get_owner_transaction_query
        from models import TransactionNote
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_phone = _session_owner_phone(db, session)
            if not user:
                raise HTTPException(status_code=401, detail="Not authenticated.")
            is_owner = user.phone == owner_phone
            # Staff may only see/void their own records unless granted full view.
            staff_filter = None if (is_owner or user.can_view_all_transactions) else user.id
            base = get_owner_transaction_query(db, owner_phone, recorded_by_id=staff_filter)
            tx = base.filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Transaction not found or already voided.")
            # Full-view staff can see all, but may still only void what they recorded.
            if not is_owner and tx.recorded_by_id != user.id:
                raise HTTPException(status_code=403, detail="You can only void transactions you recorded yourself.")

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            reason = payload.reason.strip() or "No reason given"
            tx.is_voided = True
            tx.void_reason = reason
            tx.voided_by_id = user.id
            tx.voided_at = now
            # Voiding a sale returns the stock it deducted (no-op for payments).
            from inventory_suppliers import restore_inventory_for_voided_sale
            restored = restore_inventory_for_voided_sale(db, owner_phone, tx.id, user.id)
            db.add(TransactionNote(
                transaction_id=tx.id,
                author_user_id=user.id,
                note=f"VOIDED by {(user.name or '').title()} on {now.strftime('%d/%m/%Y %H:%M')}. Reason: {reason}",
            ))
            # In-app notification so the owner sees every void (theirs or staff's).
            _add_notification(
                db, owner_phone, "void",
                f"Transaction #{tx.id} voided",
                f"{(user.name or 'Someone').title()} voided a ₦{tx.amount:,} transaction — reason: {reason}",
            )
            db.commit()

            if not is_owner:
                try:
                    from whatsapp_client import send_whatsapp_message
                    send_whatsapp_message(
                        owner_phone,
                        f"*VOID ALERT* - Staff action\n\n"
                        f"*{(user.name or '').title()}* voided transaction #{tx.id} "
                        f"(N{tx.amount:,}).\nReason: {reason}\n\n"
                        "Check your dashboard if this looks suspicious."
                    )
                except Exception:
                    pass

            return {"ok": True, "id": tx.id, "is_voided": True, "void_reason": reason,
                    "stock_returned": restored}
        finally:
            db.close()
