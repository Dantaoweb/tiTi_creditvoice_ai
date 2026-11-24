from dataclasses import dataclass
from typing import Optional

from models import User
from linked_phone_commands import find_owner_via_linked_phone


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


def branch_scope_for_user(user):
    """The data-access scope for multi-branch isolation.

    Returns (branch_id, limited):
      - owner (top-level account): (None, False) — sees all branches
      - admin (staff with can_view_all_transactions): (None, False) — the whole
        business, like the owner (staff_access.py)…
      - …unless the owner kept them to their branch ("own_branch"):
        (branch_id, True) — that whole branch (all staff in it)
      - regular staff: (None, True) — caller scopes to the staff's own records
        (recorded_by_id)
    """
    if not user or getattr(user, "parent_id", None) is None:
        return None, False
    if getattr(user, "can_view_all_transactions", False):
        # An admin sees the whole business by default (staff_access.py), unless
        # the owner kept them to their own branch
        from staff_access import kept_from
        if getattr(user, "branch_id", None) and kept_from(user, "own_branch"):
            return user.branch_id, True
        return None, False
    return None, True


def load_webhook_user_context(db, phone: str, message_type: str) -> WebhookUserContext:
    user = db.query(User).filter(User.phone == phone).first()
    business_owner_phone = phone
    business_name = "your business"

    if not user:
        # Check if this is a linked (secondary) phone — if so, load the real owner
        linked_owner = find_owner_via_linked_phone(db, phone)
        if linked_owner:
            # Treat this phone exactly as if it were the owner's primary phone
            user = linked_owner
            business_owner_phone = linked_owner.phone
            business_name = linked_owner.name
            return WebhookUserContext(
                user=user,
                business_owner_phone=business_owner_phone,
                business_name=business_name,
                is_unregistered_voice=False,
            )

    if user:
        if user.role in ["delegate", "delegate_pending"] and user.parent_id:
            admin = db.query(User).filter(User.id == user.parent_id).first()
            if admin:
                business_owner_phone = admin.phone
                business_name = admin.name
        else:
            business_name = user.name

        # Mark WhatsApp as linked if this is the first time a web-registered user messages
        if not user.whatsapp_linked:
            user.whatsapp_linked = True
            db.commit()

    return WebhookUserContext(
        user=user,
        business_owner_phone=business_owner_phone,
        business_name=business_name,
        is_unregistered_voice=not user and message_type in ["voice", "audio"],
    )
