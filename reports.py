from datetime import datetime, timedelta

from sqlalchemy import func, or_

from models import Customer, Transaction, TransactionItem, TransactionNote, User

def get_visible_transaction(db, owner_phone, transaction_id, recorded_by_id=None):
    transaction = get_owner_transaction_query(
        db,
        owner_phone,
        recorded_by_id=recorded_by_id
    ).filter(
        Transaction.id == transaction_id
    ).first()
    if not transaction:
        return None

    customer = None
    if transaction.customer_id:
        customer = db.query(Customer).filter(Customer.id == transaction.customer_id).first()
    return transaction, customer


def get_transaction_notes(db, owner_phone, transaction_id, recorded_by_id=None):
    visible_tx = get_visible_transaction(db, owner_phone, transaction_id, recorded_by_id)
    if not visible_tx:
        return None, []

    notes = db.query(TransactionNote, User).outerjoin(
        User,
        TransactionNote.author_user_id == User.id
    ).filter(
        TransactionNote.transaction_id == transaction_id
    ).order_by(
        TransactionNote.created_at.asc()
    ).all()
    return visible_tx, notes


def format_transaction_note_thread(transaction, customer, notes):
    customer_name = customer.name.title() if customer else "Direct Sale"
    msg = (
        f"Transaction #{transaction.id} notes\n"
        f"{customer_name} {transaction.type}: N{transaction.amount:,}\n\n"
    )

    if not notes:
        return msg + "No notes yet."

    for i, (note, author) in enumerate(notes, start=1):
        author_name = author.name.title() if author and author.name else "Unknown"
        note_date = note.created_at.strftime("%d/%m/%Y %H:%M")
        msg += f"{i}. {author_name} ({note_date})\n{note.note}\n\n"
    return msg.strip()


def get_balance(db, customer_id, recorded_by_id=None):

    from sqlalchemy import func

    buy_query = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "BUY"
    )

    pay_query = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "PAY"
    )

    if recorded_by_id:
        buy_query = buy_query.filter(Transaction.recorded_by_id == recorded_by_id)
        pay_query = pay_query.filter(Transaction.recorded_by_id == recorded_by_id)

    total_buy = buy_query.scalar()
    total_pay = pay_query.scalar()

    return total_buy - total_pay


# =========================
# 📊 SALES ANALYTICS
# =========================

def get_today_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "TODAY", recorded_by_id)
    return stats["total_sales"]


def get_weekly_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "WEEK", recorded_by_id)
    return stats["total_sales"]


def get_monthly_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "MONTH", recorded_by_id)
    return stats["total_sales"]


def get_yearly_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "YEAR", recorded_by_id)
    return stats["total_sales"]


def get_period_range(period):
    now = datetime.utcnow()
    if period == "TODAY":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end
    if period == "WEEK":
        start = now - timedelta(days=7)
        return start, now
    if period == "MONTH":
        start = now - timedelta(days=30)
        return start, now
    if period == "YEAR":
        start = now - timedelta(days=365)
        return start, now
    return None, None


def get_owner_transaction_query(db, owner_phone, period=None, recorded_by_id=None):
    query = db.query(Transaction).outerjoin(Customer, Transaction.customer_id == Customer.id)
    if owner_phone:
        business_user_ids = []
        admin_user = db.query(User).filter(User.phone == owner_phone).first()
        if admin_user:
            business_user_ids.append(admin_user.id)
            staff_ids = [
                row.id for row in db.query(User.id).filter(User.parent_id == admin_user.id).all()
            ]
            business_user_ids.extend(staff_ids)

        business_filter = Customer.owner_phone == owner_phone
        if business_user_ids:
            business_filter = or_(
                business_filter,
                Transaction.recorded_by_id.in_(business_user_ids)
            )
        query = query.filter(business_filter)
    if recorded_by_id:
        query = query.filter(Transaction.recorded_by_id == recorded_by_id)
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
    return query


