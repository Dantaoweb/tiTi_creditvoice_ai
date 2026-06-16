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

    if command_type == "ADD_TRUCK_WIZARD":
        from truck_commands import start_add_truck_wizard
        return start_add_truck_wizard(db, phone, send_message)

    if command_type == "RECORD_TRIP_WIZARD":
        from truck_commands import start_record_trip_wizard
        return start_record_trip_wizard(db, phone, user, send_message)

    if command_type == "RENAME_PRODUCT":
        from models import InventoryItem as _RenInv
        _old_name = parsed.get("old_name", "").strip()
        _new_name = parsed.get("new_name", "").strip()
        _item = (
            db.query(_RenInv)
            .filter(
                _RenInv.owner_phone == business_owner_phone,
                _RenInv.name.ilike(f"%{_old_name}%"),
            )
            .first()
        )
        if not _item:
            send_message(phone, f"Product '{_old_name}' not found in your stock.\n\nSend *stock* to see your list.")
            return {"status": "rename_product_not_found"}
        _prev = _item.name
        _item.name = _new_name
        db.commit()
        send_message(phone, f"Done. *{_prev.title()}* renamed to *{_new_name.title()}*.")
        return {"status": "rename_product_ok"}

    if command_type in ("EXPORT_TRANSACTIONS", "EXPORT_DEBTORS", "EXPORT_STOCK", "EXPORT_CUSTOMERS"):
        import os as _os_export
        from export_utils import make_export_token

        _type_key = {
            "EXPORT_TRANSACTIONS": "transactions",
            "EXPORT_DEBTORS": "debtors",
            "EXPORT_STOCK": "stock",
            "EXPORT_CUSTOMERS": "customers",
        }[command_type]
        _period = parsed.get("period") or None
        _base_url = _os_export.getenv("APP_BASE_URL", "").rstrip("/")

        if not _base_url:
            send_message(
                phone,
                "Export is available on your web dashboard.\n\n"
                "Open CreditVoice in your browser → Transactions → Export CSV.",
            )
            return {"status": "export_no_base_url"}

        _token = make_export_token(business_owner_phone, _period, _type_key)
        _url = f"{_base_url}/app/api/export/dl/{_token}"
        _labels = {
            "transactions": "Transactions", "debtors": "Unpaid Debtors",
            "stock": "Stock Inventory", "customers": "Customer List",
        }
        _period_label = _period.lower() if _period else "all time"
        send_message(
            phone,
            f"Your {_labels[_type_key]} export ({_period_label}) is ready.\n\n"
            f"Download: {_url}\n\n"
            "Link expires in 24 hours.",
        )
        return {"status": f"export_{_type_key}"}

    if command_type == "LOAN_STATEMENT":
        import os as _os_stmt
        from export_utils import make_export_token
        _base_url = _os_stmt.getenv("APP_BASE_URL", "").rstrip("/")
        if not _base_url:
            send_message(
                phone,
                "Your business statement is available on the web dashboard.\n\n"
                "Open CreditVoice in your browser -> Dashboard -> Download Statement PDF.",
            )
            return {"status": "statement_no_base_url"}
        _token = make_export_token(business_owner_phone, None, "loan_statement")
        _url   = f"{_base_url}/app/api/loan-statement/dl/{_token}"
        send_message(
            phone,
            "Your business statement is ready.\n\n"
            f"Download PDF: {_url}\n\n"
            "The statement includes your revenue, outstanding receivables, stock value, "
            "and transaction history. Useful for bank or microfinance applications.\n\n"
            "Link expires in 24 hours.",
        )
        return {"status": "loan_statement_sent"}

    if command_type == "SET_STUDENT_CLASS":
        from models import Customer as _SetCust
        _s_name = parsed.get("name", "").strip()
        _s_class = parsed.get("class_name", "").strip()
        if not _s_name or not _s_class:
            send_message(phone, "Usage: class [student name] [class]\nExample: class Tunde JSS2")
            return {"status": "set_class_bad_args"}
        _match = (
            db.query(_SetCust)
            .filter(
                _SetCust.owner_phone == business_owner_phone,
                _SetCust.name.ilike(f"%{_s_name}%"),
            )
            .first()
        )
        if not _match:
            send_message(phone, f"Student '{_s_name}' not found.")
            return {"status": "set_class_not_found"}
        _match.category = _s_class.upper()
        db.commit()
        send_message(phone, f"{_match.name.title()} — class set to *{_s_class.upper()}*.")
        return {"status": "set_class_ok"}

    if command_type == "ADD_TRUCK":
        from models import Customer as _TruckCust
        _plate = parsed.get("plate", "").strip().upper()
        _driver = parsed.get("driver", "").strip()
        _driver_ph = parsed.get("driver_phone", "").strip()
        if not _plate:
            send_message(phone, "Please include the truck plate number.\nExample: add truck KJA234AB driver Emeka 08012345678")
            return {"status": "add_truck_no_plate"}
        _existing = (
            db.query(_TruckCust)
            .filter(
                _TruckCust.owner_phone == business_owner_phone,
                _TruckCust.name.ilike(_plate),
                _TruckCust.is_truck.is_(True),
            )
            .first()
        )
        if _existing:
            if _driver:
                _existing.category = _driver
            if _driver_ph:
                _existing.secondary_phone = _driver_ph
            db.commit()
            _drv_line = f"\nDriver: {_existing.category}" if _existing.category else ""
            _ph_line = f"\nDriver Ph: {_existing.secondary_phone}" if _existing.secondary_phone else ""
            send_message(phone, f"Truck updated.\nPlate: {_plate}{_drv_line}{_ph_line}")
            return {"status": "truck_updated"}
        _truck = _TruckCust(
            owner_phone=business_owner_phone,
            name=_plate,
            category=_driver or None,
            secondary_phone=_driver_ph or None,
            is_truck=True,
        )
        db.add(_truck)
        db.commit()
        _drv_line = f"\nDriver: {_driver}" if _driver else ""
        _ph_line = f"\nDriver Ph: {_driver_ph}" if _driver_ph else ""
        send_message(phone, f"Truck registered.\nPlate: {_plate}{_drv_line}{_ph_line}\n\nTo record a trip: {_plate} diesel 5000 litres 1200")
        return {"status": "truck_registered"}

    if command_type == "MY_TRUCKS":
        from models import Customer as _ListTruck
        _trucks = (
            db.query(_ListTruck)
            .filter(
                _ListTruck.owner_phone == business_owner_phone,
                _ListTruck.is_truck.is_(True),
            )
            .order_by(_ListTruck.name)
            .all()
        )
        if not _trucks:
            send_message(phone, "No trucks registered yet.\n\nTo add one:\nadd truck KJA234AB driver Emeka 08012345678")
            return {"status": "no_trucks"}
        lines = [f"Registered Trucks ({len(_trucks)})\n"]
        for i, t in enumerate(_trucks, 1):
            drv = t.category or "—"
            ph = t.secondary_phone or "—"
            lines.append(f"{i}. *{t.name}*\n   Driver: {drv}\n   Phone: {ph}")
        send_message(phone, "\n".join(lines))
        return {"status": "truck_list"}

    if command_type == "CUSTOMER_SUMMARY":
        summary = get_customer_summary(db, business_owner_phone, parsed.get("name", ""), visible_recorded_by_id)
        if not summary:
            send_message(phone, "Customer not found.")
            return {"status": "customer_summary_not_found"}
        balance_text = (
            f"Credit: N{abs(summary['balance']):,}"
            if summary["balance"] < 0
            else f"Balance: N{summary['balance']:,}"
        )
        from models import Customer as _Cust, Transaction as _Tx
        _c = db.query(_Cust).filter(
            _Cust.owner_phone == business_owner_phone,
            _Cust.name == summary["name"],
        ).first()
        _class_line = f"Class: {_c.category}\n" if (_c and _c.category) else ""
        msg = (
            f"{summary['name'].title()} — Account Summary\n\n"
            f"{_class_line}"
            f"{balance_text}\n"
            f"Total bought: N{summary['total_buy']:,}\n"
            f"Total paid:   N{summary['total_pay']:,}\n"
            f"Transactions: {summary['transaction_count']:,}"
        )
        if summary["balance"] > 0:
            if _c:
                _q = db.query(_Tx).filter(
                    _Tx.customer_id == _c.id,
                    _Tx.type == "BUY",
                    _Tx.is_voided.isnot(True),
                )
                if visible_recorded_by_id:
                    _q = _q.filter(_Tx.recorded_by_id == visible_recorded_by_id)
                _recent_buys = _q.order_by(_Tx.created_at.desc()).limit(5).all()
                if _recent_buys:
                    msg += "\n\nRecent credit items:\n"
                    for _b in _recent_buys:
                        _prod = _b.product or "—"
                        _date = _b.created_at.strftime("%d/%m") if _b.created_at else ""
                        msg += f"• {_prod.title()}  N{_b.amount:,}  {_date}\n"
        send_message(phone, msg)
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

    if command_type in ("RESTOCK_NOTIFY", "PRODUCT_BUYERS"):
        if not user:
            send_message(phone, "Register first to use this feature.")
            return {"status": "restock_no_user"}
        from restock_commands import handle_restock_command
        product = parsed.get("product", "")
        if not product:
            send_message(phone, "Which product? E.g. restock rice")
            return {"status": "restock_no_product"}
        return handle_restock_command(
            db, phone, product, user, business_owner_phone, visible_recorded_by_id, send_message
        )

    return None
