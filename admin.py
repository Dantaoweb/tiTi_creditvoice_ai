from sqlalchemy import func

from models import AppAdminRole, SubscriptionPayment, User
from plans import PLAN_BASIC, PLAN_GO, PLAN_PRO, normalize_plan
from subscriptions import (
    app_user_effective_plan,
    get_business_users_by_effective_plan,
    get_month_start,
)


def format_admin_roles(db):
    roles = db.query(AppAdminRole).order_by(
        AppAdminRole.role.asc(),
        AppAdminRole.created_at.desc()
    ).all()

    if not roles:
        return "No WhatsApp-managed admin roles yet."

    msg = "WhatsApp-Managed Admin Roles\n\n"
    for index, role in enumerate(roles[:30], start=1):
        status = "Active" if role.is_active else "Denied"
        msg += (
            f"{index}. {role.phone}\n"
            f"Role: {role.role}\n"
            f"Status: {status}\n\n"
        )
    if len(roles) > 30:
        msg += f"...and {len(roles) - 30:,} more."
    return msg.strip()


def format_pending_subscriptions(payments):
    if not payments:
        return "No pending subscription payments."

    msg = "Pending Subscription Payments\n\n"
    for index, (payment, owner) in enumerate(payments, start=1):
        evidence = "yes" if payment.evidence_ref else "no"
        owner_name = owner.name.title() if owner and owner.name else payment.phone
        msg += (
            f"{index}. {owner_name}\n"
            f"Phone: {payment.phone}\n"
            f"Plan: {payment.plan}\n"
            f"Amount: N{payment.amount:,}\n"
            f"Evidence: {evidence}\n\n"
        )
    return msg.strip()


def get_app_dashboard_summary(db):
    users = db.query(User).all()
    business_users = [user for user in users if not user.parent_id]
    staff_users = [user for user in users if user.parent_id]
    plan_counts = {
        PLAN_BASIC: 0,
        PLAN_GO: 0,
        PLAN_PRO: 0,
        "EXPIRED": 0,
        "PAST_DUE": 0,
    }

    for user in business_users:
        effective_plan = app_user_effective_plan(user)
        if effective_plan not in plan_counts:
            plan_counts[effective_plan] = 0
        plan_counts[effective_plan] += 1

    pending_count = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.status == "PENDING"
    ).count()
    pending_amount = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
        SubscriptionPayment.status == "PENDING"
    ).scalar()

    month_start = get_month_start()
    approved_month_count = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.status == "APPROVED",
        SubscriptionPayment.approved_at >= month_start
    ).count()
    approved_month_amount = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
        SubscriptionPayment.status == "APPROVED",
        SubscriptionPayment.approved_at >= month_start
    ).scalar()

    return {
        "total_users": len(users),
        "business_users": len(business_users),
        "staff_users": len(staff_users),
        "active_staff": len([user for user in staff_users if user.role == "delegate"]),
        "pending_staff": len([user for user in staff_users if user.role == "delegate_pending"]),
        "plan_counts": plan_counts,
        "pending_count": pending_count,
        "pending_amount": pending_amount,
        "approved_month_count": approved_month_count,
        "approved_month_amount": approved_month_amount,
    }


def build_app_admin_dashboard_message(db):
    summary = get_app_dashboard_summary(db)
    plan_counts = summary["plan_counts"]
    return (
        "CreditVoice App Admin Dashboard\n\n"
        f"Total users: {summary['total_users']:,}\n"
        f"Business accounts: {summary['business_users']:,}\n"
        f"Staff accounts: {summary['staff_users']:,}\n"
        f"Active staff: {summary['active_staff']:,}\n"
        f"Pending staff: {summary['pending_staff']:,}\n\n"
        f"FREE/BASIC users: {plan_counts.get(PLAN_BASIC, 0):,}\n"
        f"GO users: {plan_counts.get(PLAN_GO, 0):,}\n"
        f"PRO users: {plan_counts.get(PLAN_PRO, 0):,}\n"
        f"Expired users: {plan_counts.get('EXPIRED', 0):,}\n\n"
        f"Pending upgrades: {summary['pending_count']:,} (N{summary['pending_amount']:,})\n"
        f"Approved this month: {summary['approved_month_count']:,} (N{summary['approved_month_amount']:,})\n\n"
        "Reply with:\n"
        "1. Summary\n"
        "2. PRO users\n"
        "3. GO users\n"
        "4. FREE users\n"
        "5. Expired users\n"
        "6. Pending upgrades\n"
        "7. Approved this month\n"
        "8. Recent users\n"
        "9. Revenue summary\n\n"
        "Send exit or cancel to close."
    )


