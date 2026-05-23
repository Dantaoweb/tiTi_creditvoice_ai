import os
import re

from business_templates import business_type_display, template_examples_for_user
from plans import PLAN_GO, PLAN_PRO, normalize_plan


def build_plan_message(subscription):
    plan = subscription["plan"]
    status = subscription["status"]
    expires_at = subscription["expires_at"]
    expiry_line = (
        f"Expires: {expires_at.strftime('%d/%m/%Y')}\n"
        if expires_at else
        "Expires: No expiry set\n"
    )
    limits = subscription["limits"]
    customer_limit = limits["customers"] if limits["customers"] is not None else "Unlimited"
    transaction_limit = limits["monthly_transactions"] if limits["monthly_transactions"] is not None else "Unlimited"
    staff_limit = limits["staff"] if limits["staff"] is not None else "Unlimited"

    return (
        "Your Subscription\n\n"
        f"Plan: {plan}\n"
        f"Status: {status}\n"
        f"{expiry_line}"
        f"Customers: {customer_limit}\n"
        f"Monthly transactions: {transaction_limit}\n"
        f"Staff: {staff_limit}"
    )


def build_upgrade_message():
    go_price = int(os.getenv("PLAN_GO_PRICE", "3000"))
    pro_price = int(os.getenv("PLAN_PRO_PRICE", "7000"))
    return (
        "CreditVoice Plans\n\n"
        "BASIC - Free\n"
        "1 user, 50 customers, 100 monthly transactions, basic debt tracking.\n\n"
        f"1. GO - N{go_price:,}/month\n"
        "For one-owner businesses. Unlimited customers, unlimited transactions, invoices, direct sales, inventory, suppliers, reports, reminders, and notes.\n\n"
        f"2. PRO - N{pro_price:,}/month\n"
        "Everything in Go plus staff, staff permissions, team notes, and future multilingual voice.\n\n"
        "3. View my current plan\n"
        "4. Cancel\n\n"
        "Reply with 1, 2, 3, or 4."
    )


def get_plan_price(plan):
    plan = normalize_plan(plan)
    if plan == PLAN_GO:
        return int(os.getenv("PLAN_GO_PRICE", "3000"))
    if plan == PLAN_PRO:
        return int(os.getenv("PLAN_PRO_PRICE", "7000"))
    return 0


def get_payment_account_message():
    bank = os.getenv("SUBSCRIPTION_BANK_NAME", "your bank")
    account_name = os.getenv("SUBSCRIPTION_ACCOUNT_NAME", "your account name")
    account_number = os.getenv("SUBSCRIPTION_ACCOUNT_NUMBER", "your account number")
    return (
        f"Bank: {bank}\n"
        f"Account Name: {account_name}\n"
        f"Account Number: {account_number}"
    )


def build_plan_payment_message(plan):
    plan = normalize_plan(plan)
    amount = get_plan_price(plan)
    if plan == PLAN_PRO:
        benefits = (
            "Everything in Go plus:\n"
            "- Add staff\n"
            "- Staff permissions\n"
            "- Admin sees staff records\n"
            "- Future Yoruba, Pidgin, and Hausa voice"
        )
    else:
        benefits = (
            "- Unlimited customers\n"
            "- Unlimited transactions\n"
            "- Direct sales\n"
            "- Invoice sales\n"
            "- Inventory and stock value\n"
            "- Supplier debt and payment records\n"
            "- Product reports\n"
            "- Debt reminders\n"
            "- Transaction notes"
        )

    return (
        f"{plan} Plan - N{amount:,}/month\n\n"
        f"{benefits}\n\n"
        "Pay to:\n"
        f"{get_payment_account_message()}\n\n"
        f"After payment, send:\nPAID {plan}\n\n"
        "Then send your receipt screenshot or payment reference here."
    )


def build_post_onboarding_menu(business_name, user=None):
    type_line = f"Type: {business_type_display(user)}\n" if user else ""
    examples = template_examples_for_user(user) if user else [
        "Ade bought rice 5000",
        "Ade paid 3000",
    ]
    return (
        f"Account created.\n\n"
        f"Business: {business_name.title()}\n"
        f"{type_line}"
        "Plan: BASIC\n\n"
        "Try:\n"
        f"{examples[0]}\n"
        f"{examples[1]}\n\n"
        "What next?\n"
        "1. See formats\n"
        "2. Add customer\n"
        "3. View dashboard\n"
        "4. Upgrade"
    )


def build_owner_home_menu(user, subscription):
    if subscription["plan"] == PLAN_PRO:
        extra_lines = "\n5. Staff menu\n6. Help formats"
    else:
        extra_lines = "\n5. Help formats"
    examples = template_examples_for_user(user)
    return (
        f"Hello {user.name.title()}.\n\n"
        f"Business type: {business_type_display(user)}\n\n"
        "What would you like to do?\n"
        "1. Record transaction\n"
        "2. Add customer\n"
        "3. Dashboard\n"
        "4. Upgrade / My plan"
        f"{extra_lines}\n\n"
        f"Example: {examples[0]}"
    )


def build_staff_home_menu(user, business_name, can_view_all):
    access = "Can view all business transactions" if can_view_all else "Own records only"
    return (
        f"Hello {user.name.title()}.\n\n"
        f"You are staff under {business_name.title()}.\n"
        f"Access: {access}\n\n"
        "You can:\n"
        "1. Record transaction\n"
        "2. View customers you handled\n"
        "3. Dashboard\n"
        "4. Resign"
    )