def get_transaction_stats(db, owner_phone, period=None, recorded_by_id=None):
    query = get_owner_transaction_query(db, owner_phone, period, recorded_by_id)
    total_buy = query.filter(Transaction.type == "BUY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    direct_sales = query.filter(Transaction.type == "SALE").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    total_pay = query.filter(Transaction.type == "PAY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    transaction_count = query.count()
    return {
        "total_buy": total_buy,
        "credit_sales": total_buy,
        "direct_sales": direct_sales,
        "total_sales": total_buy + direct_sales,
        "total_pay": total_pay,
        "transaction_count": transaction_count
    }


def get_dashboard_summary(db, owner_phone=None, period=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, period, recorded_by_id)
    return {
        "total_customers": get_customer_count(db, owner_phone, None, recorded_by_id),
        "new_customers": get_new_customer_count(db, owner_phone, period, recorded_by_id),
        "paid_customers": get_paid_customer_count(db, owner_phone, period, recorded_by_id),
        "total_transactions": stats["transaction_count"],
        "credit_sales_amount": stats["credit_sales"],
        "direct_sales_amount": stats["direct_sales"],
        "total_sales_amount": stats["total_sales"],
        "total_buy_amount": stats["total_sales"],
        "total_pay_amount": stats["total_pay"],
        "total_outstanding": get_total_outstanding(db, owner_phone, recorded_by_id),
    }


def dashboard_period_label(period):
    labels = {
        "TODAY": "today",
        "WEEK": "this week",
        "MONTH": "this month",
        "YEAR": "this year"
    }
    return labels.get(period, "all time")


def build_dashboard_summary_message(summary, period=None):
    period_label = dashboard_period_label(period)
    return (
        f"Dashboard {period_label}:\n"
        f"Total customers: {summary['total_customers']:,}\n"
        f"New customers: {summary['new_customers']:,}\n"
        f"Paid customers: {summary['paid_customers']:,}\n"
        f"Transactions: {summary['total_transactions']:,}\n"
        f"Credit sales: N{summary['credit_sales_amount']:,}\n"
        f"Direct sales: N{summary['direct_sales_amount']:,}\n"
        f"Total sales: N{summary['total_sales_amount']:,}\n"
        f"Payments received: N{summary['total_pay_amount']:,}\n"
        f"Outstanding balance: N{summary['total_outstanding']:,}"
    )


def build_dashboard_menu_message():
    return (
        "Dashboard Menu\n\n"
        "1. Today dashboard\n"
        "2. This week dashboard\n"
        "3. This month dashboard\n"
        "4. This year dashboard\n"
        "5. All-time dashboard\n"
        "6. Customer count\n"
        "7. Customer list\n"
        "8. Unpaid debtors\n"
        "9. Product leaderboard\n\n"
        "Reply with 1-9.\n"
        "You can also send commands like:\n"
        "dashboard today\n"
        "list customers\n"
        "unpaid debtors\n\n"
        "Send exit, back, done, or cancel to close."
    )


def build_dashboard_selection_message(db, owner_phone, selection, recorded_by_id=None):
    period_options = {
        "1": "TODAY",
        "2": "WEEK",
        "3": "MONTH",
        "4": "YEAR",
        "5": None
    }

    if selection in period_options:
        period = period_options[selection]
        summary = get_dashboard_summary(db, owner_phone, period, recorded_by_id)
        return "dashboard_summary", build_dashboard_summary_message(summary, period)

    if selection == "6":
        count = get_customer_count(db, owner_phone, None, recorded_by_id)
        return "dashboard_customer_count", f"Customers all time: {count:,}"

    if selection == "7":
        customers = list_customers(db, owner_phone, None, recorded_by_id)
        if not customers:
            return "dashboard_customer_list_empty", "No customers found."

        msg = "Customers\n\n"
        for i, customer in enumerate(customers, start=1):
            msg += (
                f"{i}. {customer['name'].title()}"
                f" ({customer['phone'] or 'no phone'}): N{customer['balance']:,}\n"
            )
        return "dashboard_customer_list", msg

    if selection == "8":
        debtors, total_outstanding = get_unpaid_debtors(db, owner_phone, recorded_by_id)
        if not debtors:
            return "dashboard_unpaid_empty", "No unpaid debtors found."

        msg = f"Unpaid Debtors\nTotal outstanding: N{total_outstanding:,}\n\n"
        for i, debtor in enumerate(debtors, start=1):
            msg += f"{i}. {debtor['name'].title()}: N{debtor['balance']:,}\n"
        return "dashboard_unpaid_debtors", msg

    if selection == "9":
        results = get_product_sales_by_period(db, owner_phone, recorded_by_id=recorded_by_id)
        if not results:
            return "dashboard_products_empty", "No product sales data available yet."

        msg = "Product Leaderboard by Quantity\n\n"
        for i, row in enumerate(results[:10], start=1):
            unit_label = "unit" if row.total_quantity == 1 else "units"
            msg += (
                f"{i}. {row.product.title()} -> "
                f"{row.total_quantity:,} {unit_label}, N{row.total_amount:,}\n"
            )
        return "dashboard_product_leaderboard", msg

    return None, None


def get_total_outstanding(db, owner_phone=None, recorded_by_id=None):
    debtors, total_outstanding = get_unpaid_debtors(db, owner_phone, recorded_by_id)
    return total_outstanding


def get_customer_count(db, owner_phone=None, period=None, recorded_by_id=None):
    query = db.query(Customer)
    if recorded_by_id:
        query = query.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if period:
        start, end = get_period_range(period)
        if start and end:
            if recorded_by_id:
                query = query.filter(
                    Transaction.created_at >= start,
                    Transaction.created_at < end
                )
            else:
                query = query.filter(
                    Customer.created_at >= start,
                    Customer.created_at < end
                )
    if recorded_by_id:
        return query.distinct(Customer.id).count()
    return query.count()


def get_new_customer_count(db, owner_phone=None, period=None, recorded_by_id=None):
    return get_customer_count(db, owner_phone, period, recorded_by_id)


def get_paid_customer_count(db, owner_phone=None, period=None, recorded_by_id=None):
    query = db.query(Customer).join(
        Transaction,
        Transaction.customer_id == Customer.id
    ).filter(
        Transaction.type == "PAY"
    )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if recorded_by_id:
        query = query.filter(Transaction.recorded_by_id == recorded_by_id)
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
    return query.distinct(Customer.id).count()


def get_total_transaction_count(db, owner_phone=None, period=None, recorded_by_id=None):
    return get_owner_transaction_query(db, owner_phone, period, recorded_by_id).count()


def list_customers(db, owner_phone=None, period=None, recorded_by_id=None):
    query = db.query(Customer)
    if recorded_by_id:
        query = query.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)

    if period:
        start, end = get_period_range(period)
        if start and end:
            if recorded_by_id:
                query = query.filter(
                    Transaction.created_at >= start,
                    Transaction.created_at < end
                )
            else:
                query = query.filter(
                    Customer.created_at >= start,
                    Customer.created_at < end
                )

    if recorded_by_id:
        query = query.distinct(Customer.id)

    customers = query.all()
    result = []
    for customer in customers:
        result.append({
            "name": customer.name,
            "phone": customer.customer_phone,
            "balance": get_balance(db, customer.id, recorded_by_id)
        })
    return result


