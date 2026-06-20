from datetime import datetime, timedelta, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

from messages import get_plan_price
from models import Customer, SubscriptionPayment, User
from plans import (
    FEATURE_MIN_PLAN,
    PLAN_BASIC,
    PLAN_LIMITS,
    format_upgrade_message,
    normalize_plan,
    plan_allows_feature,
)


def get_business_owner_user(db, user):
    if not user:
        return None
    if user.parent_id:
        owner = db.query(User).filter(User.id == user.parent_id).first()
        if owner:
            return owner
    return user


def get_business_subscription(db, user):
    owner = get_business_owner_user(db, user)
    plan = normalize_plan(getattr(owner, "subscription_plan", PLAN_BASIC))
    status = (getattr(owner, "subscription_status", None) or "ACTIVE").upper()
    expires_at = getattr(owner, "subscription_expires_at", None)

    if expires_at and expires_at < _utcnow():
        status = "EXPIRED"
        # Persist the downgrade so the DB reflects reality
        if owner and plan != PLAN_BASIC:
            owner.subscription_plan = PLAN_BASIC
            owner.subscription_status = "EXPIRED"
            try:
                db.commit()
            except Exception:
                db.rollback()
        plan = PLAN_BASIC

    if status not in ["ACTIVE", "TRIAL"]:
        plan = PLAN_BASIC

    return {
        "owner": owner,
        "plan": plan,
        "status": status,
        "expires_at": expires_at,
        "limits": PLAN_LIMITS[plan],
    }


def ensure_feature_allowed(db, user, feature, feature_label):
    subscription = get_business_subscription(db, user)
    owner = subscription["owner"] or user
    required_plan = FEATURE_MIN_PLAN.get(feature, PLAN_BASIC)
    if plan_allows_feature(subscription["plan"], feature):
        return True, None
    return False, format_upgrade_message(
        subscription["plan"],
        required_plan,
        feature_label,
        owner,
        feature,
    )


def get_month_start():
    now = _utcnow()
    return datetime(now.year, now.month, 1)


def check_customer_limit(db, owner_phone, subscription):
    limit = subscription["limits"].get("customers")
    if limit is None:
        return True, None

    count = db.query(Customer).filter(
        Customer.owner_phone == owner_phone
    ).count()
    if count < limit:
        return True, None

    return False, (
        f"Basic plan customer limit reached ({limit}).\n\n"
        "Send UPGRADE to move to Go for unlimited customers."
    )


def check_thrift_participant_limit(db, owner_phone, subscription):
    limit = subscription["limits"].get("thrift_participants")
    if limit is None:
        return True, None

    count = db.query(Customer).filter(
        Customer.owner_phone == owner_phone
    ).count()
    if count < limit:
        return True, None

    return False, (
        f"BASIC allows up to {limit} thrift participants.\n\n"
        "Upgrade to GO for unlimited participants, contribution reminders, and participant history."
    )


def check_staff_limit(db, owner, subscription):
    limit = subscription["limits"].get("staff")
    if limit is None:
        return True, None

    count = db.query(User).filter(User.parent_id == owner.id).count()
    if count < limit:
        return True, None

    return False, (
        f"Your {subscription['plan']} plan allows {limit} staff.\n\n"
        "Send UPGRADE to see team options."
    )


def create_subscription_payment_request(db, user, plan):
    owner = get_business_owner_user(db, user)
    plan = normalize_plan(plan)
    amount = get_plan_price(plan)

    existing = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.user_id == owner.id,
        SubscriptionPayment.status == "PENDING"
    ).order_by(
        SubscriptionPayment.created_at.desc()
    ).first()

    if existing:
        existing.plan = plan
        existing.amount = amount
        existing.phone = owner.phone
        existing.payment_method = "BANK_TRANSFER"
        existing.evidence_type = None
        existing.evidence_ref = None
        existing.created_at = _utcnow()
        return existing

    payment = SubscriptionPayment(
        user_id=owner.id,
        phone=owner.phone,
        plan=plan,
        amount=amount,
        status="PENDING",
        payment_method="BANK_TRANSFER"
    )
    db.add(payment)
    db.flush()
    return payment


def get_pending_subscription_payment(db, user):
    owner = get_business_owner_user(db, user)
    if not owner:
        return None
    return db.query(SubscriptionPayment).filter(
        SubscriptionPayment.user_id == owner.id,
        SubscriptionPayment.status == "PENDING"
    ).order_by(
        SubscriptionPayment.created_at.desc()
    ).first()


def approve_subscription_payment(db, payment, admin_user):
    owner = db.query(User).filter(User.id == payment.user_id).first()
    if not owner:
        return None

    owner.subscription_plan = normalize_plan(payment.plan)
    owner.subscription_status = "ACTIVE"
    owner.subscription_expires_at = _utcnow() + timedelta(days=30)
    payment.status = "APPROVED"
    payment.approved_at = _utcnow()
    payment.approved_by_user_id = admin_user.id if admin_user else None
    return owner


def app_user_effective_plan(user):
    status = (getattr(user, "subscription_status", None) or "ACTIVE").upper()
    expires_at = getattr(user, "subscription_expires_at", None)
    if expires_at and expires_at < _utcnow():
        return "EXPIRED"
    if status not in ["ACTIVE", "TRIAL"]:
        return status
    return normalize_plan(getattr(user, "subscription_plan", PLAN_BASIC))


def get_business_users_by_effective_plan(db, plan):
    users = db.query(User).filter(User.parent_id == None).order_by(
        User.created_at.desc()
    ).all()
    return [
        user
        for user in users
        if app_user_effective_plan(user) == plan
    ]
