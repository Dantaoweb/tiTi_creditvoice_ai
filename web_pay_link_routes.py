"""
Pay links on the web (payment_links.py).

Public (no login — the customer opens it from WhatsApp):
  GET  /app/api/public/pay/{token}         what to pay, and where
  POST /app/api/public/pay/{token}/claim   "I've paid" → the owner is alerted

Business (owner and authorised staff confirm money, like refunds):
  GET  /app/api/payment-claims             waiting to be confirmed (and recent)
  POST /app/api/payment-claims/{id}/confirm   record it, send the receipt
  POST /app/api/payment-claims/{id}/reject    tell the customer it didn't arrive
  GET  /app/api/pay-links/...              the link, to copy and send
"""
import threading
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import SessionLocal
from models import Customer, Invoice, PaymentClaim, User
from web_auth import require_web_auth
from web_common import (
    _add_notification, _require_can_record, _send_web_receipt, _session_owner_phone, _session_user,
)

_hits = {}
_hits_lock = threading.Lock()


def _throttle(request: Request, limit=20, window=3600):
    """A public page: a few "I've paid" taps per hour from one place is plenty."""
    ip = (request.client.host if request.client else "?")
    now = time.time()
    with _hits_lock:
        hits = [t for t in _hits.get(ip, []) if now - t < window]
        if len(hits) >= limit:
            raise HTTPException(status_code=429, detail="Too many tries — please wait a little.")
        hits.append(now)
        _hits[ip] = hits


class ClaimRequest(BaseModel):
    amount: Optional[int] = None
    name: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=300)
    proof: Optional[str] = Field(default=None, max_length=2_100_000)   # data URL of the transfer photo


class ConfirmRequest(BaseModel):
    amount: Optional[int] = None


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=200)


def _require_confirmer(db, session):
    user = _session_user(db, session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    if user.parent_id is not None and not user.can_view_all_transactions:
        raise HTTPException(status_code=403, detail="Only the owner or an authorised staff member "
                                                    "can confirm payments.")
    return user


def register_pay_link_routes(app):
    from payment_links import (
        PayLinkError, claim, claim_row_dict, confirm, debt_pay_link, invoice_pay_link, page, reject,
    )

    @app.get("/app/api/public/pay/{token}")
    def public_pay_page(token: str):
        db = SessionLocal()
        try:
            try:
                return page(db, token)
            except PayLinkError as e:
                raise HTTPException(status_code=404, detail=str(e))
        finally:
            db.close()

    @app.post("/app/api/public/pay/{token}/claim")
    def public_pay_claim(token: str, payload: ClaimRequest, request: Request):
        _throttle(request)
        from whatsapp_client import send_whatsapp_message
        db = SessionLocal()
        try:
            try:
                c = claim(db, token, payload.amount, payload.name, payload.note, payload.proof)
            except PayLinkError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            who = c.payer_name or (claim_row_dict(db, c)["customer"]) or "A customer"
            title = f"{who} says they paid ₦{c.amount:,}"
            _add_notification(db, c.owner_phone, "payment_claim", title,
                              f"For {c.label}. Check your bank, then confirm it in Payments to confirm.",
                              link="/payment-claims")
            db.commit()
            try:
                send_whatsapp_message(c.owner_phone, f"*PAYMENT TO CONFIRM*\n\n{title} for {c.label}"
                                      + (f" — \"{c.note}\"" if c.note else "")
                                      + ".\n\nCheck your bank, then confirm it on the app: Payments to confirm.")
            except Exception:
                pass
            return {"ok": True, **page(db, token)}
        finally:
            db.close()

    # ── The business side ────────────────────────────────────────────────
    @app.get("/app/api/payment-claims")
    def web_payment_claims(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            rows = (db.query(PaymentClaim).filter(PaymentClaim.owner_phone == owner_phone)
                    .order_by(PaymentClaim.status != "pending", PaymentClaim.id.desc()).limit(100).all())
            return {"claims": [claim_row_dict(db, c) for c in rows],
                    "pending": sum(1 for c in rows if c.status == "pending")}
        finally:
            db.close()

    @app.get("/app/api/payment-claims/count")
    def web_payment_claims_count(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            n = db.query(PaymentClaim).filter(PaymentClaim.owner_phone == _session_owner_phone(db, session),
                                              PaymentClaim.status == "pending").count()
            return {"pending": n}
        finally:
            db.close()

    def _claim(db, session, claim_id):
        c = db.query(PaymentClaim).filter(PaymentClaim.id == claim_id,
                                          PaymentClaim.owner_phone == _session_owner_phone(db, session)).first()
        if not c:
            raise HTTPException(status_code=404, detail="Not found.")
        return c

    @app.get("/app/api/payment-claims/{claim_id}")
    def web_payment_claim(claim_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            return claim_row_dict(db, _claim(db, session, claim_id), with_proof=True)
        finally:
            db.close()

    @app.post("/app/api/payment-claims/{claim_id}/confirm")
    def web_confirm_claim(claim_id: int, payload: ConfirmRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_confirmer(db, session)
            _require_can_record(db, session, count_sale=False)
            c = _claim(db, session, claim_id)
            try:
                receipt_id = confirm(db, c, user.id, payload.amount)
            except PayLinkError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            _send_web_receipt(db, c.owner_phone, receipt_id)
            return claim_row_dict(db, c)
        finally:
            db.close()

    @app.post("/app/api/payment-claims/{claim_id}/reject")
    def web_reject_claim(claim_id: int, payload: RejectRequest, session: dict = Depends(require_web_auth)):
        from business_templates import business_display_name
        from whatsapp_client import send_whatsapp_message
        db = SessionLocal()
        try:
            user = _require_confirmer(db, session)
            c = _claim(db, session, claim_id)
            try:
                reject(db, c, user.id, payload.reason)
            except PayLinkError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            cust = db.query(Customer).filter(Customer.id == c.customer_id).first() if c.customer_id else None
            owner = db.query(User).filter(User.phone == c.owner_phone).first()
            if cust and cust.customer_phone:
                try:
                    send_whatsapp_message(
                        cust.customer_phone,
                        f"*{business_display_name(owner) if owner else 'The business'}*: we couldn't find your "
                        f"₦{c.amount:,} payment for {c.label}. {c.reject_reason}\n\nPlease check with your bank "
                        "or send us the transfer receipt.")
                except Exception:
                    pass
            return claim_row_dict(db, c)
        finally:
            db.close()

    @app.get("/app/api/pay-links/invoice/{invoice_id}")
    def web_invoice_pay_link(invoice_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            inv = db.query(Invoice).filter(Invoice.id == invoice_id,
                                           Invoice.owner_phone == _session_owner_phone(db, session)).first()
            if not inv:
                raise HTTPException(status_code=404, detail="Invoice not found.")
            return {"link": invoice_pay_link(db, inv)}
        finally:
            db.close()

    @app.get("/app/api/pay-links/customer/{customer_id}")
    def web_customer_pay_link(customer_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            cust = db.query(Customer).filter(Customer.id == customer_id,
                                             Customer.owner_phone == _session_owner_phone(db, session)).first()
            if not cust:
                raise HTTPException(status_code=404, detail="Customer not found.")
            return {"link": debt_pay_link(db, cust)}
        finally:
            db.close()
