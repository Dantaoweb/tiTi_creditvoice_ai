import os
import re

from business_templates import (
    business_type_display,
    industry_template_for_user,
    template_examples_for_user,
    template_next_steps_for_user,
    template_plan_value_for_user,
)
from plans import PLAN_GO, PLAN_PRO, PLAN_PREMIUM, PLAN_BASIC, normalize_plan, plan_allows_feature


def build_plan_message(subscription, user=None):
    from business_templates import template_key_for_user
    template_key = template_key_for_user(user) if user else None
    is_thrift = template_key == "thrift_contribution"
    is_school = template_key == "school"

    plan = subscription["plan"]
    status = subscription["status"]
    expires_at = subscription["expires_at"]
    expiry_line = (
        f"Expires: {expires_at.strftime('%d/%m/%Y')}\n"
        if expires_at else
        "Expires: No expiry set\n"
    )
    limits = subscription["limits"]
    transaction_limit = limits["monthly_transactions"] if limits["monthly_transactions"] is not None else "Unlimited"
    staff_limit = limits["staff"] if limits["staff"] is not None else "Unlimited"

    if is_thrift:
        participant_limit = limits.get("thrift_participants")
        participant_limit = participant_limit if participant_limit is not None else "Unlimited"
        limits_lines = (
            f"Participants: {participant_limit}\n"
            f"Monthly transactions: {transaction_limit}\n"
        )
    elif is_school:
        customer_limit = limits["customers"] if limits["customers"] is not None else "Unlimited"
        limits_lines = (
            f"Students: {customer_limit}\n"
            f"Monthly transactions: {transaction_limit}\n"
        )
    else:
        customer_limit = limits["customers"] if limits["customers"] is not None else "Unlimited"
        limits_lines = (
            f"Customers: {customer_limit}\n"
            f"Monthly transactions: {transaction_limit}\n"
        )

    return (
        "Your Subscription\n\n"
        f"Plan: {plan}\n"
        f"Status: {status}\n"
        f"{expiry_line}"
        f"{limits_lines}"
        f"Staff: {staff_limit}"
    )


def _numbered_lines(items, start=1):
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=start))



def build_industry_value_message(user):
    template = industry_template_for_user(user)
    values = template_plan_value_for_user(user)
    title = template["label"] if template else business_type_display(user)
    go_reason = values.get("go_reason", "GO adds stronger reports and business tools.")
    pro_reason = values.get("pro_reason", "PRO is best when staff need controlled access.")

    return (
        f"{title} setup\n\n"
        "BASIC helps you:\n"
        f"{_numbered_lines(values['basic'])}\n\n"
        "GO adds:\n"
        f"{_numbered_lines(values['go'])}\n"
        f"{go_reason}\n\n"
        "PRO adds:\n"
        f"{_numbered_lines(values['pro'])}\n"
        f"{pro_reason}"
    )


def build_upgrade_message(user=None):
    from business_templates import template_key_for_user
    go_price = int(os.getenv("PLAN_GO_PRICE", "3000"))
    pro_price = int(os.getenv("PLAN_PRO_PRICE", "7000"))
    premium_price = int(os.getenv("PLAN_PREMIUM_PRICE", "10000"))

    template_key = template_key_for_user(user) if user else None
    is_thrift = template_key == "thrift_contribution"
    is_school = template_key == "school"

    if is_thrift:
        basic_desc = "10 participants. No reminders or history."
        go_desc = "Unlimited participants, contribution reminders, history, reports."
        pro_desc = "Everything in Go, plus collectors or staff can record contributions. 1 branch, 1 partner, 1 investor."
        premium_desc = "Everything in Pro, with unlimited branches, partners, and investors."
    elif is_school:
        basic_desc = "50 students, 100 transactions/month."
        go_desc = "Unlimited students, fee reminders, payment reports, notes."
        pro_desc = "Everything in Go, plus bursar or admin staff can record fee payments. 1 branch, 1 partner, 1 investor."
        premium_desc = "Everything in Pro, with unlimited branches, partners, and investors."
    else:
        basic_desc = "50 customers, 100 transactions/month."
        go_desc = "Unlimited customers, transactions, inventory, suppliers, reminders, reports."
        pro_desc = "Everything in Go, plus staff management. 1 branch, 1 partner, 1 investor."
        premium_desc = "Everything in Pro, with unlimited branches, partners, and investors."

    industry_value = ""
    if user:
        values = template_plan_value_for_user(user)
        industry_value = (
            f"For {business_type_display(user)}:\n"
            f"GO: {values['go'][0]}\n"
            f"PRO: {values['pro'][0]}\n\n"
        )
    return (
        "Plans\n\n"
        f"BASIC - Free\n"
        f"{basic_desc}\n\n"
        f"{industry_value}"
        f"1. GO - N{go_price:,}/month\n"
        f"{go_desc}\n\n"
        f"2. PRO - N{pro_price:,}/month\n"
        f"{pro_desc}\n\n"
        f"3. PREMIUM - N{premium_price:,}/month\n"
        f"{premium_desc}\n\n"
        "4. My current plan\n"
        "5. Cancel"
    )


def _monthly_price(plan):
    if plan == PLAN_GO:
        return int(os.getenv("PLAN_GO_PRICE", "3000"))
    if plan == PLAN_PRO:
        return int(os.getenv("PLAN_PRO_PRICE", "7000"))
    if plan == PLAN_PREMIUM:
        return int(os.getenv("PLAN_PREMIUM_PRICE", "10000"))
    return 0


