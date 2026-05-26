from messages import build_owner_home_menu, build_staff_home_menu
from models import PendingAction
from webhook_context import can_view_all_business_transactions
from whatsapp_client import send_whatsapp_message


HOME_WORDS = [
    "hello",
    "hi",
    "hey",
    "titi",
    "start",
    "menu",
    "main menu",
    "home",
    "help",
]


def handle_home_menu_request(db, phone, text, user, subscription, business_name):
    if not user or text.lower().strip() not in HOME_WORDS:
        return None

    if user.role == "delegate":
        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        db.add(PendingAction(phone=phone, action="STAFF_HOME_MENU"))
        db.commit()
        send_whatsapp_message(
            phone,
            build_staff_home_menu(
                user,
                business_name,
                can_view_all_business_transactions(user),
            ),
        )
        return {"status": "delegate_home_menu"}

    if user.role == "user" and user.parent_id is None:
        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        db.add(PendingAction(phone=phone, action="OWNER_HOME_MENU"))
        db.commit()
        send_whatsapp_message(phone, build_owner_home_menu(user, subscription))
        return {"status": "owner_home_menu"}

    return None
