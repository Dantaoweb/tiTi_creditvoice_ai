from datetime import datetime, timedelta, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Days a paid plan keeps working after its expiry date before dropping to Basic.
SUBSCRIPTION_GRACE_DAYS = 3

from messages import get_plan_price
from models import Customer, SubscriptionPayment, Transaction, User
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
        if _utcnow() < expires_at + timedelta(days=SUBSCRIPTION_GRACE_DAYS):
            # Grace window: the paid plan keeps working for a few days past
            # expiry so a late renewal doesn't disrupt the business.
            status = "GRACE"
        else:
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

    if status not in ["ACTIVE", "TRIAL", "GRACE"]:
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


def staff_recording_allowed(db, user):
    """True if this user may record sales/payments. Owners always may; a staff
    sub-account may only when the business plan includes staff (Pro/Premium).
    So when a business lapses to Basic, its staff can no longer record — the
    business behaves like a plain Basic account (owner-only)."""
    from plans import plan_allows_feature
    if not user or getattr(user, "parent_id", None) is None:
        return True
    subscription = get_business_subscription(db, user)
    return plan_allows_feature(subscription["plan"], "STAFF")


def staff_record_block_message(user, subscription):
    """Return a WhatsApp block message if a staff sub-account may not record
    under the given (already-resolved) subscription dict, else None. Owners are
    never blocked."""
    from plans import plan_allows_feature
    if not user or getattr(user, "parent_id", None) is None:
        return None
    if plan_allows_feature((subscription or {}).get("plan"), "STAFF"):
        return None
    return ("Your business is on the Basic plan, so staff cannot record sales. "
            "Please ask the owner to renew to Pro or Premium.")


def get_month_start():
    now = _utcnow()
    return datetime(now.year, now.month, 1)


def monthly_transaction_count(db, owner_phone):
    """Non-voided transactions the business recorded in the current month."""
    from reports import get_owner_transaction_query
    return get_owner_transaction_query(db, owner_phone).filter(
        Transaction.created_at >= get_month_start()
    ).count()


def monthly_transaction_usage(db, owner_phone, subscription):
    """(count, limit, remaining) for the current month. limit/remaining are None
    when the plan is unlimited. Used for the approaching-limit warning."""
    limit = subscription["limits"].get("monthly_transactions")
    count = monthly_transaction_count(db, owner_phone)
    remaining = None if limit is None else max(0, limit - count)
    return count, limit, remaining


def check_monthly_transaction_limit(db, owner_phone, subscription):
    """(allowed, message). Blocks a new sale once the month's transaction cap is
    reached (Basic = 100). Unlimited plans always pass."""
    limit = subscription["limits"].get("monthly_transactions")
    if limit is None:
        return True, None
    if monthly_transaction_count(db, owner_phone) < limit:
        return True, None
    return False, (
        f"You've reached the Basic plan limit of {limit} transactions this month. "
        "Upgrade to Go for unlimited transactions."
    )


def check_monthly_invoice_limit(db, owner_phone, subscription):
    limit = subscription["limits"].get("monthly_invoice_uses")
    if limit is None:
        return True, None
    count = (
        db.query(Transaction)
        .join(Customer, Transaction.customer_id == Customer.id)
        .filter(
            Customer.owner_phone == owner_phone,
            Transaction.is_invoice == True,
            Transaction.created_at >= get_month_start(),
        )
        .count()
    )
    if count < limit:
        return True, None
    return False, (
        f"You've used {limit} multi-item invoices this month (Basic limit).\n\n"
        "Upgrade to Go for unlimited invoice-style transactions."
    )


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