# Yearly prices default to 10× the monthly price (2 months free) but can be
# overridden per plan on Render via these env vars.
_YEARLY_ENV = {
    PLAN_GO:      "PLAN_GO_YEARLY_PRICE",
    PLAN_PRO:     "PLAN_PRO_YEARLY_PRICE",
    PLAN_PREMIUM: "PLAN_PREMIUM_YEARLY_PRICE",
}


def get_plan_price(plan, period="MONTHLY"):
    from plans import normalize_period, PERIOD_YEARLY, YEARLY_MONTHS
    plan = normalize_plan(plan)
    monthly = _monthly_price(plan)
    if monthly and normalize_period(period) == PERIOD_YEARLY:
        return int(os.getenv(_YEARLY_ENV[plan], str(monthly * YEARLY_MONTHS)))
    return monthly


def get_payment_account_message():
    bank = os.getenv("SUBSCRIPTION_BANK_NAME", "your bank")
    account_name = os.getenv("SUBSCRIPTION_ACCOUNT_NAME", "your account name")
    account_number = os.getenv("SUBSCRIPTION_ACCOUNT_NUMBER", "your account number")
    return (
        f"Bank: {bank}\n"
        f"Account Name: {account_name}\n"
        f"Account Number: {account_number}"
    )


def build_plan_payment_message(plan, period="MONTHLY"):
    from plans import normalize_period, PERIOD_YEARLY
    plan = normalize_plan(plan)
    period = normalize_period(period)
    amount = get_plan_price(plan, period)
    is_yearly = period == PERIOD_YEARLY
    per_label = "year" if is_yearly else "month"
    monthly_amt = get_plan_price(plan, "MONTHLY")
    yearly_amt = get_plan_price(plan, "YEARLY")
    # Let the user switch billing period from this same screen.
    toggle = (
        f"\nBilling: *{'Yearly' if is_yearly else 'Monthly'}*\n"
        f"1. Monthly - N{monthly_amt:,}/month\n"
        f"2. Yearly - N{yearly_amt:,}/year (2 months free)\n"
        f"Reply 1 or 2 to switch.\n"
    )
    if plan == PLAN_PREMIUM:
        benefits = (
            "Everything in Pro plus:\n"
            "- Unlimited branches\n"
            "- Unlimited partners\n"
            "- Unlimited investors\n"
            "- Add staff & staff permissions\n"
            "- Future Yoruba, Pidgin, and Hausa voice"
        )
    elif plan == PLAN_PRO:
        benefits = (
            "Everything in Go plus:\n"
            "- Add staff\n"
            "- Staff permissions\n"
            "- Admin sees staff records\n"
            "- 1 branch, 1 partner, 1 investor\n"
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
        f"{plan} Plan - N{amount:,}/{per_label}\n\n"
        f"{benefits}\n"
        f"{toggle}\n"
        "Pay to:\n"
        f"{get_payment_account_message()}\n\n"
        f"After payment, send:\nPAID {plan}\n\n"
        "Then send your receipt screenshot or payment reference here.\n\n"
        "Prefer to pay online by card? Reply: PAY ONLINE"
    )


def build_post_onboarding_menu(business_name, user=None):
    from business_templates import has_service_price_catalog
    type_line = f"{business_type_display(user)}\n" if user else ""
    examples = template_examples_for_user(user) if user else [
        "Ade bought rice 5000",
        "Ade paid 3000",
    ]
    if user:
        from business_templates import template_key_for_user
        _tkey = template_key_for_user(user)
        if _tkey == "thrift_contribution":
            option4 = "4. View participants & reminders"
        elif has_service_price_catalog(user):
            option4 = "4. Set up your price list ✦"
        else:
            option4 = "4. Add your products ✦"
    else:
        option4 = "4. Add your products ✦"
    return (
        f"Account created.\n"
        f"Business: {business_name.title()}\n"
        f"{type_line}"
        "Plan: BASIC\n\n"
        f"Try sending:\n{examples[0]}\n{examples[1]}\n\n"
        "Or pick one:\n"
        "1. Help & formats\n"
        "2. Add customer\n"
        "3. Dashboard\n"
        f"{option4}\n"
        "5. Upgrade\n\n"
        "Send MENU anytime.\n\n"
        "Protect your account: set a recovery PIN in case you ever change your phone number.\n"
        "set pin 1234"
    )


