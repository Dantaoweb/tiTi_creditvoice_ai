"""
Subscription / Upgrade routes: status, bank-transfer request, confirm-payment,
Monnify init/verify, and the public Monnify subscription webhook.

Split out of web_routes.py. Register with register_subscription_routes(app);
shared helpers come from web_common.
"""
import json
import os
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import require_web_auth
from web_common import _add_notification


class SubscriptionRequestBody(BaseModel):
    plan: str = Field(max_length=10)
    period: str = Field(default="MONTHLY", max_length=10)


class MonnifyInitBody(BaseModel):
    plan: str = Field(max_length=10)
    period: str = Field(default="MONTHLY", max_length=10)


class MonnifyVerifyBody(BaseModel):
    reference: str = Field(max_length=80)
    transaction_reference: Optional[str] = Field(default=None, max_length=120)


def register_subscription_routes(app):

    @app.get("/app/api/subscription/status")
    def web_subscription_status(session: dict = Depends(require_web_auth)):
        """Return current plan, expiry, and any pending payment request."""
        import requests as _req
        db = SessionLocal()
        try:
            from subscriptions import get_business_subscription, get_pending_subscription_payment
            from messages import get_plan_price, get_payment_account_message
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            sub = get_business_subscription(db, user)
            pending = get_pending_subscription_payment(db, user)
            go_price      = get_plan_price("GO")
            pro_price     = get_plan_price("PRO")
            premium_price = get_plan_price("PREMIUM")
            bank_details = get_payment_account_message()
            is_test = "sandbox" in os.getenv("MONNIFY_BASE_URL", "sandbox")
            return {
                "plan":       sub["plan"],
                "status":     sub["status"],
                "expires_at": sub["expires_at"].isoformat() if sub["expires_at"] else None,
                "prices":     {"GO": go_price, "PRO": pro_price, "PREMIUM": premium_price},
                "prices_yearly": {
                    "GO":      get_plan_price("GO", "YEARLY"),
                    "PRO":     get_plan_price("PRO", "YEARLY"),
                    "PREMIUM": get_plan_price("PREMIUM", "YEARLY"),
                },
                "bank_details": bank_details,
                "monnify": {
                    "api_key":       os.getenv("MONNIFY_API_KEY", ""),
                    "contract_code": os.getenv("MONNIFY_CONTRACT_CODE", ""),
                    "is_test":       is_test,
                },
                "pending_payment": {
                    "id":     pending.id,
                    "plan":   pending.plan,
                    "amount": pending.amount,
                    "period": pending.billing_period or "MONTHLY",
                    "method": pending.payment_method,
                    "status": pending.status,
                } if pending else None,
                "user": {
                    "name":  user.name or "",
                    "email": user.email or f"{user.phone}@creditvoice.app",
                    "phone": user.phone or "",
                },
            }
        finally:
            db.close()

    @app.post("/app/api/subscription/request")
    def web_subscription_bank_transfer(
        payload: SubscriptionRequestBody,
        session: dict = Depends(require_web_auth),
    ):
        """Create a pending bank-transfer subscription upgrade request."""
        from subscriptions import create_subscription_payment_request
        from messages import get_payment_account_message
        from plans import normalize_plan, PLAN_BASIC
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            plan = normalize_plan(payload.plan)
            if plan == PLAN_BASIC:
                raise HTTPException(status_code=400, detail="Cannot request a downgrade to Basic.")
            payment = create_subscription_payment_request(db, user, plan, payload.period)
            payment.payment_method = "BANK_TRANSFER"
            db.commit()
            return {
                "ok": True,
                "payment_id": payment.id,
                "plan": plan,
                "period": payment.billing_period,
                "amount": payment.amount,
                "bank_details": get_payment_account_message(),
                "reference": user.phone,
            }
        finally:
            db.close()

    @app.post("/app/api/subscription/confirm-payment")
    def web_subscription_confirm_payment(
        payload: SubscriptionRequestBody,
        session: dict = Depends(require_web_auth),
    ):
        """User reports they've completed the bank transfer — alert admins
        (WhatsApp + email). This is the web equivalent of replying PAID on
        WhatsApp; it does NOT activate the plan (an admin still approves)."""
        from subscriptions import (
            create_subscription_payment_request,
            get_pending_subscription_payment,
            get_business_owner_user,
        )
        from admin_commands import notify_subscription_admins
        from whatsapp_client import send_whatsapp_message
        from plans import normalize_plan, PLAN_BASIC
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")

            payment = get_pending_subscription_payment(db, user)
            if not payment:
                # Modal reopened / request expired — recreate so admins are still alerted
                plan = normalize_plan(payload.plan)
                if plan == PLAN_BASIC:
                    raise HTTPException(status_code=400, detail="Invalid plan.")
                payment = create_subscription_payment_request(db, user, plan, payload.period)
                payment.payment_method = "BANK_TRANSFER"
                db.commit()

            owner = get_business_owner_user(db, user)
            try:
                notify_subscription_admins(db, payment, owner, send_whatsapp_message, evidence_received=False)
            except Exception:
                import traceback; traceback.print_exc()

            # In-app notification to app admins so it shows on the web dashboard.
            try:
                from admin import app_admin_phones
                from web_auth import phone_candidates
                cand = set()
                for p in app_admin_phones():
                    cand.update(phone_candidates(p))
                owner_name = (owner.name if owner else user.name) or user.phone
                admins = db.query(User).filter(User.phone.in_(list(cand))).all() if cand else []
                for a in admins:
                    _add_notification(
                        db, a.phone, "upgrade",
                        f"Upgrade payment: {payment.plan}",
                        f"{owner_name} ({user.phone}) reports paying for {payment.plan} by bank transfer — please verify and approve.",
                    )
                if admins:
                    db.commit()
            except Exception:
                import traceback; traceback.print_exc()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/subscription/monnify/init")
    def web_subscription_monnify_init(
        payload: MonnifyInitBody,
        session: dict = Depends(require_web_auth),
    ):
        """Create a Monnify payment reference for subscription upgrade."""
        from subscriptions import create_subscription_payment_request
        from plans import normalize_plan, PLAN_BASIC
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            plan = normalize_plan(payload.plan)
            if plan == PLAN_BASIC:
                raise HTTPException(status_code=400, detail="Cannot request Basic via Monnify.")
            payment = create_subscription_payment_request(db, user, plan, payload.period)
            payment.payment_method = "MONNIFY"
            # Use the DB payment ID as the unique reference for Monnify
            db.flush()
            ref = f"CV-SUB-{payment.id}-{uuid.uuid4().hex[:6].upper()}"
            payment.evidence_ref = ref
            db.commit()
            is_test = "sandbox" in os.getenv("MONNIFY_BASE_URL", "sandbox")
            return {
                "ok": True,
                "reference": ref,
                "amount": payment.amount,
                "plan": plan,
                "api_key": os.getenv("MONNIFY_API_KEY", ""),
                "contract_code": os.getenv("MONNIFY_CONTRACT_CODE", ""),
                "is_test": is_test,
                "customer_name": user.name or user.phone,
                "customer_email": user.email or f"{user.phone}@creditvoice.app",
                "period": payment.billing_period,
                "description": f"CreditVoice {plan} Plan - {'1 year' if payment.billing_period == 'YEARLY' else '1 month'}",
            }
        finally:
            db.close()

    @app.post("/app/api/subscription/monnify/verify")
    def web_subscription_monnify_verify(
        payload: MonnifyVerifyBody,
        session: dict = Depends(require_web_auth),
    ):
        """Verify a Monnify payment and activate subscription if successful."""
        import requests as _req
        from subscriptions import approve_subscription_payment
        from plans import normalize_plan
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")

            # Find the pending payment by evidence_ref (our reference)
            from models import SubscriptionPayment
            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.evidence_ref == payload.reference,
                SubscriptionPayment.payment_method == "MONNIFY",
            ).first()
            if not payment:
                raise HTTPException(status_code=404, detail="Payment reference not found.")
            if payment.status == "APPROVED":
                return {"ok": True, "plan": payment.plan, "already_active": True}

            # Verify with Monnify API
            from wallet_service import _get_monnify_token, MONNIFY_BASE_URL
            try:
                token = _get_monnify_token()
                tx_ref = payload.transaction_reference or payload.reference
                resp = _req.get(
                    f"{MONNIFY_BASE_URL}/api/v2/transactions/{tx_ref}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
                resp.raise_for_status()
                body = resp.json().get("responseBody", {})
                tx_status = body.get("paymentStatus") or body.get("transactionStatus", "")
                amount_paid = int(body.get("amountPaid", 0))
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Monnify verification failed: {e}")

            if tx_status.upper() != "PAID" and tx_status.upper() != "SUCCESS":
                raise HTTPException(status_code=400, detail=f"Payment not completed (status: {tx_status}).")
            if amount_paid < payment.amount:
                raise HTTPException(status_code=400, detail=f"Amount paid ({amount_paid}) less than required ({payment.amount}).")

            # Activate
            owner = approve_subscription_payment(db, payment, user)
            db.commit()
            return {
                "ok": True,
                "plan": normalize_plan(payment.plan),
                "expires_at": owner.subscription_expires_at.isoformat() if owner and owner.subscription_expires_at else None,
            }
        finally:
            db.close()

    # Public webhook — no auth required, verified by HMAC
    @app.post("/app/api/webhooks/monnify/subscription")
    async def web_monnify_subscription_webhook(request: Request):
        """Monnify webhook for subscription payments — auto-activates on PAID."""
        import requests as _req
        from subscriptions import approve_subscription_payment
        from models import SubscriptionPayment
        body_bytes = await request.body()
        sig_header = request.headers.get("monnify-signature", "")
        # Verify HMAC-SHA512
        secret = os.getenv("MONNIFY_SECRET_KEY", "")
        if secret and sig_header:
            import hmac as _hmac, hashlib as _hs
            expected = _hmac.new(secret.encode(), body_bytes, _hs.sha512).hexdigest()
            if not _hmac.compare_digest(expected, sig_header):
                raise HTTPException(status_code=401, detail="Invalid webhook signature.")
        try:
            data = json.loads(body_bytes)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON.")
        event_type   = data.get("eventType", "")
        event_data   = data.get("eventData", {})
        tx_status    = event_data.get("paymentStatus", "")
        pay_ref      = event_data.get("paymentReference", "")
        amount_paid  = int(event_data.get("amountPaid", 0))
        if "SUCCESSFUL" not in tx_status.upper() and "PAID" not in tx_status.upper():
            return {"ok": True, "ignored": True}
        db = SessionLocal()
        try:
            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.evidence_ref == pay_ref,
                SubscriptionPayment.payment_method == "MONNIFY",
                SubscriptionPayment.status == "PENDING",
            ).first()
            if not payment:
                return {"ok": True, "ignored": True, "reason": "unknown_ref"}
            if amount_paid < payment.amount:
                return {"ok": True, "ignored": True, "reason": "underpaid"}
            approve_subscription_payment(db, payment, admin_user=None)
            db.commit()
        finally:
            db.close()
        return {"ok": True}
