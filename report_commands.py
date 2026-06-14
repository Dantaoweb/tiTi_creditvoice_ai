from models import PendingAction
from reports import (
    build_dashboard_menu_message,
    build_dashboard_summary_message,
    build_margin_summary_message,
    get_biggest_debtor,
    get_customer_count,
    get_customer_summary,
    get_dashboard_summary,
    get_debtor_leaderboard,
    get_margin_summary,
    get_monthly_sales,
    get_most_sold_product,
    get_new_customer_count,
    get_outstanding_balance,
    get_overdue_debtors,
    get_paid_customer_count,
    get_product_sales_by_date,
    get_product_sales_by_period,
    get_products_below_cost,
    get_today_sales,
    get_transaction_stats,
    get_unpaid_debtors,
    get_weekly_sales,
    get_yearly_sales,
    list_customers,
    search_customers,
)
from subscriptions import ensure_feature_allowed


def handle_report_command(
    db,
    phone,
    text,
    parsed,
    user,
    business_owner_phone,
    visible_recorded_by_id,
    send_message,
):
    command_type = parsed.get("type")

    if command_type == "TODAY_SALES":
        total = get_today_sales(db, business_owner_phone, visible_recorded_by_id)
        send_message(phone, f"Today's sales: N{total:,}")
        return {"status": "today_sales"}

    if command_type == "WEEKLY_SALES":
        total = get_weekly_sales(db, business_owner_phone, visible_recorded_by_id)
        send_message(phone, f"Weekly sales: N{total:,}")
        return {"status": "weekly_sales"}

    if command_type == "MONTHLY_SALES":
        total = get_monthly_sales(db, business_owner_phone, visible_recorded_by_id)
        send_message(phone, f"Monthly sales: N{total:,}")
        return {"status": "monthly_sales"}

    if command_type == "YEARLY_SALES":
        total = get_yearly_sales(db, business_owner_phone, visible_recorded_by_id)
        send_message(phone, f"Yearly sales: N{total:,}")
        return {"status": "yearly_sales"}

    if command_type == "PERIOD_TRANSACTIONS":
        stats = get_transaction_stats(
            db,
            business_owner_phone,
            parsed.get("period"),
            visible_recorded_by_id,
        )
        period_name = parsed.get("period", "ALL TIME").title()
        send_message(
            phone,
            f"{period_name} transactions: {stats['transaction_count']:,}\n"
            f"Credit sales: N{stats['credit_sales']:,}\n"
            f"Direct sales: N{stats['direct_sales']:,}\n"
            f"Total sales: N{stats['total_sales']:,}\n"
            f"Payments received: N{stats['total_pay']:,}"
        )
        return {"status": "period_transactions"}

    if command_type == "PERIOD_TOTAL_RECEIVED":
        stats = get_transaction_stats(
            db,
            business_owner_phone,
            parsed.get("period"),
            visible_recorded_by_id,
        )
        label = parsed.get("period", "all time")
        send_message(phone, f"Total received {label}: N{stats['total_pay']:,}")
        return {"status": "period_total_received"}

    if command_type == "PERIOD_TOTAL_PAID":
        stats = get_transaction_stats(
            db,
            business_owner_phone,
            parsed.get("period"),
            visible_recorded_by_id,
        )
        label = parsed.get("period", "all time")
        send_message(phone, f"Total paid {label}: N{stats['total_pay']:,}")
        return {"status": "period_total_paid"}

    if command_type == "OUTSTANDING_BALANCE":
        total = get_outstanding_balance(db, business_owner_phone, visible_recorded_by_id)
        send_message(phone, f"Total outstanding balance: N{total:,}")
        return {"status": "outstanding_balance"}

    if command_type == "PERIOD_CASH_CREDIT":
        stats = get_transaction_stats(
            db,
            business_owner_phone,
            parsed.get("period"),
            visible_recorded_by_id,
        )
        label = parsed.get("period", "all time").lower()
        if parsed.get("measure") == "CASH":
            send_message(phone, f"Cash {label}: N{stats['total_pay']:,}")
        else:
            send_message(phone, f"Credit {label}: N{stats['total_buy']:,}")
        return {"status": "period_cash_credit"}

    if command_type == "MOST_SOLD_PRODUCT":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "product_report_plan_blocked"}

        product = get_most_sold_product(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
        if not product:
            send_message(phone, "No product sales data available yet.")
            return {"status": "no_product_sales"}
        send_message(
            phone,
            f"Most sold product: {product.product.title()}\n"
            f"Quantity: {product.total_quantity:,}\n"
            f"Sales: N{product.total_amount:,}"
        )
        return {"status": "most_sold_product"}

    if command_type == "PRODUCT_LEADERBOARD":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "product_report_plan_blocked"}

        results = get_product_sales_by_period(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
        if not results:
            send_message(phone, "No product sales data available yet.")
            return {"status": "product_leaderboard_empty"}
        msg = "Product Leaderboard\n\n"
        for index, row in enumerate(results[:10], start=1):
            msg += f"{index}. {row.product.title()} -> {row.total_quantity:,} units, N{row.total_amount:,}\n"
        send_message(phone, msg)
        return {"status": "product_leaderboard"}

    if command_type == "PRODUCT_SALES_BY_DATE":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "product_report_plan_blocked"}

        if not parsed.get("date"):
            send_message(phone, "Send product sales by date DD/MM/YYYY")
            return {"status": "product_sales_by_date_missing"}
        results = get_product_sales_by_date(db, business_owner_phone, parsed["date"], visible_recorded_by_id)
        if not results:
            send_message(phone, f"No product sales found for {parsed['date']}")
            return {"status": "product_sales_by_date_empty"}
        msg = f"Product Sales on {parsed['date']}\n\n"
        for index, row in enumerate(results, start=1):
            msg += f"{index}. {row.product.title()} -> {row.total_quantity:,} units, N{row.total_amount:,}\n"
        send_message(phone, msg)
        return {"status": "product_sales_by_date"}

    if command_type == "CUSTOMER_LIST":
        period = parsed.get("period")
        customers = list_customers(db, business_owner_phone, period, visible_recorded_by_id)
        if not customers:
            label = f" for {period.lower()}" if period else ""
            send_message(phone, f"No customers found{label}.")
            return {"status": "customer_list_empty"}

        period_header = f" ({period.title()})" if period else ""
        msg = f"Customers{period_header}\n\n"
        for index, customer in enumerate(customers, start=1):
            msg += (
                f"{index}. {customer['name'].title()}"
                f" ({customer['phone'] or 'no phone'}): N{customer['balance']:,}\n"
            )
        send_message(phone, msg)
        return {"status": "customer_list"}

    if command_type == "CUSTOMER_COUNT":
        period = parsed.get("period")
        count = get_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
        period_label = period.lower() if period else "all time"
        send_message(phone, f"Customers {period_label}: {count:,}")
        return {"status": "customer_count"}

    if command_type == "NEW_CUSTOMERS":
        period = parsed.get("period")
        count = get_new_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
        period_label = period.lower() if period else "all time"
        send_message(phone, f"New customers {period_label}: {count:,}")
        return {"status": "new_customers"}

    if command_type == "PAID_CUSTOMERS":
        period = parsed.get("period")
        count = get_paid_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
        period_label = period.lower() if period else "all time"
        send_message(phone, f"Paid customers {period_label}: {count:,}")
        return {"status": "paid_customers"}

    if command_type == "DASHBOARD_SUMMARY":
        period = parsed.get("period")
        if period is None and text.lower().strip() in [
            "dashboard",
            "stats",
            "dashboard summary",
            "dashboard stats",
            "business summary",
            "business stats",
        ]:
            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name="",
                    action="DASHBOARD_MENU",
                    last_customer=""
                )
            )
            db.commit()
            send_message(phone, build_dashboard_menu_message())
            return {"status": "dashboard_menu"}

        summary = get_dashboard_summary(db, business_owner_phone, period, visible_recorded_by_id)
        send_message(phone, build_dashboard_summary_message(summary, period, user))
        return {"status": "dashboard_summary"}

    if command_type == "BIGGEST_DEBTOR":
        debtor = get_biggest_debtor(db, business_owner_phone, visible_recorded_by_id)
        if not debtor:
            send_message(phone, "No debtors found.")
            return {"status": "biggest_debtor_empty"}
        send_message(phone, f"Biggest debtor: {debtor['name'].title()}: N{debtor['balance']:,}")
        return {"status": "biggest_debtor"}

    if command_type == "DEBTOR_LEADERBOARD":
        leaderboard = get_debtor_leaderboard(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
        if not leaderboard:
            send_message(phone, "No debtors found.")
            return {"status": "debtor_leaderboard_empty"}
        msg = "Debtor Leaderboard\n\n"
        for index, debtor in enumerate(leaderboard, start=1):
            msg += f"{index}. {debtor['name'].title()}: N{debtor['balance']:,}\n"
        send_message(phone, msg)
        return {"status": "debtor_leaderboard"}

    if command_type == "SEARCH_CUSTOMER":
        customers = search_customers(db, business_owner_phone, parsed.get("query", ""), visible_recorded_by_id)
        if not customers:
            send_message(phone, "Customer not found.")
            return {"status": "search_customer_empty"}
        msg = "Search results\n\n"
        for index, customer in enumerate(customers, start=1):
            msg += f"{index}. {customer.name.title()} -> {customer.customer_phone or 'no phone'}\n"
        send_message(phone, msg)
        return {"status": "search_customer"}

    if command_type == "CUSTOMER_SUMMARY":
        summary = get_customer_summary(db, business_owner_phone, parsed.get("name", ""), visible_recorded_by_id)
        if not summary:
            send_message(phone, "Customer not found.")
            return {"status": "customer_summary_not_found"}
        balance_text = (
            f"credit: N{abs(summary['balance']):,}"
            if summary["balance"] < 0
            else f"balance: N{summary['balance']:,}"
        )
        send_message(
            phone,
            f"{summary['name'].title()} summary\n"
            f"{balance_text}\n"
            f"Bought: N{summary['total_buy']:,}\n"
            f"Paid: N{summary['total_pay']:,}\n"
            f"Transactions: {summary['transaction_count']:,}"
        )
        return {"status": "customer_summary"}

    if command_type == "OVERDUE_DEBTORS":
        overdue_list = get_overdue_debtors(db, business_owner_phone, visible_recorded_by_id)
        if len(overdue_list) == 0:
            send_message(phone, "No overdue debtors.")
            return {"status": "no_overdue"}

        msg = "Overdue Debtors\n\n"
        for index, debtor in enumerate(overdue_list, start=1):
            due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
            msg += (
                f"{index}. {debtor['name']}\n"
                f"Balance: N{debtor['balance']:,}\n"
                f"Due: {due_date_text}\n"
                f"Overdue: {debtor['overdue_days']} days\n\n"
            )
        send_message(phone, msg)
        return {"status": "overdue_direct"}

    if command_type == "UNPAID_DEBTORS":
        debtors, total_outstanding = get_unpaid_debtors(
            db,
            business_owner_phone,
            visible_recorded_by_id,
        )
        if len(debtors) == 0:
            send_message(phone, "No unpaid debtors.")
            return {"status": "no_debtors"}

        msg = "Unpaid Debtors\n\n"
        for index, debtor in enumerate(debtors, start=1):
            msg += f"{index}. {debtor['name'].title()}: N{debtor['balance']:,}\n"

        msg += f"\nTotal Outstanding: N{total_outstanding:,}"
        send_message(phone, msg)
        return {"status": "unpaid_debtors"}

    if command_type == "MARGIN_REPORT":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Margin reports")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "margin_report_plan_blocked"}

        period = parsed.get("period")
        summary = get_margin_summary(db, business_owner_phone, period, visible_recorded_by_id)
        send_message(phone, build_margin_summary_message(summary, period))
        return {"status": "margin_report"}

    if command_type == "BELOW_COST_PRODUCTS":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "below_cost_plan_blocked"}

        items = get_products_below_cost(db, business_owner_phone)
        if not items:
            send_message(phone, "No products are currently set below cost price.")
            return {"status": "no_below_cost"}

        lines = ["Products selling below cost:\n"]
        for item in items:
            unit_label = f" {item.unit}" if item.unit else ""
            diff = item.cost_price - item.selling_price
            lines.append(
                f"- {item.name.title()}{unit_label}\n"
                f"  Cost: N{item.cost_price:,}  Sell: N{item.selling_price:,}  "
                f"Loss/unit: N{diff:,}"
            )
        send_message(phone, "\n".join(lines))
        return {"status": "below_cost_products"}

    return None