def build_invalid_message(user=None):
    examples = template_examples_for_user(user)
    return (
        "I could not understand that yet.\n\n"
        "Try:\n"
        f"{examples[0]}\n"
        f"{examples[1]}\n"
        f"{examples[2]}\n"
        "upgrade\n\n"
        "Send FORMATS for more examples."
    )


def build_supported_formats_message(user=None):
    examples = template_examples_for_user(user)
    business_line = ""
    if user:
        business_line = f"For {business_type_display(user)}\n\n"
    return (
        "Supported Formats\n\n"
        f"{business_line}"
        "Recommended for your business\n"
        f"{examples[0]}\n"
        f"{examples[1]}\n"
        f"{examples[2]}\n\n"
        "Customer debt/sales\n"
        "Ade bought rice 5000\n"
        "Ade bought 3kg cement for 5000\n"
        "Ade bought rice 4000, beans 3000 paid 2000\n\n"
        "Payment\n"
        "Ade paid 3000\n"
        "Alhaji pay 4000 balance 6000 due tomorrow\n\n"
        "Due date\n"
        "Ade bought rice 5000 due 12/2/2026\n"
        "Ade bought rice 5000 paid 2000 due tomorrow\n\n"
        "Direct sale/service income\n"
        "I sold phone 45k\n"
        "I supply 1 truck load of sand 60000\n"
        "I received 1000 for doing chair\n\n"
        "Stock and suppliers\n"
        "Ayo supply me 12kg cocoa at 5000\n"
        "I buy 12 bags rice from Ayo at 15k each\n"
        "I paid Ayo 14000 for egg\n"
        "stock\n"
        "suppliers\n\n"
        "Customer setup\n"
        "John 08012345678\n"
        "add customer John\n"
        "John phone 08012345678\n\n"
        "Other commands\n"
        "dashboard\n"
        "my plan\n"
        "upgrade\n"
        "change name"
    )


def build_onboarding_start_message():
    return (
        "Welcome to CreditVoice.\n\n"
        "Reply with your business name to create your free BASIC account.\n"
        "Example: Ayo Stores"
    )


def pending_transaction_summary(pending, customer=None):
    if pending.action == "SUPPLIER_PURCHASE":
        balance = max((pending.buy_amount or 0) - (pending.paid_amount or 0), 0)
        return (
            "Supplier purchase saved.\n"
            f"{pending.product.title()}: N{pending.buy_amount:,}\n"
            f"Paid: N{pending.paid_amount:,}\n"
            f"You owe: N{balance:,}"
        )

    if pending.action == "SUPPLIER_PAYMENT":
        product_line = f" for {pending.product.title()}" if pending.product else ""
        return (
            "Supplier payment saved.\n"
            f"{pending.customer_name.title()}: N{pending.paid_amount:,}{product_line}"
        )

    if pending.action == "SALE":
        label = pending.product.title() if pending.product else "Service/direct income"
        return (
            "Saved as service/direct income.\n"
            f"{label}: N{pending.buy_amount:,}\n"
            "No customer debt was recorded."
        )

    customer_name = customer.name.title() if customer else pending.customer_name.title()
    if pending.action == "COMBINED":
        return (
            f"{customer_name} transaction saved.\n"
            f"Charge: N{pending.buy_amount:,}\n"
            f"Paid: N{pending.paid_amount:,}"
        )
    if pending.action == "BUY":
        return (
            f"{customer_name} charge saved.\n"
            f"Amount: N{pending.buy_amount:,}"
        )
    if pending.action == "PAY":
        return (
            f"{customer_name} payment saved.\n"
            f"Paid: N{pending.paid_amount:,}"
        )
    return "Saved."


def balance_status_line(balance):
    if balance < 0:
        return f"Credit: N{abs(balance):,}"
    return f"Balance: N{balance:,}"


def edit_prompt_for_pending(pending):
    if pending.source_text:
        return pending.source_text
    if pending.action == "SUPPLIER_PURCHASE":
        return (
            "No problem. Send the corrected stock purchase.\n"
            "Example: Ayo supply me 12kg cocoa at 5000"
        )
    if pending.action == "SUPPLIER_PAYMENT":
        return (
            "No problem. Send the corrected supplier payment.\n"
            "Example: I paid Ayo 14000 for egg"
        )
    if pending.action == "SALE":
        return (
            "No problem. Send the corrected service income.\n"
            "Example: I received 1000 for doing chair"
        )
    if pending.action == "PAY":
        return (
            "No problem. Send the corrected payment.\n"
            "Example: Ade paid 3000"
        )
    if pending.action == "COMBINED":
        return (
            "No problem. Send the corrected transaction.\n"
            "Example: Ade bought rice 5000 paid 2000"
        )
    return (
        "No problem. Send the corrected transaction.\n"
        "Example: Ade bought rice 5000"
    )


def apply_voice_confirmation_options(confirm_msg, source_text=None):
    if not source_text:
        return confirm_msg
    confirm_msg = re.sub(
        r"Reply YES or 1 to save, EDIT or 2 to change\.?",
        "",
        confirm_msg
    ).strip()
    confirm_msg = f"{confirm_msg}\n\nReply:\n1. Save\n2. Edit text\n3. Send voice again"
    return f"I heard:\n{source_text}\n\n{confirm_msg}"