def get_biggest_debtor(db, owner_phone=None, recorded_by_id=None):
    debtors, _ = get_unpaid_debtors(db, owner_phone, recorded_by_id)
    if not debtors:
        return None
    return max(debtors, key=lambda item: item["balance"])


def get_debtor_leaderboard(db, owner_phone=None, limit=10, recorded_by_id=None):
    debtors, _ = get_unpaid_debtors(db, owner_phone, recorded_by_id)
    return sorted(debtors, key=lambda item: item["balance"], reverse=True)[:limit]


def get_customer_summary(db, owner_phone, name, recorded_by_id=None):
    customer = db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name == name
    ).first()
    if not customer:
        return None
    buy_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == "BUY"
    )
    pay_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == "PAY"
    )
    tx_query = db.query(Transaction).filter(
        Transaction.customer_id == customer.id
    )
    if recorded_by_id:
        buy_query = buy_query.filter(Transaction.recorded_by_id == recorded_by_id)
        pay_query = pay_query.filter(Transaction.recorded_by_id == recorded_by_id)
        tx_query = tx_query.filter(Transaction.recorded_by_id == recorded_by_id)

    transaction_count = tx_query.count()
    if recorded_by_id and transaction_count == 0:
        return None

    return {
        "name": customer.name,
        "balance": get_balance(db, customer.id, recorded_by_id),
        "total_buy": buy_query.scalar(),
        "total_pay": pay_query.scalar(),
        "transaction_count": transaction_count
    }


def search_customers(db, owner_phone, query_text, recorded_by_id=None):
    query = db.query(Customer)
    if recorded_by_id:
        query = query.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        )
    return query.filter(
        Customer.owner_phone == owner_phone,
        Customer.name.ilike(f"%{query_text}%")
    ).distinct(Customer.id).all()


class ProductSalesRow:
    def __init__(self, product, total_quantity, total_amount):
        self.product = product
        self.total_quantity = total_quantity
        self.total_amount = total_amount


def build_product_sales_rows(transactions, item_rows):
    item_transaction_ids = {row.transaction_id for row in item_rows}
    totals = {}

    for row in item_rows:
        if row.product not in totals:
            totals[row.product] = {"quantity": 0, "amount": 0}
        totals[row.product]["quantity"] += row.quantity or 0
        totals[row.product]["amount"] += row.total or 0

    for tx in transactions:
        if tx.id in item_transaction_ids or not tx.product:
            continue
        if tx.product not in totals:
            totals[tx.product] = {"quantity": 0, "amount": 0}
        totals[tx.product]["quantity"] += tx.quantity or 1
        totals[tx.product]["amount"] += tx.amount or 0

    return sorted(
        [
            ProductSalesRow(product, values["quantity"], values["amount"])
            for product, values in totals.items()
        ],
        key=lambda row: row.total_quantity,
        reverse=True
    )


