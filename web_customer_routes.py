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

from database import SessionLocal
from models import User, Customer, Transaction, Branch
from reports import get_balance, get_owner_transaction_query
from web_auth import require_web_auth
from web_common import (
    _session_owner_phone, _owner_filter, _scoped_read, _money, _iso,
    _session_user, _send_web_receipt, _add_notification,
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
    @app.get("/app/api/customers")
    def web_customers(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC to match DB
            owner_phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(Customer), Customer, owner_phone)
            # Branch isolation: a branch staff sees their branch's customers; an
            # unassigned staff sees only customers they've recorded a sale for.
            eff_branch, rec = _scoped_read(db, session)
            if eff_branch is not None:
                query = query.filter(Customer.branch_id == eff_branch)
            elif rec is not None:
                query = query.filter(Customer.id.in_(
                    db.query(Transaction.customer_id).filter(Transaction.recorded_by_id == rec)
                ))
            rows = query.order_by(Customer.created_at.desc()).limit(200).all()

            def _customer_due(customer_id):
                due_dates = [
                    tx.due_date
                    for tx in db.query(Transaction).filter(
                        Transaction.customer_id == customer_id,
                        Transaction.type == "BUY",
                        Transaction.due_date.isnot(None),
                        Transaction.is_voided.isnot(True),
                    ).all()
                    if tx.due_date
                ]
                if not due_dates:
                    return None, False
                next_due = min(due_dates)
                has_overdue = any(d < now for d in due_dates)
                return next_due, has_overdue

            result = []
            for c in rows:
                # Denormalized column — already on the row; NULL falls back to the sum
                bal = _money(c.balance if c.balance is not None else get_balance(db, c.id))
                next_due, has_overdue = _customer_due(c.id) if bal > 0 else (None, False)
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
            return {"customers": result}
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
            existing = db.query(Customer).filter(
                Customer.owner_phone == owner_phone,
                Customer.name == payload.name.strip(),
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
                    Customer.name == new_name,
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
                ]
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
    @app.get("/app/api/transactions")
    def web_transactions(
        period: Optional[str] = Query(default=None),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            # Branch isolation: staff are scoped to their branch (or own records);
            # an owner may filter by the branch they picked.
            eff_branch, rec = _scoped_read(db, session, branch_id)
            query = get_owner_transaction_query(
                db, owner_phone, period_key, recorded_by_id=rec, include_voided=True, branch_id=eff_branch,
            )
            rows = query.order_by(Transaction.created_at.desc()).limit(200).all()
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
                ]
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

            return {"ok": True, "id": tx.id, "is_voided": True, "void_reason": reason}
        finally:
            db.close()
