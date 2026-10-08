"""
Who hears what as a finance application moves.

Three people care about an application and none of them sat watching it:
  • the admins — a new request waits at SUBMITTED until one of them shares
    it, a claimed repayment waits to be confirmed, and a financier's move can
    make our fee due;
  • the business — whether its request was sent, approved, declined (and
    why) or delivered;
  • the financier — a request shared with them, a repayment they should
    confirm, a request withdrawn. Their portal has no bell, so they are
    reached on WhatsApp and email.

Every function here is best-effort: an alert that fails must never undo the
change it was about.
"""
import logging
import os

from admin_alerts import notify_admins

_log = logging.getLogger(__name__)

# What the business is told when its request reaches each stage.
_BUSINESS_UPDATES = {
    "SHARED":    ("📨 Finance request sent",
                  "Your request {code} was sent to {partner}. They will review it and contact you."),
    "IN_REVIEW": ("🔎 Finance request in review",
                  "{partner} is reviewing your request {code}."),
    "APPROVED":  ("🎉 Finance request approved",
                  "{partner} approved your request {code}."),
    "DECLINED":  ("Update on your finance request",
                  "{partner} could not approve your request {code} this time."),
    "DELIVERED": ("✅ Asset delivered",
                  "{partner} marked your request {code} as delivered. Record each repayment "
                  "on your Scorecard page as you pay."),
}


def _label(application):
    return application.business_name or application.owner_phone


def pending_finance_count(db):
    """Requests waiting to be shared, plus repayments waiting to be confirmed."""
    from finance_installments import CLAIMED
    from models import FinanceApplication, SupplierPayment, SupplierPurchase
    submitted = db.query(FinanceApplication).filter(FinanceApplication.status == "SUBMITTED").count()
    claimed = (
        db.query(SupplierPayment)
        .join(SupplierPurchase, SupplierPayment.purchase_id == SupplierPurchase.id)
        .filter(SupplierPurchase.finance_application_id.isnot(None),
                SupplierPayment.verification == CLAIMED)
        .count()
    )
    return submitted + claimed


def tell_admins(db, event_type, title, body):
    notify_admins(db, event_type, title, body, tab="Finance")


def tell_business(db, application, partner):
    """The business hears its request moved to a new stage."""
    update = _BUSINESS_UPDATES.get(application.status)
    if not update:
        return
    try:
        from proactive_scheduler import _notify
        title, line = update
        body = line.format(code=application.application_code,
                           partner=partner.name if partner else "The financier")
        if application.status == "DECLINED" and application.decline_reason:
            body += f"\n\nReason: {application.decline_reason}"
        _notify(db, application.owner_phone, "finance_status", title, body, link="/scorecard")
    except Exception:
        _log.exception("could not tell the business about %s", application.application_code)


def tell_financier(db, application, partner, title, line):
    """Every active login at the financier, on WhatsApp (when live) and email."""
    if not partner:
        return
    try:
        from models import FinancierUser
        users = db.query(FinancierUser).filter(
            FinancierUser.finance_partner_id == partner.id,
            FinancierUser.is_active == True,  # noqa: E712
        ).all()
        if not users:
            return
        base = os.getenv("APP_BASE_URL", "").rstrip("/")
        text = (f"*{title}*\n\n{line}\n\n"
                f"Open it in your CreditVoice portal: {base}/financier")
        from feature_flags import whatsapp_live
        live = whatsapp_live(db)
        for u in users:
            if live and u.phone:
                try:
                    from whatsapp_client import send_whatsapp_message
                    send_whatsapp_message(u.phone, text)
                except Exception:
                    _log.exception("financier WhatsApp failed")
            if u.email:
                try:
                    from email_service import send_email
                    plain = text.replace("*", "")
                    safe = plain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    send_email(u.email, f"[CreditVoice] {title}",
                               f'<pre style="font-family:inherit;font-size:14px">{safe}</pre>', plain)
                except Exception:
                    _log.exception("financier email failed")
    except Exception:
        _log.exception("could not tell the financier about %s", application.application_code)


def after_stage_change(db, application, partner, old_status, moved_by="admin"):
    """Everyone who should hear about a stage change, hears it."""
    if application.status == old_status:
        return
    tell_business(db, application, partner)
    code = application.application_code
    if application.status == "SHARED":
        tell_financier(
            db, application, partner, "New finance request",
            f"{_label(application)} ({code}) would like "
            f"{application.asset_requested or 'financing'}"
            + (f" worth N{application.asset_value:,}" if application.asset_value else "")
            + ". Their scorecard is attached in the portal.",
        )
    if moved_by == "financier":
        # Our fee can become due on the financier's move, so the admins watch these.
        tell_admins(
            db, "finance_financier_update",
            f"{partner.name if partner else 'Financier'} → {application.status.replace('_', ' ').title()}",
            f"{partner.name if partner else 'The financier'} moved {_label(application)} ({code}) "
            f"to {application.status.replace('_', ' ').lower()}"
            + (f". Reason: {application.decline_reason}" if application.status == "DECLINED"
               and application.decline_reason else "") + ".",
        )
