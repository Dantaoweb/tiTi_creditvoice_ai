import os
import re

from business_templates import (
    business_type_display,
    industry_template_for_user,
    template_examples_for_user,
    template_next_steps_for_user,
    template_plan_value_for_user,
)
from plans import PLAN_GO, PLAN_PRO, PLAN_BASIC, normalize_plan, plan_allows_feature


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

    template_key = template_key_for_user(user) if user else None
    is_thrift = template_key == "thrift_contribution"
    is_school = template_key == "school"

    if is_thrift:
        basic_desc = "10 participants. No reminders or history."
        go_desc = "Unlimited participants, contribution reminders, history, reports."
        pro_desc = "GO + collectors or staff can record contributions."
    elif is_school:
        basic_desc = "50 students, 100 transactions/month."
        go_desc = "Unlimited students, fee reminders, payment reports, notes."
        pro_desc = "GO + bursar or admin staff can record fee payments."
    else:
        basic_desc = "50 customers, 100 transactions/month."
        go_desc = "Unlimited customers, transactions, inventory, suppliers, reminders, reports."
        pro_desc = "GO + staff management."

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
        "3. My current plan\n"
        "4. Cancel"
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
            "4. Automation / reminders\n"
            "5. Back"
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
            "4. Automation / reminders\n"
            "5. Back"
        )
    return (
        "More options\n\n"
        "1. Suppliers\n"
        "2. My plan & upgrade\n"
        "3. Staff (PRO)\n"
        "4. Automation / reminders\n"
        "5. Back"
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
