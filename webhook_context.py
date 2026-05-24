from dataclasses import dataclass
from typing import Optional

from models import User


@dataclass
class WebhookUserContext:
    user: Optional[User]
    business_owner_phone: str
    business_name: str
    is_unregistered_voice: bool = False


def is_staff_user(user):
    return bool(user and user.role == "delegate" and user.parent_id)


def can_view_all_business_transactions(user):
    if not user:
        return False
    if user.role == "user" and not user.parent_id:
        return True
    return is_staff_user(user) and bool(user.can_view_all_transactions)


def visibility_recorded_by_id(user):
    if is_staff_user(user) and not can_view_all_business_transactions(user):
        return user.id
    return None


def load_webhook_user_context(db, phone: str, message_type: str) -> WebhookUserContext:
    user = db.query(User).filter(User.phone == phone).first()
    business_owner_phone = phone
    business_name = "your business"

    if user:
        if user.role in ["delegate", "delegate_pending"] and user.parent_id:
            admin = db.query(User).filter(User.id == user.parent_id).first()
            if admin:
                business_owner_phone = admin.phone
                business_name = admin.name
        else:
            business_name = user.name

    return WebhookUserContext(
        user=user,
        business_owner_phone=business_owner_phone,
        business_name=business_name,
        is_unregistered_voice=not user and message_type in ["voice", "audio"],
    )
