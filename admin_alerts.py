"""
Telling the app admins that something is waiting for them.

Every admin is reached — the APP_ADMIN_PHONES allow-list AND admins granted
from the app (AppAdminRole), less any who were denied — and each alert lands
on the phone their account actually uses, whichever format (0809… or
234809…) the allow-list was written in. Otherwise the alert is saved under a
number nobody logs in with and never shows in anyone's bell.

An alert goes to the bell and as a phone push, and tapping it opens the admin
tab where the work is (`/admin?tab=Suppliers`). It never raises: an alert that
fails must not lose the thing it was about.
"""
import logging

_log = logging.getLogger(__name__)


def admin_phones(db):
    """The account phone of every active app admin."""
    from admin import ROLE_APP_ADMIN, app_admin_phones, is_app_admin
    from models import AppAdminRole, User
    from web_auth import phone_candidates

    listed = set(app_admin_phones())
    for r in db.query(AppAdminRole).filter(
        AppAdminRole.role == ROLE_APP_ADMIN, AppAdminRole.is_active == True,  # noqa: E712
    ).all():
        if r.phone:
            listed.add(r.phone)

    candidates = set()
    for p in listed:
        candidates.update(phone_candidates(p))
    if not candidates:
        return []
    users = db.query(User).filter(User.phone.in_(list(candidates))).all()
    # is_app_admin honours a denial made from the app over the allow-list.
    return sorted({u.phone for u in users if u.phone and is_app_admin(u.phone, db)})


def notify_admins(db, event_type, title, body, tab=None):
    """Bell + push to every app admin. `tab` is the admin tab to open."""
    try:
        from web_common import _add_notification
        link = f"/admin?tab={tab}" if tab else "/admin"
        phones = admin_phones(db)
        for phone in phones:
            _add_notification(db, phone, event_type, title, body, link=link)
        if phones:
            db.commit()
        return phones
    except Exception:
        _log.exception("could not notify the admins: %s", title)
        try:
            db.rollback()
        except Exception:
            pass
        return []


def pending_payments(db):
    """Bank transfers the business says it made, not yet approved or rejected.
    A request opened just to see the bank details is not counted."""
    from models import SubscriptionPayment
    return db.query(SubscriptionPayment).filter(
        SubscriptionPayment.status == "PENDING",
        SubscriptionPayment.paid_reported_at.isnot(None),
    ).count()


def pending_opportunity_applications(db):
    from models import OpportunityApplication
    return db.query(OpportunityApplication).filter(OpportunityApplication.status == "submitted").count()


def pending_supplier_applications(db):
    from models import VerifiedSupplier
    return db.query(VerifiedSupplier).filter(VerifiedSupplier.verification_status == "pending").count()
