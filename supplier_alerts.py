"""
Supplier connection requests that nobody answers.

A request is passed straight to the supplier, who accepts or declines. One the
supplier ignores leaves the buyer waiting with no answer, so after a few days
the supplier is reminded once and the admins are told — they can chase the
supplier or block the request. Those requests count as waiting on the
Suppliers tab until the supplier answers or an admin blocks them.
"""
from datetime import timedelta

STALE_DAYS = 3


def _cutoff():
    from models import utcnow
    return utcnow() - timedelta(days=STALE_DAYS)


def stale_supplier_requests(db):
    """Requests still waiting on the supplier after STALE_DAYS."""
    from models import SupplierContactMessage
    return db.query(SupplierContactMessage).filter(
        SupplierContactMessage.connection_status == "forwarded",
        SupplierContactMessage.created_at < _cutoff(),
    ).count()


def check_unanswered_supplier_requests(db):
    """Scheduler check: remind the supplier once and tell the admins."""
    from admin_alerts import notify_admins
    from models import SupplierContactMessage, User, VerifiedSupplier, utcnow
    from proactive_scheduler import _notify

    rows = db.query(SupplierContactMessage).filter(
        SupplierContactMessage.connection_status == "forwarded",
        SupplierContactMessage.created_at < _cutoff(),
        SupplierContactMessage.reminded_at.is_(None),
    ).all()
    for m in rows:
        # Stamp first: a failed send must not repeat the reminder every cycle.
        m.reminded_at = utcnow()
        db.commit()
        vs = db.query(VerifiedSupplier).filter(VerifiedSupplier.id == m.supplier_id).first()
        if not vs:
            continue
        sup = db.query(User).filter(User.phone == vs.owner_phone).first()
        sup_name = (sup.business_type_label or sup.name) if sup else vs.owner_phone
        buyer = m.from_business_name or "A buyer"
        interest = f" for {m.product_interest}" if m.product_interest else ""
        try:
            _notify(db, vs.owner_phone, "supplier_enquiry_reminder",
                    "⏰ A buyer is waiting for your answer",
                    f"{buyer} asked to connect{interest} {STALE_DAYS}+ days ago. "
                    "Accept or decline it on your Supplier Profile so they are not left waiting.",
                    link="/suppliers")
        except Exception:
            pass
        notify_admins(
            db, "supplier_enquiry_stale", "Supplier hasn't answered",
            f"{sup_name} has not answered {buyer}'s request{interest} for {STALE_DAYS}+ days. "
            "They were reminded; chase them or block the request.",
            tab="Suppliers",
        )