def format_user_list(users, title):
    if not users:
        return f"{title}\n\nNo users found."

    msg = f"{title}\n\n"
    for index, user in enumerate(users[:20], start=1):
        expires = user.subscription_expires_at.strftime("%d/%m/%Y") if user.subscription_expires_at else "No expiry"
        name = user.name.title() if user.name else "Unnamed"
        msg += (
            f"{index}. {name}\n"
            f"Phone: {user.phone}\n"
            f"Plan: {normalize_plan(user.subscription_plan)}\n"
            f"Status: {app_user_effective_plan(user)}\n"
            f"Expires: {expires}\n\n"
        )
    if len(users) > 20:
        msg += f"...and {len(users) - 20:,} more."
    return msg.strip()


def build_app_admin_selection_message(db, selection):
    normalized = str(selection).lower().strip()
    if normalized in ["1", "summary"]:
        return "app_admin_summary", build_app_admin_dashboard_message(db)

    if normalized in ["2", "pro", "pro users"]:
        return "app_admin_pro_users", format_user_list(
            get_business_users_by_effective_plan(db, PLAN_PRO),
            "PRO Users"
        )

    if normalized in ["3", "go", "go users"]:
        return "app_admin_go_users", format_user_list(
            get_business_users_by_effective_plan(db, PLAN_GO),
            "GO Users"
        )

    if normalized in ["4", "free", "basic", "free users", "basic users"]:
        return "app_admin_free_users", format_user_list(
            get_business_users_by_effective_plan(db, PLAN_BASIC),
            "FREE/BASIC Users"
        )

    if normalized in ["5", "expired", "expired users"]:
        return "app_admin_expired_users", format_user_list(
            get_business_users_by_effective_plan(db, "EXPIRED"),
            "Expired Users"
        )

    if normalized in ["6", "pending", "pending upgrades"]:
        payments = db.query(SubscriptionPayment, User).outerjoin(
            User,
            SubscriptionPayment.user_id == User.id
        ).filter(
            SubscriptionPayment.status == "PENDING"
        ).order_by(
            SubscriptionPayment.created_at.asc()
        ).all()
        return "app_admin_pending_upgrades", format_pending_subscriptions(payments)

    if normalized in ["7", "approved", "approved this month"]:
        payments = db.query(SubscriptionPayment, User).outerjoin(
            User,
            SubscriptionPayment.user_id == User.id
        ).filter(
            SubscriptionPayment.status == "APPROVED",
            SubscriptionPayment.approved_at >= get_month_start()
        ).order_by(
            SubscriptionPayment.approved_at.desc()
        ).limit(20).all()
        if not payments:
            return "app_admin_approved_month", "No approved subscriptions this month."
        msg = "Approved This Month\n\n"
        for index, (payment, owner) in enumerate(payments, start=1):
            name = owner.name.title() if owner and owner.name else payment.phone
            approved_at = payment.approved_at.strftime("%d/%m/%Y") if payment.approved_at else "Unknown date"
            msg += (
                f"{index}. {name}\n"
                f"Phone: {payment.phone}\n"
                f"Plan: {payment.plan}\n"
                f"Amount: N{payment.amount:,}\n"
                f"Approved: {approved_at}\n\n"
            )
        return "app_admin_approved_month", msg.strip()

    if normalized in ["8", "recent", "recent users"]:
        users = db.query(User).filter(User.parent_id == None).order_by(
            User.created_at.desc()
        ).limit(20).all()
        return "app_admin_recent_users", format_user_list(users, "Recent Business Users")

    if normalized in ["9", "revenue", "revenue summary"]:
        total_approved = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
            SubscriptionPayment.status == "APPROVED"
        ).scalar()
        month_approved = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
            SubscriptionPayment.status == "APPROVED",
            SubscriptionPayment.approved_at >= get_month_start()
        ).scalar()
        pending_amount = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
            SubscriptionPayment.status == "PENDING"
        ).scalar()
        return "app_admin_revenue", (
            "Revenue Summary\n\n"
            f"Approved all time: N{total_approved:,}\n"
            f"Approved this month: N{month_approved:,}\n"
            f"Pending upgrades: N{pending_amount:,}"
        )

    return "app_admin_unknown", build_app_admin_dashboard_message(db)