def build_owner_home_menu(user, subscription):
    from business_templates import menu_group_for_user
    plan = subscription.get("plan", PLAN_BASIC) if isinstance(subscription, dict) else PLAN_BASIC
    if plan_allows_feature(plan, "VOICE_TEXT"):
        tip_line = "💡 fast mode  |  🎤 voice notes  |  auto reminders"
    else:
        tip_line = "💡 fast mode  |  🎤 voice notes (GO)  |  auto reminders (GO)"
    name = user.name.title() if user else "there"
    group = menu_group_for_user(user) if user else "stock"

    if group == "service":
        body = (
            "1. Record sale\n"
            "2. Service jobs\n"
            "3. Price list\n"
            "4. My customers\n"
            "5. Reminders\n"
            "6. Dashboard\n"
            "7. Wallet ✦\n"
            "8. Help\n"
            "9. More →"
        )
    elif group == "school":
        body = (
            "1. Record fee payment\n"
            "2. My students\n"
            "3. Fee defaulters\n"
            "4. Fee schedule\n"
            "5. Dashboard\n"
            "6. Textbooks / stock\n"
            "7. Wallet ✦\n"
            "8. Help\n"
            "9. More →"
        )
    elif group == "thrift":
        body = (
            "1. Record contribution\n"
            "2. Select group / rate\n"
            "3. Participants\n"
            "4. Reminders\n"
            "5. Reports\n"
            "6. Dashboard\n"
            "7. Help\n"
            "8. Wallet ✦\n"
            "9. More →"
        )
    elif group == "food":
        body = (
            "1. Record sale\n"
            "2. Select product\n"
            "3. Menu / price list\n"
            "4. My customers\n"
            "5. Reminders\n"
            "6. Stock / inventory\n"
            "7. Dashboard\n"
            "8. Wallet ✦\n"
            "9. More →"
        )
    elif group == "clinic":
        body = (
            "1. Record payment\n"
            "2. Select service\n"
            "3. Price list\n"
            "4. My patients\n"
            "5. Reminders\n"
            "6. Dashboard\n"
            "7. Stock / consumables\n"
            "8. Wallet ✦\n"
            "9. More →"
        )
    elif group == "fee":
        body = (
            "1. Record payment\n"
            "2. My customers\n"
            "3. Reminders\n"
            "4. Dashboard\n"
            "5. Reports\n"
            "6. Help\n"
            "7. Wallet ✦\n"
            "8. More →"
        )
    else:  # stock (default)
        body = (
            "1. Record sale\n"
            "2. Select product\n"
            "3. Stock / inventory\n"
            "4. My customers\n"
            "5. Reminders\n"
            "6. Dashboard\n"
            "7. Wallet ✦\n"
            "8. Help\n"
            "9. More →"
        )

    return f"Hi {name}.\n\n{body}\n\n{tip_line}\n\nMENU to return here anytime."


def build_home_more_menu(user=None):
    from business_templates import menu_group_for_user, template_key_for_user
    group = menu_group_for_user(user) if user else "stock"
    if group == "school":
        return (
            "More options\n\n"
            "1. Textbooks & stock\n"
            "2. My plan & upgrade\n"
            "3. Teachers (PRO)\n"
            "4. Partners & Investors\n"
            "5. Automation / reminders\n"
            "6. Notes\n"
            "7. Thrift / ajo savings\n"
            "8. Back"
        )
    if group == "service":
        key = template_key_for_user(user) if user else None
        _is_salon = key == "salon_beauty"
        stock_line = "1. Products / stock\n" if _is_salon else "1. Suppliers\n"
        return (
            f"More options\n\n"
            f"{stock_line}"
            "2. My plan & upgrade\n"
            "3. Staff (PRO)\n"
            "4. Partners & Investors\n"
            "5. Automation / reminders\n"
            "6. Notes\n"
            "7. Thrift / ajo savings\n"
            "8. Back"
        )
    return (
        "More options\n\n"
        "1. Suppliers\n"
        "2. My plan & upgrade\n"
        "3. Staff (PRO)\n"
        "4. Partners & Investors\n"
        "5. Automation / reminders\n"
        "6. Notes\n"
        "7. Thrift / ajo savings\n"
        "8. Back"
    )


def build_staff_home_menu(user, business_name, can_view_all):
    access = "All records" if can_view_all else "Own records only"
    return (
        f"Hi {user.name.title()}. Staff at {business_name.title()}.\n"
        f"Access: {access}\n\n"
        "1. Record sale\n"
        "2. Select product\n"
        "3. My customers\n"
        "4. Dashboard\n"
        "5. Stock\n"
        "6. Help\n"
        "7. Resign\n\n"
        "MENU to return here anytime."
    )


def build_invalid_message(user=None):
    examples = template_examples_for_user(user)
    return (
        f"Not understood. Try:\n{examples[0]}\n\n"
        "Send MENU for options or FORMATS for examples."
    )


