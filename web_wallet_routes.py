"""
Wallet routes: summary, interest/waitlist, manual payment match, the public
Monnify payment webhook, and reserved-account provisioning.

Split out of web_routes.py. Register with register_wallet_routes(app);
shared helpers come from web_common / webhook_context.
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from database import SessionLocal
from models import User
from web_auth import require_web_auth
from webhook_context import load_webhook_user_context


class WalletMatchRequest(BaseModel):
    wallet_tx_id: int
    customer_id: int


def register_wallet_routes(app):

    @app.get("/app/api/wallet")
    def web_wallet(session: dict = Depends(require_web_auth)):
        from wallet_service import get_wallet_summary
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            return get_wallet_summary(db, owner_phone)
        finally:
            db.close()

    @app.post("/app/api/wallet/interest")
    def web_wallet_interest(session: dict = Depends(require_web_auth)):
        """Register owner as interested — shown on the coming-soon page."""
        from wallet_service import register_waitlist
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            register_waitlist(db, owner_phone)
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/wallet/match")
    def web_wallet_match(
        payload: WalletMatchRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Manually match an unmatched inbound payment to a customer."""
        from wallet_service import manually_match_payment
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            tx, err = manually_match_payment(
                db,
                payload.wallet_tx_id,
                payload.customer_id,
                owner_phone,
            )
            if err:
                raise HTTPException(status_code=400, detail=err)
            return {"ok": True, "transaction_id": tx.id}
        finally:
            db.close()

    # ── Monnify payment webhook ───────────────────────────────────────────────
    @app.post("/webhook/payment-received")
    async def webhook_payment_received(request):
        """
        Monnify calls this on every SUCCESSFUL_TRANSACTION for a reserved account.
        Header: monnify-signature — HMAC-SHA512 of raw body using your Secret Key.
        """
        from wallet_service import process_incoming_payment, resolve_bank_name, verify_webhook_signature
        from whatsapp_client import send_whatsapp_message

        body = await request.body()
        sig  = request.headers.get("monnify-signature", "")

        if not verify_webhook_signature(body, sig):
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

        import json as _json
        data      = _json.loads(body)
        event     = data.get("eventType", "")
        event_data = data.get("eventData", {})

        # ── Settlement confirmation (Layer 3) ────────────────────────────────
        if event == "SETTLEMENT_COMPLETED":
            # Monnify fields: reservedAccountReference = owner_phone we set
            owner_phone = (
                event_data.get("reservedAccountReference")
                or event_data.get("accountReference")
                or ""
            )
            settled    = int(float(event_data.get("totalAmount") or event_data.get("settledAmount") or 0))
            dest_bank  = resolve_bank_name(event_data.get("destinationBankCode", "")) \
                         or event_data.get("destinationBankName", "your bank")
            dest_name  = event_data.get("destinationAccountName", "")

            if owner_phone and settled:
                send_whatsapp_message(
                    owner_phone,
                    f"✅ ₦{settled:,} has been sent to your {dest_bank} account"
                    + (f" ({dest_name})" if dest_name else "") + ".\n"
                    "This covers payments collected up to yesterday.\n"
                    "Check your bank for the credit alert."
                )
            return {"ok": True, "event": event}

        # ── Inbound payment (Layer 1) ─────────────────────────────────────────
        if event != "SUCCESSFUL_TRANSACTION":
            return {"ok": True, "skipped": event}
        if event_data.get("paymentStatus") != "PAID":
            return {"ok": True, "skipped": "not paid"}

        # Parse Monnify payload
        ref       = event_data.get("transactionReference", "")
        narration = event_data.get("paymentDescription", "")
        amount    = int(float(event_data.get("amountPaid", 0)))

        # Owner identified from the accountReference we set during provisioning
        owner_phone = event_data.get("product", {}).get("reference", "")

        # Sender details come from paymentSourceInformation array
        src       = (event_data.get("paymentSourceInformation") or [{}])[0]
        sender    = src.get("accountName", "")
        s_acct    = src.get("accountNumber", "")
        s_bank    = resolve_bank_name(src.get("bankCode", ""))

        # Destination account number (the business's reserved account)
        dest_info = event_data.get("destinationAccountInformation", {})
        va_number = dest_info.get("accountNumber", "")

        if not owner_phone or not amount or not ref:
            raise HTTPException(status_code=400, detail="Missing required fields.")

        db = SessionLocal()
        try:
            from models import Wallet
            # Prefer lookup by owner_phone (set as accountReference); fall back to VA number
            wallet = db.query(Wallet).filter(Wallet.owner_phone == owner_phone).first()
            if not wallet and va_number:
                wallet = db.query(Wallet).filter(Wallet.virtual_account_number == va_number).first()
            if not wallet:
                raise HTTPException(status_code=404, detail="Wallet not found.")

            tx = process_incoming_payment(
                db, wallet.owner_phone, amount, sender, s_bank, narration, ref, s_acct
            )

            match_note = ""
            unmatched_note = ""
            if tx.matched_customer_id:
                from models import Customer as _Customer
                from sqlalchemy import func as _func
                c = db.query(_Customer).filter(_Customer.id == tx.matched_customer_id).first()
                if c:
                    # Compute remaining balance for that customer
                    from models import Transaction as _Tx
                    total_owed = db.query(_func.coalesce(_func.sum(_Tx.amount), 0)).filter(
                        _Tx.customer_id == c.id, _Tx.type == "BUY", _Tx.is_voided != True
                    ).scalar() or 0
                    total_paid = db.query(_func.coalesce(_func.sum(_Tx.amount), 0)).filter(
                        _Tx.customer_id == c.id, _Tx.type == "PAY", _Tx.is_voided != True
                    ).scalar() or 0
                    balance = max(0, int(total_owed) - int(total_paid))
                    balance_line = f"\nBalance remaining: ₦{balance:,}" if balance > 0 else "\nAccount fully cleared ✅"
                    match_note = f"\nMatched to *{c.name.title()}* and recorded as payment.{balance_line}"
            else:
                unmatched_note = "\n\nNo customer matched — open the Wallet to assign this payment."

            send_whatsapp_message(
                wallet.owner_phone,
                f"💰 *Payment received: ₦{amount:,}*\n"
                f"From: {sender or 'Unknown'} ({s_bank})\n"
                f"Ref: {ref}"
                f"{match_note}{unmatched_note}"
            )
            return {"ok": True, "reference": tx.reference}
        finally:
            db.close()

    # ── Admin: provision a Monnify reserved account for an owner ─────────────
    @app.post("/app/api/wallet/provision")
    def web_wallet_provision(session: dict = Depends(require_web_auth)):
        """
        Owner calls this once to create their reserved account on Monnify.
        Safe to call again — returns existing details if already provisioned.
        """
        from wallet_service import provision_virtual_account
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            owner = db.query(User).filter(User.phone == owner_phone).first()
            if not owner:
                raise HTTPException(status_code=404, detail="Owner not found.")
            result = provision_virtual_account(db, owner_phone, owner.name or owner_phone)
            return {"ok": True, **result}
        finally:
            db.close()