def get_product_sales_by_period(db, owner_phone=None, period=None, recorded_by_id=None):
    query = get_owner_transaction_query(db, owner_phone, period, recorded_by_id).filter(
        Transaction.type.in_(["BUY", "SALE"])
    )
    transactions = query.all()
    transaction_ids = [tx.id for tx in transactions]
    if not transaction_ids:
        return []

    item_rows = db.query(TransactionItem).filter(
        TransactionItem.transaction_id.in_(transaction_ids)
    ).all()
    return build_product_sales_rows(transactions, item_rows)


def get_most_sold_product(db, owner_phone=None, period=None, recorded_by_id=None):
    results = get_product_sales_by_period(db, owner_phone, period, recorded_by_id)
    if not results:
        return None
    return results[0]


def get_product_sales_by_date(db, owner_phone, date_text, recorded_by_id=None):
    try:
        report_date = datetime.strptime(date_text, "%d/%m/%Y").date()
    except ValueError:
        return None
    start = datetime(report_date.year, report_date.month, report_date.day)
    end = start + timedelta(days=1)

    query = get_owner_transaction_query(db, owner_phone, recorded_by_id=recorded_by_id).filter(
        Transaction.type.in_(["BUY", "SALE"]),
        Transaction.created_at >= start,
        Transaction.created_at < end
    )
    transactions = query.all()
    transaction_ids = [tx.id for tx in transactions]
    if not transaction_ids:
        return []

    item_rows = db.query(TransactionItem).filter(
        TransactionItem.transaction_id.in_(transaction_ids)
    ).all()
    return build_product_sales_rows(transactions, item_rows)


def get_total_paid_today(db, owner_phone=None, recorded_by_id=None):
    today = datetime.utcnow().date()
    query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).join(Customer, Transaction.customer_id == Customer.id)
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if recorded_by_id:
        query = query.filter(Transaction.recorded_by_id == recorded_by_id)
    total = query.filter(
        Transaction.type == "PAY",
        func.date(Transaction.created_at) == today
    ).scalar()
    return total


def get_outstanding_balance(db, owner_phone=None, recorded_by_id=None):
    return get_total_outstanding(db, owner_phone, recorded_by_id)

# =========================
# 📋 UNPAID DEBTORS
# =========================

def get_unpaid_debtors(db, owner_phone=None, recorded_by_id=None):

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    debtors = []

    total_outstanding = 0

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance > 0:
            debtors.append({
                "name": customer.name,
                "balance": balance
            })

            total_outstanding += balance

    return debtors, total_outstanding

# =========================
# ⚠️ OVERDUE DEBTORS
# =========================

def get_overdue_debtors(db, owner_phone=None, recorded_by_id=None):

    overdue_list = []

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    today = datetime.utcnow()

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        )
        if recorded_by_id:
            latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
        latest_tx = latest_tx.order_by(
            Transaction.due_date.desc()
        ).first()

        if not latest_tx:
            continue

        if latest_tx.due_date.date() < today.date():

            overdue_days = (
                today.date()
                - latest_tx.due_date.date()
            ).days

            overdue_list.append({
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date,
                "overdue_days": overdue_days
            })

    return overdue_list

# =========================
# 📅 DUE TODAY
# =========================

def get_due_today(db, owner_phone=None, recorded_by_id=None):

    due_today = []

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    today = datetime.utcnow().date()

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        )
        if recorded_by_id:
            latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
        latest_tx = latest_tx.order_by(
            Transaction.due_date.desc()
        ).first()

        if not latest_tx:
            continue

        due_date = latest_tx.due_date.date()

        if due_date == today:

            due_today.append({
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date
            })

    return due_today

# =========================
# 📅 DUE IN 2 DAYS
# =========================

def get_due_in_2_days(db, owner_phone=None, recorded_by_id=None):

    due_list = []

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    target_date = (
        datetime.utcnow().date()
        + timedelta(days=2)
    )

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        )
        if recorded_by_id:
            latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
        latest_tx = latest_tx.order_by(
            Transaction.due_date.desc()
        ).first()

        if not latest_tx:
            continue

        due_date = latest_tx.due_date.date()

        if due_date == target_date:

            due_list.append({
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date
            })

    return due_list

