from admin_commands import handle_admin_subscription_command, notify_subscription_admins
from customer_commands import handle_customer_command
from messages import (
    build_plan_message,
    build_supported_formats_message,
    build_upgrade_message,
)
from models import PendingAction
from onboarding_commands import handle_profile_command
from reminder_commands import handle_reminder_command
from report_commands import handle_report_command
from staff_commands import handle_staff_command
from supplier_commands import handle_supplier_command
from transaction_setup import handle_transaction_setup
from whatsapp_client import send_whatsapp_message


def handle_parsed_command(
    db,
    phone,
    text,
    parsed,
    pending,
    user,
    subscription,
    business_name,
    business_owner_phone,
    visible_recorded_by_id,
    voice_transcript_text,
):
    if parsed["type"] == "FORMATS":
        msg = build_supported_formats_message(user)
        send_whatsapp_message(phone, msg)
        return {"status": "formats"}

    supplier_result = handle_supplier_command(
        db,
        phone,
        parsed,
        user,
        business_owner_phone,
        voice_transcript_text,
        send_whatsapp_message
    )
    if supplier_result:
        return supplier_result
    if parsed["type"] == "ARTISAN_PAYMENT_CHOICE":
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name=parsed["name"].lower(),
                action="ARTISAN_PAYMENT_CHOICE",
                paid_amount=parsed["amount"],
                product=f"{parsed.get('description', 'service/work')} - {parsed['name'].lower()}",
                last_customer=parsed["name"].lower()
            )
        )
        db.commit()
        send_whatsapp_message(
            phone,
            f"{parsed['name'].title()} paid you N{parsed['amount']:,}.\n\n"
            "What is this for?\n"
            "1. For the work/service you did, no customer debt\n"
            "2. He/she paid debt owed to you"
        )
        return {"status": "artisan_payment_choice"}

    if parsed["type"] == "MY_PLAN":
        send_whatsapp_message(phone, build_plan_message(subscription))
        return {"status": "my_plan"}

    if parsed["type"] == "UPGRADE_MENU":
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name="",
                action="UPGRADE_MENU",
                last_customer=""
            )
        )
        db.commit()
        send_whatsapp_message(phone, build_upgrade_message())
        return {"status": "upgrade_menu"}

    admin_subscription_result = handle_admin_subscription_command(
        db,
        phone,
        parsed,
        user,
        send_whatsapp_message,
        notify_subscription_admins
    )
    if admin_subscription_result:
        return admin_subscription_result

    staff_result = handle_staff_command(
        db,
        phone,
        parsed,
        user,
        subscription,
        business_name,
        send_whatsapp_message
    )
    if staff_result:
        return staff_result

    profile_result = handle_profile_command(
        db,
        phone,
        parsed,
        pending,
        business_owner_phone,
        send_whatsapp_message
    )
    if profile_result:
        return profile_result
    reminder_result = handle_reminder_command(
        db,
        phone,
        parsed,
        user,
        send_whatsapp_message
    )
    if reminder_result:
        return reminder_result
    report_result = handle_report_command(
        db,
        phone,
        text,
        parsed,
        user,
        business_owner_phone,
        visible_recorded_by_id,
        send_whatsapp_message
    )
    if report_result:
        return report_result
    customer_result = handle_customer_command(
        db,
        phone,
        text,
        parsed,
        user,
        business_owner_phone,
        visible_recorded_by_id,
        send_whatsapp_message
    )
    if customer_result:
        return customer_result
    transaction_setup_result = handle_transaction_setup(
        db,
        phone,
        parsed,
        user,
        business_owner_phone,
        subscription,
        visible_recorded_by_id,
        voice_transcript_text,
        send_whatsapp_message
    )
    if transaction_setup_result:
        return transaction_setup_result

    return None