def build_supported_formats_message(user=None):
    examples = template_examples_for_user(user)
    next_steps = template_next_steps_for_user(user)
    business_line = ""
    if user:
        business_line = f"For {business_type_display(user)}\n\n"
    return (
        "📋 *Supported Formats*\n\n"
        f"{business_line}"
        "⭐ *Recommended for your business*\n"
        f"👉 {examples[0]}\n"
        f"👉 {examples[1]}\n"
        f"👉 {examples[2]}\n\n"

        "🛒 *Customer debt / sales*\n"
        "👉 Ade bought rice 5000\n"
        "👉 Ade bought 3kg cement for 5000\n"
        "👉 Ade bought rice 4000, beans 3000 paid 2000\n\n"

        "💰 *Payment*\n"
        "👉 Ade paid 3000\n"
        "👉 Alhaji pay 4000 balance 6000 due tomorrow\n\n"

        "📅 *Due date*\n"
        "👉 Ade bought rice 5000 due 12/2/2026\n"
        "👉 Ade bought rice 5000 paid 2000 due tomorrow\n\n"

        "🏪 *Direct sale / service income*\n"
        "👉 I sold phone 45k\n"
        "👉 I supply 1 truck load of sand 60000\n"
        "👉 I received 1000 for doing chair\n\n"

        "📦 *Add stock (set prices)*\n"
        "👉 add stock rice cost 3000 sell 4000\n"
        "👉 add stock paracetamol 500mg cost 150 sell 200, paracetamol 1g cost 250 sell 350\n\n"

        "📦 *Add stock with quantity + price (one message)*\n"
        "👉 add stock honey 10 liters at 10000, selling price 12000\n\n"

        "🔄 *Restock at a new price (adds to existing)*\n"
        "👉 add stock eggs 150 crates at 5600, selling price 6200\n\n"

        "➕ *Add quantity only (keeps existing price)*\n"
        "👉 add stock 150 crates eggs\n\n"

        "✏️ *Update price only (no quantity change)*\n"
        "👉 add stock eggs crate cost 5600 sell 6200\n\n"

        "🛍️ *Sell from stock*\n"
        "👉 select product\n"
        "   - pick a product, send quantity\n"
        "   - custom price: send 3 at 2500\n\n"

        "🏭 *Stock and suppliers*\n"
        "👉 Ayo supply me 12kg cocoa at 5000\n"
        "👉 I buy 12 bags rice from Ayo at 15k each\n"
        "👉 I buy 10 bags rice at 5000 each\n"
        "👉 I paid Ayo 14000 for egg\n"
        "👉 stock\n"
        "👉 suppliers\n"
        "👉 supplier due\n"
        "👉 supplier due this week\n"
        "👉 supplier debts\n\n"

        "📂 *Manage a stock item* (send  stock  then pick a number)\n"
        "   1. Add more quantity\n"
        "   2. Update price\n"
        "   3. Delete item\n"
        "   4. Rename item\n\n"

        "🔧 *Manual stock* (owner / full-access staff only for remove & set)\n"
        "👉 add stock 10 bags rice\n"
        "👉 remove stock 5 bags rice (spoilage)\n"
        "👉 remove stock 2 carton malt (expired)\n"
        "👉 set stock rice 50 bags\n"
        "👉 stock alert rice 10\n\n"

        "🏷️ *Product aliases* (teach tiTi your shorthand)\n"
        "👉 alias eba = garri\n"
        "👉 paracetamol same as paracetamol 500mg\n\n"

        "👤 *Customer setup*\n"
        "👉 John 08012345678\n"
        "👉 add customer John\n"
        "👉 John phone 08012345678\n\n"

        "🔍 *Check customer account*\n"
        "👉 Ade balance\n"
        "👉 Ade account\n"
        "👉 Ade balance this month\n"
        "👉 customer summary Ade\n\n"

        "📋 *Lists & overdue*\n"
        "👉 customer list\n"
        "👉 due  (overdue debtors menu)\n"
        "👉 supplier debts\n\n"

        "⚡ *Fast Capture Mode* (busy market hours)\n"
        "👉 fast mode on\n"
        "👉 fast mode on 8am to 6pm\n"
        "👉 fast mode off\n"
        "👉 close sales\n\n"

        "📊 *Margin & profitability*\n"
        "👉 margin report\n"
        "👉 margin today\n"
        "👉 margin this month\n"
        "👉 products below cost\n\n"

        "❌ *Void / correct a transaction*\n"
        "👉 void last\n"
        "👉 void 42\n"
        "👉 void last customer returned goods\n\n"

        "🤖 *Ask tiTi about your business*\n"
        "👉 who owes me the most\n"
        "👉 why are my sales declining\n"
        "👉 what is my best selling product\n"
        "👉 when am i busiest\n"
        "👉 is [product] profitable\n\n"

        "🧾 *Receipts*\n"
        "👉 print receipt Mary\n"
        "👉 receipt 42\n\n"

        "💬 *Customer Bot* (sell via WhatsApp Status)\n"
        "👉 bot on\n"
        "👉 bot off\n"
        "👉 shop tag demopharmacy\n"
        "👉 auto order on\n"
        "👉 auto order off\n"
        "👉 delivery note Same day delivery within Lagos\n"
        "👉 payment mode Transfer to 0123456789 GTB\n"
        "👉 bot settings\n\n"

        "🔒 *Account security*\n"
        "👉 set pin 1234\n"
        "👉 change pin 1234 5678\n"
        "👉 remove pin 1234\n"
        "👉 recover 08012345678 1234\n\n"

        "📱 *Linked phones* (access from a second number)\n"
        "👉 link phone 08012345678\n"
        "👉 link confirm 483920\n"
        "👉 link decline\n"
        "👉 my phones\n"
        "👉 unlink phone 08012345678\n\n"

        "👥 *Staff* (PRO plan)\n"
        "👉 add staff 08012345678 Name\n"
        "👉 staff\n"
        "👉 allow staff 08012345678 view all\n"
        "👉 revoke staff 08012345678 view all\n\n"

        "⏰ *Reminders*\n"
        "👉 due  (see debtors, preview & send reminders)\n"
        "👉 reminder automation\n"
        "👉 auto reminders on\n"
        "👉 reminder time 8am\n"
        "👉 reminder queue\n\n"

        "💾 *Thrift / ajo / savings*\n"
        "👉 Amina contributed 5000\n"
        "👉 Tunde paid thrift 2000\n"
        "👉 Ade saved 3000\n\n"

        "⚙️ *Other commands*\n"
        "👉 dashboard\n"
        "👉 my plan\n"
        "👉 upgrade\n"
        "👉 change name\n\n"

        "ℹ️ *When you are inside a feature:*\n"
        f"{_numbered_lines(next_steps)}"
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
            f"Paid now: N{pending.paid_amount:,}\n"
            f"Debt: N{balance:,}"
        )

    if pending.action == "SUPPLIER_PAYMENT":
        product_line = f" for {pending.product.title()}" if pending.product else ""
        return (
            "Supplier payment saved.\n"
            f"Paid now: N{pending.paid_amount:,} to {pending.customer_name.title()}{product_line}"
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


def _business_example(user, index, fallback):
    if not user:
        return fallback
    examples = template_examples_for_user(user)
    if len(examples) > index:
        return examples[index]
    return fallback


def _customer_payment_example(pending, user):
    customer_name = (getattr(pending, "customer_name", None) or "").strip().title()
    if not customer_name:
        template = industry_template_for_user(user) if user else None
        customer_name = "Mary" if template and template.get("label") == "Pharmacy / Medicine Store" else "Ade"
    return f"{customer_name} paid 3000"


def _supplier_payment_example(pending, user):
    supplier_name = (getattr(pending, "customer_name", None) or "").strip().title() or "Ayo"
    product = (getattr(pending, "product", None) or "").strip()
    if not product:
        template = industry_template_for_user(user) if user else None
        product = "malaria drug" if template and template.get("label") == "Pharmacy / Medicine Store" else "rice"
    return f"I paid {supplier_name} 14000 for {product}"


def _fmt_amount(val):
    try:
        return f"N{int(val):,}" if val else None
    except (TypeError, ValueError):
        return None


def _build_understood_summary(pending):
    """Build a 'What I understood' block from pending fields."""
    lines = ["What I understood:"]
    customer = (pending.customer_name or "").strip()
    if customer:
        lines.append(f"  Customer: {customer.title()}")

    action = pending.action or ""

    if action == "PAY":
        amt = _fmt_amount(pending.paid_amount)
        if amt:
            lines.append(f"  Payment: {amt}")
    elif action == "SALE":
        amt = _fmt_amount(pending.buy_amount)
        if amt:
            lines.append(f"  Direct income: {amt}")
        if pending.product:
            lines.append(f"  Description: {pending.product.title()}")
    elif action == "SUPPLIER_PURCHASE":
        amt = _fmt_amount(pending.buy_amount)
        if amt:
            lines.append(f"  Purchase total: {amt}")
        if pending.product:
            lines.append(f"  Item: {pending.product.title()}")
        if pending.quantity:
            unit_label = f" {pending.unit}" if pending.unit else ""
            lines.append(f"  Qty: {pending.quantity:,}{unit_label}")
    elif action == "SUPPLIER_PAYMENT":
        amt = _fmt_amount(pending.paid_amount)
        if amt:
            lines.append(f"  Payment to supplier: {amt}")
    else:
        # BUY / COMBINED / fallback
        buy = _fmt_amount(pending.buy_amount)
        paid = _fmt_amount(pending.paid_amount) if (pending.paid_amount or 0) > 0 else None
        if buy:
            lines.append(f"  Amount owed: {buy}")
        if paid:
            lines.append(f"  Paid now: {paid}")
        if pending.product:
            lines.append(f"  Item: {pending.product.title()}")
        if pending.quantity:
            unit_label = f" {pending.unit}" if pending.unit else ""
            lines.append(f"  Qty: {pending.quantity:,}{unit_label}")
        if pending.due_date:
            lines.append(f"  Due: {pending.due_date.strftime('%d/%m/%Y')}")

        # Invoice items
        try:
            import json as _json
            items = _json.loads(pending.items_json or "[]")
            if items:
                lines.append("  Items:")
                for it in items[:5]:
                    qty = it.get("quantity", 1)
                    prod = (it.get("product") or "").title()
                    total = _fmt_amount(it.get("total"))
                    label = f"    {qty}× {prod}"
                    if total:
                        label += f" — {total}"
                    lines.append(label)
                if len(items) > 5:
                    lines.append(f"    ...and {len(items) - 5} more")
        except Exception:
            pass

    return "\n".join(lines)


def edit_prompt_for_pending(pending, user=None):
    if pending.source_text:
        return pending.source_text

    summary = _build_understood_summary(pending)

    if pending.action == "SUPPLIER_PURCHASE":
        return (
            f"{summary}\n\n"
            "Retype to correct it:\n"
            f"Example: {_business_example(user, 2, 'Ayo supply me 12kg cocoa at 5000')}"
        )
    if pending.action == "SUPPLIER_PAYMENT":
        return (
            f"{summary}\n\n"
            "Retype to correct it:\n"
            f"Example: {_supplier_payment_example(pending, user)}"
        )
    if pending.action == "SALE":
        return (
            f"{summary}\n\n"
            "Retype to correct it:\n"
            f"Example: {_business_example(user, 1, 'I received 1000 for doing chair')}"
        )
    if pending.action == "PAY":
        return (
            f"{summary}\n\n"
            "Retype to correct it:\n"
            f"Example: {_customer_payment_example(pending, user)}"
        )
    from biz_language import get_lang
    _L = get_lang(user)
    if pending.action == "COMBINED":
        return (
            f"{summary}\n\n"
            "Retype to correct it:\n"
            f"Example: {_business_example(user, 0, _L['example_credit'])}"
        )
    return (
        f"{summary}\n\n"
        "Retype to correct it:\n"
        f"Example: {_business_example(user, 0, _L['example_credit'])}"
    )


_CONFIRM_DISCLAIMER = "_⚠️ tiTi can make mistakes — please double-check these details before confirming._"


def with_confirm_disclaimer(msg: str) -> str:
    """Append the AI disclaimer to any confirmation message."""
    return f"{msg}\n\n{_CONFIRM_DISCLAIMER}"


def apply_voice_confirmation_options(confirm_msg, source_text=None):
    if source_text:
        confirm_msg = re.sub(
            r"Reply YES or 1 to save, EDIT or 2 to change\.?",
            "",
            confirm_msg
        ).strip()
        confirm_msg = f"{confirm_msg}\n\nReply:\n1. Save\n2. Edit text\n3. Send voice again"
        confirm_msg = f"I heard:\n{source_text}\n\n{confirm_msg}"
    return with_confirm_disclaimer(confirm_msg)


def build_what_can_do_message(user=None):
    from business_templates import template_key_for_user
    tkey = template_key_for_user(user) if user else None
    is_thrift = tkey == "thrift_contribution"
    is_school = tkey == "school"

    if is_thrift:
        sales_line  = "💰 *Contributions* — record member deposits and payments"
        stock_line  = "📦 *Products/Items* — track contribution items or levies"
        cust_line   = "👥 *Members* — manage thrift group participants"
    elif is_school:
        sales_line  = "💰 *Fees* — record student payments and outstanding balances"
        stock_line  = "📦 *Items* — track school supplies and materials"
        cust_line   = "👥 *Students* — manage student records and balances"
    else:
        sales_line  = "💰 *Sales & Credit* — record cash sales, credit sales, and payments received"
        stock_line  = "📦 *Stock/Inventory* — add products, update prices, track quantities"
        cust_line   = "👥 *Customers* — track who owes you and how much"

    return (
        "Hello! I'm *tiTi*, your CreditVoice business assistant 🤖\n\n"
        "Just send me a WhatsApp message in plain English — no special format needed.\n\n"
        "*Here's what I can do for you:*\n\n"
        f"{sales_line}\n"
        f"{stock_line}\n"
        f"{cust_line}\n"
        "📊 *Reports* — daily summary, debtor list, best-selling products, staff performance\n"
        "🧾 *Suppliers* — record what you bought, from who, and at what cost\n"
        "👷 *Staff* — invite team members, set profiles, view performance\n"
        "🤝 *Partners & Investors* — add co-founders or investors with different access levels\n"
        "📝 *Notes* — record expenses, memos, and decisions\n"
        "⏰ *Reminders* — set payment reminders for customers\n"
        "📤 *Export* — export your transactions, debtors, or stock to a spreadsheet\n\n"
        "*How to use me:*\n"
        "Just type naturally. For example:\n"
        "• _Ada bought 2 bags rice at 35000_\n"
        "• _Emeka paid 5000_\n"
        "• _stock rice 10 bags cost 30000_\n"
        "• _summary today_\n"
        "• _who owes me the most_\n\n"
        "Type *menu* anytime to see the main menu, or ask me anything!"
    )


def build_app_guide_message(topic):
    """
    Returns step-by-step navigation instructions for a given app feature.
    Works on both WhatsApp (plain text) and web app (same text shown in tiTi panel).
    No LLM call — completely free and instant.
    """
    guides = {
        "pdf": (
            "🧾 *How to download a PDF receipt*\n\n"
            "*On the web app:*\n"
            "1. Click *Transactions* in the sidebar\n"
            "2. Find and click any sale\n"
            "3. Tap the *PDF* or *Print* icon at the top of the receipt\n"
            "4. Your browser will download or open the receipt\n\n"
            "*On WhatsApp:*\n"
            "Send: _receipt [customer name]_\n"
            "Example: _receipt Ada_\n"
            "tiTi will generate and send the receipt PDF directly."
        ),
        "void": (
            "↩️ *How to void / remove a transaction*\n\n"
            "Voiding cancels a wrong sale or payment — it stops counting in your "
            "balances and reports, but is kept (marked voided) for your records.\n\n"
            "*On the web app:*\n"
            "1. Click *Transactions* in the sidebar\n"
            "2. Find the wrong entry and tap the *Void* (⨯) action\n"
            "3. Type the reason and confirm\n\n"
            "*On WhatsApp:*\n"
            "• _void last_ — void your most recent one\n"
            "• _void 42_ — void transaction #42\n"
            "• _void 42 wrong amount_ — add a reason\n\n"
            "Notes: staff can only void what they recorded themselves; the owner "
            "can void anything. Every void notifies the owner, with the reason."
        ),
        "record_sale": (
            "💰 *How to record a sale*\n\n"
            "*On WhatsApp* — just type naturally:\n"
            "• _Ada bought 3 bags of rice for 9000_\n"
            "• _sold 2 shirts to Emeka 5000 credit_\n"
            "• _cash sale tissue paper 500_\n\n"
            "*On the web app:*\n"
            "1. Click *Quick Record* in the sidebar (or bottom bar on mobile)\n"
            "2. Type the sale details in the box\n"
            "3. Tap *Send* — tiTi will process it the same way\n\n"
            "💡 For shop checkout with receipt, use *POS* instead."
        ),
        "price_list": (
            "🧾 *How to set up your price list*\n\n"
            "For services (tailoring, barbing, mechanic, laundry, etc.) your price "
            "list is your menu of services and their prices.\n\n"
            "*On the web app:*\n"
            "1. Open *Price list* (or *Add stock*) in the sidebar\n"
            "2. Tap *Catalog* to pick services suggested for your trade — or add your own\n"
            "3. Set the price for each service and *Save*\n"
            "4. Use *Select service* to record a job from your list\n\n"
            "*On WhatsApp:*\n"
            "• _price list_ — view or edit your services and prices\n"
            "• _price haircut 1000_ — add or update a service and its price\n"
            "• _select product_ — record a sale from your price list\n\n"
            "💡 Send _price list_ any time to review or change your prices."
        ),
        "inventory": (
            "📦 *How to add stock / inventory*\n\n"
            "*On WhatsApp:*\n"
            "• Single item: _stock rice 20 bags cost 30000 price 2000_\n"
            "• Multiple at once: _add paracetamol, sugar, tissue, milo_\n\n"
            "*On the web app:*\n"
            "1. Click *Inventory* in the sidebar\n"
            "2. Tap *+ Add Item* to add one product with full details\n"
            "3. Or tap *Quick Add Names* to paste a list of product names at once\n"
            "4. Or tap *From Catalog* to pick from your industry's default product list\n\n"
            "After adding names, you can set prices and quantities by tapping each item."
        ),
        "customers": (
            "👥 *How to add a customer*\n\n"
            "*On WhatsApp:*\n"
            "Customers are created automatically when you record a credit sale:\n"
            "_Ada bought 3 bags rice 9000 credit_\n"
            "Ada is now saved as a customer with ₦9,000 balance.\n\n"
            "*On the web app:*\n"
            "1. Click *Customers* in the sidebar\n"
            "2. Tap *+ Add Customer*\n"
            "3. Enter name and phone number\n"
            "4. Tap *Save*"
        ),
        "summary": (
            "📊 *How to see your summary / reports*\n\n"
            "*On WhatsApp:*\n"
            "• _summary today_ — today's sales and profit\n"
            "• _summary this week_ — weekly overview\n"
            "• _summary this month_ — monthly report\n"
            "• _who owes me_ — full debtor list\n"
            "• _best selling_ — your top products\n\n"
            "*On the web app:*\n"
            "1. Click *Dashboard* in the sidebar\n"
            "2. Use the *Period* dropdown (top right) to switch between Today / Week / Month\n"
            "3. Scroll down to see charts, debtor summary, and top products"
        ),
        "reminder": (
            "⏰ *How to send a payment reminder*\n\n"
            "*On WhatsApp:*\n"
            "• _remind Ada_ — sends Ada a payment reminder now\n"
            "• _remind all debtors_ — sends everyone with a balance a reminder\n\n"
            "*On the web app:*\n"
            "1. Click *Reminders* in the sidebar\n"
            "2. You can set automatic reminders — choose how many days after a sale\n"
            "3. Or go to *Customers*, open a customer, and tap *Send Reminder*\n\n"
            "💡 tiTi also sends low-debt nudges automatically if you've enabled reminders."
        ),
        "supplier": (
            "🚚 *How to record a supplier purchase*\n\n"
            "*On WhatsApp:*\n"
            "• _bought 10 bags rice from Alhaji for 150000_\n"
            "• _purchased tissue 200 packs from ABC Suppliers 45000 credit_\n\n"
            "*On the web app:*\n"
            "1. Click *Suppliers* in the sidebar\n"
            "2. First add your supplier if not already there\n"
            "3. Then tap *+ Purchase* to record what you bought, quantity, and amount\n"
            "4. Mark it as paid or credit — tiTi tracks what you owe"
        ),
        "staff": (
            "👷 *How to manage staff*\n\n"
            "*On WhatsApp:*\n"
            "• _invite staff_ — start the process to add a team member\n"
            "• _staff report_ — see staff performance this month\n\n"
            "*On the web app:*\n"
            "1. Click *Staff* in the sidebar\n"
            "2. Tap *+ Invite Staff* — enter their phone number\n"
            "3. They'll receive a WhatsApp message to join your business\n"
            "4. You can set their position, level, and salary from their profile\n\n"
            "Staff can record sales on your behalf from their own WhatsApp."
        ),
        "partner": (
            "🤝 *How to add a partner or investor*\n\n"
            "*On the web app:*\n"
            "1. Click *Partners* in the sidebar\n"
            "2. Tap *+ Invite Partner*\n"
            "3. Enter their phone number and select their role:\n"
            "   — Co-founder, Partner, Investor, or Silent\n"
            "4. Set equity % and investment amount if applicable\n"
            "5. They'll receive a WhatsApp invitation to join\n\n"
            "Partners can be given different levels of access to your business data."
        ),
        "notes": (
            "📝 *How to use Business Notes*\n\n"
            "*On WhatsApp:*\n"
            "• _note: bought generator for 150000_ — records an expense\n"
            "• _memo: meet supplier Friday_ — saves a memo\n\n"
            "*On the web app:*\n"
            "1. Click *Notes* in the sidebar\n"
            "2. Tap *+ Add Note*\n"
            "3. Choose a category: Expense, Income, Decision, Goal, or Memo\n"
            "4. Set who can see it — just you, partners, or everyone\n\n"
            "Notes with amounts appear in your expense/income summary."
        ),
        "pos": (
            "🛒 *How to use POS (Point of Sale)*\n\n"
            "*On the web app:*\n"
            "1. Click *POS* in the sidebar (or bottom bar on mobile)\n"
            "2. Search for a product or tap it from the catalog\n"
            "3. Set quantity — tap *Add to Cart*\n"
            "4. When done, tap *Checkout*\n"
            "5. Choose payment type and enter customer name (optional)\n"
            "6. A receipt is generated — you can print or download as PDF\n\n"
            "💡 POS works great for shops with a tablet or phone on the counter."
        ),
        "bulk_add": (
            "📦 *How to add many products at once*\n\n"
            "*On WhatsApp:*\n"
            "Send: _add paracetamol, sugar, tissue, milo, soap_\n"
            "tiTi creates all of them as draft items instantly.\n\n"
            "*On the web app:*\n"
            "1. Click *Inventory* in the sidebar\n"
            "2. Tap *Quick Add Names*\n"
            "3. Paste or type your product names (one per line, or separated by commas)\n"
            "4. Tap *Add All* — they're all saved as drafts\n"
            "5. Set prices and quantities later by tapping each item\n\n"
            "Or tap *From Catalog* to pick from your industry's default product list."
        ),
        "branches": (
            "🏪 *How to manage branches*\n\n"
            "*On the web app:*\n"
            "1. Click *Branches* in the sidebar\n"
            "2. Tap *+ Add Branch* to create a new shop location\n"
            "3. Each branch can have its own staff members\n"
            "4. Reports can be filtered by branch\n\n"
            "Staff assigned to a branch only see their branch's data."
        ),
        "automation": (
            "⚡ *How to set up automations*\n\n"
            "*On the web app:*\n"
            "1. Click *Automation* in the sidebar\n"
            "2. *Payment reminders* — set how many days after a credit sale to remind the customer automatically\n"
            "3. *Low stock alerts* — tiTi notifies you when any product falls below your set quantity\n"
            "4. *Inactivity nudge* — tiTi checks in if you haven't recorded anything in a few days\n\n"
            "All automations send to both WhatsApp and your app notification bell."
        ),
        "download_app": (
            "📱 *How to install CreditVoice on your phone*\n\n"
            "*Android (recommended):*\n"
            "1. Open the app in your Chrome browser\n"
            "2. Tap the *three dots menu* (top right)\n"
            "3. Tap *Add to Home Screen* or *Install App*\n"
            "4. It works like a normal app — even offline!\n\n"
            "*iPhone:*\n"
            "1. Open the app in Safari\n"
            "2. Tap the *Share* button (box with arrow)\n"
            "3. Tap *Add to Home Screen*\n\n"
            "💡 You can still use tiTi on WhatsApp alongside the app — they sync automatically."
        ),
        "wallet": (
            "💳 *How to use the Wallet / receive payments*\n\n"
            "The CreditVoice Wallet lets customers pay you directly via bank transfer.\n\n"
            "*On the web app:*\n"
            "1. Click *Wallet* in the sidebar\n"
            "2. Your virtual account number is shown — share it with customers\n"
            "3. When a customer transfers to your account, tiTi detects it and records it automatically\n\n"
            "_Note: Wallet is currently in early access. Contact support to activate._"
        ),
        "transactions": (
            "📋 *How to see your transaction history*\n\n"
            "*On WhatsApp:*\n"
            "• _transactions today_ — today's sales list\n"
            "• _transactions this week_ — weekly list\n"
            "• _export transactions_ — download as spreadsheet\n\n"
            "*On the web app:*\n"
            "1. Click *Transactions* in the sidebar\n"
            "2. Use the *Period* dropdown to filter by date\n"
            "3. Click any transaction to see full details\n"
            "4. Tap *Export* to download as a CSV/Excel file\n"
            "5. Tap the *PDF* icon on any transaction for a printable receipt"
        ),
        "debt": (
            "💰 *How to check who owes you money*\n\n"
            "*On WhatsApp:*\n"
            "• _who owes me_ — full debtor list\n"
            "• _who owes me most_ — sorted by highest balance\n"
            "• _debtors_ — same thing\n"
            "• _Ada balance_ — check one specific customer\n\n"
            "*On the web app:*\n"
            "1. Click *Customers* in the sidebar\n"
            "2. Customers with outstanding balances are highlighted\n"
            "3. Tap any customer to see their full credit history\n"
            "4. Tap *Send Reminder* to chase a payment\n\n"
            "tiTi also sends you automatic debt alerts every 3 days for overdue balances."
        ),
        "thrift": (
            "💰 *How to use Thrift / Ajo*\n\n"
            "*On WhatsApp — record contributions:*\n"
            "• _Amina contributed 5000_ — records ₦5,000 from Amina\n"
            "• _Tunde paid ajo 3000_ — same thing\n"
            "• _Ada esusu 2000_ — same thing\n\n"
            "*Manage participants on WhatsApp:*\n"
            "• _add thrift member Amina Bello_ — adds Amina as a participant\n"
            "• _thrift report_ — shows how much each member has contributed\n"
            "• _thrift totals_ — same thing\n\n"
            "*On the web app:*\n"
            "1. Click *Thrift* in the sidebar\n"
            "2. Tap *Add Participant* to register members\n"
            "3. Tap *Record Contribution* for each payment\n"
            "4. The *Participants* tab shows each member's total at a glance\n\n"
            "💡 Connect your Wallet so members can transfer directly — contributions match automatically."
        ),
        "savings": (
            "💰 *How to record personal savings*\n\n"
            "Personal savings are separate from your business — they're for money you're\n"
            "setting aside for yourself (school fees, house rent, emergency fund, etc.)\n\n"
            "*On WhatsApp — just type:*\n"
            "• _I saved 5000_ — record ₦5,000 as saved\n"
            "• _personal savings 10000 school fees_ — save with a note\n"
            "• _my savings 2000 emergency_ — same thing\n"
            "• _my savings balance_ — see your total saved\n\n"
            "*On the web app:*\n"
            "1. Click *Thrift* in the sidebar\n"
            "2. Tap *Record Saving*\n"
            "3. Enter the amount and an optional note\n"
            "4. Tap *Save* — it's added to your personal savings total\n\n"
            "💡 Personal savings appear in the Thrift section, separate from group contributions."
        ),
    }

    text = guides.get(topic)
    if text:
        return text
    return (
        "I'm not sure which feature you're asking about.\n\n"
        "Try asking more specifically, like:\n"
        "• _how do I download my receipt as PDF_\n"
        "• _how do I add stock_\n"
        "• _where is my debtor list_\n\n"
        "Or send *help* to see everything I can do."
    )


def build_bulk_add_result_message(saved_names, already_exist=None):
    count = len(saved_names)
    names_list = "\n".join(f"• {n.title()}" for n in saved_names)
    exist_line = ""
    if already_exist:
        exist_line = f"\n\n_{len(already_exist)} already existed: {', '.join(n.title() for n in already_exist)}_"
    return (
        f"✅ Added *{count} product{'s' if count != 1 else ''}* to your inventory:\n\n"
        f"{names_list}"
        f"{exist_line}\n\n"
        "These are saved as drafts. To set prices and quantities, just say:\n"
        "_price <product name> <cost> <selling price>_\n"
        "Example: _price paracetamol 300 500_\n\n"
        "Or visit your *Inventory* page on the CreditVoice app to fill in the details."
    )