def check_thrift_group_limit(db, owner_phone, subscription):
    """Whether the user can create/keep another savings group under their plan.
    Only ACTIVE groups count, so a completed group frees a slot."""
    from models import ThriftGroup
    limit = subscription["limits"].get("thrift_groups")
    if limit is None:
        return True, None
    count = db.query(ThriftGroup).filter(
        ThriftGroup.owner_phone == owner_phone,
        ThriftGroup.status == "active",
    ).count()
    if count < limit:
        return True, None
    return False, (
        f"Your {subscription['plan']} plan allows {limit} savings groups.\n\n"
        "Upgrade to run more groups (and unlock target/goal groups)."
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


def check_branch_limit(db, owner, subscription):
    """True if the owner can add another branch under their plan.

    Pro allows 1 branch; Premium is unlimited (limit None)."""
    from models import Branch
    limit = subscription["limits"].get("branches")
    if limit is None:
        return True, None

    count = db.query(Branch).filter(Branch.owner_phone == owner.phone).count()
    if count < limit:
        return True, None

    return False, (
        f"Your {subscription['plan']} plan allows {limit} "
        f"branch{'es' if limit != 1 else ''}.\n\n"
        "Upgrade to Premium for unlimited branches."
    )


# Partnership roles bucket into two caps: investor-type roles (investor, silent
# investor) count against "investors"; everyone else (partner, co-founder)
# counts against "partners".
_INVESTOR_ROLES = ("investor", "silent")


def _partner_bucket(role):
    return "investor" if str(role).lower() in _INVESTOR_ROLES else "partner"


def check_partner_limit(db, owner, subscription, role="partner"):
    """True if the owner can add another partner/investor under their plan.

    Counted per bucket: Pro allows 1 partner AND 1 investor; Premium is
    unlimited. Pending and active records both count against the cap."""
    from models import BusinessPartner
    bucket = _partner_bucket(role)
    key = "investors" if bucket == "investor" else "partners"
    label = "investor" if bucket == "investor" else "partner"
    limit = subscription["limits"].get(key)
    if limit is None:
        return True, None

    rows = db.query(BusinessPartner).filter(
        BusinessPartner.owner_phone == owner.phone,
        BusinessPartner.status.in_(["active", "pending"]),
    ).all()
    count = sum(1 for r in rows if _partner_bucket(r.role) == bucket)
    if count < limit:
        return True, None

    return False, (
        f"Your {subscription['plan']} plan allows {limit} {label}"
        f"{'s' if limit != 1 else ''}.\n\n"
        f"Upgrade to Premium for unlimited {label}s."
    )


def create_subscription_payment_request(db, user, plan, period="MONTHLY"):
    from plans import normalize_period
    owner = get_business_owner_user(db, user)
    plan = normalize_plan(plan)
    period = normalize_period(period)
    amount = get_plan_price(plan, period)

    existing = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.user_id == owner.id,
        SubscriptionPayment.status == "PENDING"
    ).order_by(
        SubscriptionPayment.created_at.desc()
    ).first()

    if existing:
        existing.plan = plan
        existing.amount = amount
        existing.billing_period = period
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
        billing_period=period,
        status="PENDING",
        payment_method="BANK_TRANSFER"
    )
    db.add(payment)
    db.flush()
    return payment


def create_monnify_subscription_link(db, user, plan, period="MONTHLY"):
    """Create/reuse a pending subscription payment as a Monnify online payment
    and return (payment, checkout_url). checkout_url is None when Monnify is
    unavailable, in which case the caller should fall back to bank transfer.

    Uses the same CV-SUB-<id>-<rand> reference scheme as the web Monnify flow,
    stored on evidence_ref so /app/api/webhooks/monnify/subscription activates
    the plan automatically on payment."""
    import uuid as _uuid
    from wallet_service import create_monnify_checkout

    owner = get_business_owner_user(db, user)
    payment = create_subscription_payment_request(db, user, plan, period)
    payment.payment_method = "MONNIFY"
    db.flush()
    ref = f"CV-SUB-{payment.id}-{_uuid.uuid4().hex[:6].upper()}"
    payment.evidence_ref = ref

    email = getattr(owner, "email", None) or f"{owner.phone}@creditvoice.app"
    _term = "1 year" if (payment.billing_period or "MONTHLY").upper() == "YEARLY" else "1 month"
    checkout_url = create_monnify_checkout(
        reference=ref,
        amount=payment.amount,
        customer_name=(owner.name or owner.phone),
        customer_email=email,
        description=f"CreditVoice {payment.plan} Plan - {_term}",
    )
    return payment, checkout_url


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
    # Idempotency guard — reject if already approved so a duplicate admin
    # command can never upgrade the subscription a second time.
    if payment.status != "PENDING":
        return None

    owner = db.query(User).filter(User.id == payment.user_id).first()
    if not owner:
        return None

    from plans import period_days
    owner.subscription_plan = normalize_plan(payment.plan)
    owner.subscription_status = "ACTIVE"
    owner.subscription_expires_at = _utcnow() + timedelta(days=period_days(payment.billing_period))
    payment.status = "APPROVED"
    payment.approved_at = _utcnow()
    payment.approved_by_user_id = admin_user.id if admin_user else None
    return owner


def app_user_effective_plan(user):
    status = (getattr(user, "subscription_status", None) or "ACTIVE").upper()
    expires_at = getattr(user, "subscription_expires_at", None)
    if expires_at and expires_at < _utcnow():
        # Only "expired" once the grace window has also passed.
        if _utcnow() >= expires_at + timedelta(days=SUBSCRIPTION_GRACE_DAYS):
            return "EXPIRED"
    if status not in ["ACTIVE", "TRIAL", "GRACE"]:
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
