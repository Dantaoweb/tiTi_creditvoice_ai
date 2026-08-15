from datetime import datetime, timedelta, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

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

    # Fast path: the denormalized column (maintained by the Transaction event
    # listeners in models.py). A per-staff view can't be served by it, and a
    # NULL column (pre-backfill row) falls through to the authoritative sum.
    if not recorded_by_id:
        stored = db.query(Customer.balance).filter(Customer.id == customer_id).scalar()
        if stored is not None:
            return stored

    buy_query = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "BUY",
        Transaction.is_voided != True,
    )

    pay_query = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "PAY",
        Transaction.is_voided != True,
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
    now = _utcnow()
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


def get_owner_transaction_query(db, owner_phone, period=None, recorded_by_id=None, include_voided=False, branch_id=None):
    query = db.query(Transaction).outerjoin(Customer, Transaction.customer_id == Customer.id)
    if not include_voided:
        query = query.filter(Transaction.is_voided != True)
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
    if branch_id:
        query = query.filter(Transaction.branch_id == int(branch_id))
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
    return query


def get_transaction_stats(db, owner_phone, period=None, recorded_by_id=None, branch_id=None):
    query = get_owner_transaction_query(db, owner_phone, period, recorded_by_id, branch_id=branch_id)
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


def get_dashboard_summary(db, owner_phone=None, period=None, recorded_by_id=None, branch_id=None):
    stats = get_transaction_stats(db, owner_phone, period, recorded_by_id, branch_id=branch_id)
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


def build_dashboard_summary_message(summary, period=None, user=None):
    from biz_language import get_lang
    L = get_lang(user)
    period_label = dashboard_period_label(period)
    return (
        f"Dashboard {period_label}:\n"
        f"{L['total_customers']}: {summary['total_customers']:,}\n"
        f"{L['new_customers']}: {summary['new_customers']:,}\n"
        f"{L['paid_customers']}: {summary['paid_customers']:,}\n"
        f"Transactions: {summary['total_transactions']:,}\n"
        f"{L['credit_sales']}: N{summary['credit_sales_amount']:,}\n"
        f"{L['direct_sales']}: N{summary['direct_sales_amount']:,}\n"
        f"{L['total_sales']}: N{summary['total_sales_amount']:,}\n"
        f"{L['payments']}: N{summary['total_pay_amount']:,}\n"
        f"{L['outstanding']}: N{summary['total_outstanding']:,}"
    )


def get_margin_summary(db, owner_phone, period=None, recorded_by_id=None, branch_id=None):
    """
    Compare expected revenue (at selling price) vs actual revenue recorded.
    Returns a dict with: expected, actual, discount_gap, below_cost_products.
    Only meaningful when inventory items have selling_price set.
    """
    from models import InventoryItem, TransactionItem
    start, end = get_period_range(period) if period else (None, None)

    tx_query = db.query(TransactionItem).join(
        Transaction, TransactionItem.transaction_id == Transaction.id
    ).filter(Transaction.type == "BUY")

    if recorded_by_id:
        tx_query = tx_query.filter(Transaction.recorded_by_id == recorded_by_id)
    if branch_id is not None:
        tx_query = tx_query.filter(Transaction.branch_id == branch_id)
    if start:
        tx_query = tx_query.filter(Transaction.created_at >= start, Transaction.created_at < end)

    items = tx_query.all()
    actual = sum(i.total or 0 for i in items)
    expected = 0
    for i in items:
        inv = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone,
            func.lower(InventoryItem.name) == (i.product or "").lower(),
        ).first()
        if inv and inv.selling_price:
            expected += (i.quantity or 1) * inv.selling_price
        else:
            expected += i.total or 0

    below_cost = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.cost_price.isnot(None),
        InventoryItem.selling_price.isnot(None),
        InventoryItem.selling_price < InventoryItem.cost_price,
    ).all()

    return {
        "expected": expected,
        "actual": actual,
        "discount_gap": max(expected - actual, 0),
        "below_cost_products": [i.name for i in below_cost],
    }


def get_products_below_cost(db, owner_phone):
    """Return inventory items where selling_price < cost_price."""
    from models import InventoryItem
    return db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.cost_price.isnot(None),
        InventoryItem.selling_price.isnot(None),
        InventoryItem.selling_price < InventoryItem.cost_price,
    ).all()


def build_margin_summary_message(summary, period=None):
    label = dashboard_period_label(period) if period else "all time"
    lines = [f"Margin summary — {label}:"]
    lines.append(f"Expected revenue: N{summary['expected']:,}")
    lines.append(f"Actual revenue:   N{summary['actual']:,}")
    gap = summary["discount_gap"]
    if gap > 0:
        lines.append(f"Discount gap:     N{gap:,}")
    if summary["below_cost_products"]:
        products = ", ".join(p.title() for p in summary["below_cost_products"][:5])
        lines.append(f"\n⚠ Selling below cost: {products}")
    return "\n".join(lines)


def get_inventory_insights(db, owner_phone, period=None, branch_id=None):
    """Inventory Insights report over a period, tracking cost/price/stock so the
    web report screen can surface: (A) a margin snapshot from current cost vs
    selling price, (B) the price-change log, and (C) stock received. Everything
    is scoped to the owner (and branch when given)."""
    from models import InventoryItem, InventoryMovement, ItemPriceChange

    start, end = get_period_range(period)  # (None, None) = all time

    items_q = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone)
    if branch_id is not None:
        items_q = items_q.filter(InventoryItem.branch_id == branch_id)
    items = items_q.all()
    item_names = {it.id: it.name for it in items}
    item_ids = list(item_names.keys())

    # ── A. Margin snapshot (current cost vs current selling price) ──────────
    margin = []
    for it in items:
        if it.selling_price is None:
            continue  # unpriced draft — nothing to measure
        is_service = it.quantity is None or it.category == "service"
        cost, sell = it.cost_price, it.selling_price
        m = (sell - cost) if cost is not None else None
        pct = round(m / sell * 100) if (m is not None and sell) else None
        if cost is None:
            flag = "no_cost"
        elif m < 0:
            flag = "loss"
        elif pct is not None and pct < 10:
            flag = "thin"
        else:
            flag = None
        margin.append({
            "id": it.id, "name": it.name, "unit": it.unit, "is_service": is_service,
            "cost_price": cost, "selling_price": sell,
            "margin": m, "margin_pct": pct, "flag": flag,
        })
    # Worst first (loss/thin/no-cost surface at the top).
    _rank = {"loss": 0, "thin": 1, "no_cost": 2}
    margin.sort(key=lambda r: (
        _rank.get(r["flag"], 3),
        r["margin_pct"] if r["margin_pct"] is not None else 9999,
    ))

    # ── B. Price changes in period ─────────────────────────────────────────
    price_changes, price_up, price_down = [], 0, 0
    if item_ids:
        pc_q = db.query(ItemPriceChange).filter(
            ItemPriceChange.owner_phone == owner_phone,
            ItemPriceChange.item_id.in_(item_ids),
        )
        if start is not None:
            pc_q = pc_q.filter(ItemPriceChange.created_at >= start,
                               ItemPriceChange.created_at < end)
        pcs = pc_q.order_by(ItemPriceChange.id.desc()).limit(200).all()
        changer_ids = {c.changed_by_id for c in pcs if c.changed_by_id}
        changer_names = {}
        if changer_ids:
            for u in db.query(User).filter(User.id.in_(changer_ids)).all():
                changer_names[u.id] = u.name
        for c in pcs:
            if c.old_price is not None and c.new_price is not None:
                if c.new_price > c.old_price:
                    price_up += 1
                elif c.new_price < c.old_price:
                    price_down += 1
            price_changes.append({
                "id": c.id, "item_id": c.item_id,
                "name": item_names.get(c.item_id, "—"),
                "field": c.field, "old_price": c.old_price, "new_price": c.new_price,
                "changed_by": changer_names.get(c.changed_by_id),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            })

    # ── C. Stock received in period (IN movements) ─────────────────────────
    stock_received, purchasing_spend = [], 0
    if item_ids:
        mv_q = db.query(InventoryMovement).filter(
            InventoryMovement.owner_phone == owner_phone,
            InventoryMovement.item_id.in_(item_ids),
            InventoryMovement.movement_type == "IN",
        )
        if start is not None:
            mv_q = mv_q.filter(InventoryMovement.created_at >= start,
                               InventoryMovement.created_at < end)
        agg = {}
        for m in mv_q.order_by(InventoryMovement.id.asc()).all():
            qty = m.quantity or 0
            up = m.unit_price or 0
            purchasing_spend += qty * up
            a = agg.setdefault(m.item_id, {"qty": 0.0, "spent": 0, "first": None, "last": None})
            a["qty"] += qty
            a["spent"] += qty * up
            if up:
                if a["first"] is None:
                    a["first"] = up
                a["last"] = up
        for iid, a in agg.items():
            avg = round(a["spent"] / a["qty"]) if a["qty"] else None
            trend = None
            if a["first"] and a["last"]:
                trend = "up" if a["last"] > a["first"] else ("down" if a["last"] < a["first"] else None)
            stock_received.append({
                "item_id": iid, "name": item_names.get(iid, "—"),
                "qty": a["qty"], "spent": a["spent"], "avg_cost": avg,
                "first_cost": a["first"], "last_cost": a["last"], "trend": trend,
            })
        stock_received.sort(key=lambda r: r["spent"], reverse=True)

    return {
        "period": period,
        "purchasing_spend": purchasing_spend,
        "price_edits": len(price_changes),
        "price_up": price_up,
        "price_down": price_down,
        "margin": margin,
        "price_changes": price_changes,
        "stock_received": stock_received,
    }


def build_dashboard_menu_message():
    return (
        "Dashboard\n\n"
        "1. Today\n"
        "2. This week\n"
        "3. This month\n"
        "4. This year\n"
        "5. All time\n"
        "6. Customer count\n"
        "7. Customer list\n"
        "8. Unpaid debtors\n"
        "9. Product leaderboard\n"
        "10. Export data (CSV)\n"
        "11. Business statement (PDF)"
    )


def build_dashboard_selection_message(db, owner_phone, selection, recorded_by_id=None, user=None):
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
        return "dashboard_summary", build_dashboard_summary_message(summary, period, user)

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
            if debtor.get("overdue"):
                due_label = f" - OVERDUE {debtor['overdue_days']}d"
            elif debtor.get("due_date"):
                due_label = f" - Due: {debtor['due_date'].strftime('%d/%m/%Y')}"
            else:
                due_label = " - No due date"
            msg += f"{i}. {debtor['name'].title()}: N{debtor['balance']:,}{due_label}\n"
        msg += "\nReply a number to manage."
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


def _get_staff_top_products(db, owner_phone, staff_id, period=None, top_n=5):
    """
    Returns a list of {product, qty, total} sorted by total revenue
    for transactions recorded by a specific staff member.
    Merges TransactionItem rows (multi-item) with Transaction.product (single-item).
    """
    sale_tx_ids = get_owner_transaction_query(
        db, owner_phone, period, recorded_by_id=staff_id
    ).filter(
        Transaction.type.in_(["BUY", "SALE"])
    ).with_entities(Transaction.id, Transaction.product, Transaction.quantity, Transaction.amount).all()

    if not sale_tx_ids:
        return []

    tx_id_list = [row[0] for row in sale_tx_ids]

    # Aggregate from TransactionItem (covers multi-item transactions)
    item_rows = db.query(
        TransactionItem.product,
        func.coalesce(func.sum(TransactionItem.quantity), 0),
        func.coalesce(func.sum(TransactionItem.total), 0),
    ).filter(
        TransactionItem.transaction_id.in_(tx_id_list)
    ).group_by(TransactionItem.product).all()

    # Build product map: {product_lower: [qty, total]}
    product_map = {}
    for product, qty, total in item_rows:
        key = (product or "").lower().strip()
        if not key:
            continue
        if key not in product_map:
            product_map[key] = [0, 0]
        product_map[key][0] += qty
        product_map[key][1] += total

    # Transactions that have no items — use Transaction.product + amount
    tx_ids_with_items = set(
        row[0] for row in db.query(TransactionItem.transaction_id).filter(
            TransactionItem.transaction_id.in_(tx_id_list)
        ).all()
    )
    for tx_id, product, qty, amount in sale_tx_ids:
        if tx_id in tx_ids_with_items:
            continue
        key = (product or "").lower().strip()
        if not key:
            continue
        if key not in product_map:
            product_map[key] = [0, 0]
        product_map[key][0] += qty or 1
        product_map[key][1] += amount or 0

    sorted_products = sorted(product_map.items(), key=lambda x: x[1][1], reverse=True)
    return [
        {"product": p.title(), "qty": v[0], "total": v[1]}
        for p, v in sorted_products[:top_n]
    ]


def get_staff_performance(db, owner_phone, period=None):
    admin_user = db.query(User).filter(User.phone == owner_phone).first()
    if not admin_user:
        return []

    staff_members = db.query(User).filter(User.parent_id == admin_user.id).all()
    if not staff_members:
        return []

    results = []
    for staff in staff_members:
        base = get_owner_transaction_query(db, owner_phone, period, recorded_by_id=staff.id)
        sales = base.filter(
            Transaction.type.in_(["BUY", "SALE"])
        ).with_entities(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).scalar()
        payments = base.filter(
            Transaction.type == "PAY"
        ).with_entities(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).scalar()
        tx_count = base.count()
        customer_ids = base.filter(
            Transaction.customer_id != None
        ).with_entities(Transaction.customer_id).distinct().count()
        top_products = _get_staff_top_products(db, owner_phone, staff.id, period)
        results.append({
            "id": staff.id,
            "name": staff.name,
            "phone": staff.phone,
            "role": staff.role,
            "staff_position": staff.staff_position,
            "staff_salary": staff.staff_salary,
            "sales": sales,
            "payments": payments,
            "transactions": tx_count,
            "customers_served": customer_ids,
            "top_products": top_products,
        })

    results.sort(key=lambda r: r["sales"], reverse=True)
    return results


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


def get_product_sales_by_period(db, owner_phone=None, period=None, recorded_by_id=None, branch_id=None):
    query = get_owner_transaction_query(db, owner_phone, period, recorded_by_id, branch_id=branch_id).filter(
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
    today = _utcnow().date()
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

def get_unpaid_debtors(db, owner_phone=None, recorded_by_id=None, branch_id=None):

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    else:
        # Fast path: filter debtors in SQL via the denormalized balance instead
        # of summing every customer's transactions one by one (was N+1).
        customers = customers.filter(Customer.balance > 0)
    if branch_id is not None:
        customers = customers.filter(Customer.branch_id == branch_id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    debtors = []
    total_outstanding = 0
    today = _utcnow().date()

    for customer in customers:
        balance = customer.balance if not recorded_by_id else get_balance(db, customer.id, recorded_by_id)

        if balance > 0:
            latest_tx = db.query(Transaction).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "BUY",
                Transaction.due_date.isnot(None),
            )
            if recorded_by_id:
                latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
            latest_tx = latest_tx.order_by(Transaction.due_date.desc()).first()

            due_date = latest_tx.due_date if latest_tx else None
            overdue = bool(due_date and due_date.date() < today)
            overdue_days = (today - due_date.date()).days if overdue else 0

            debtors.append({
                "name": customer.name,
                "balance": balance,
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "due_date": due_date,
                "overdue": overdue,
                "overdue_days": overdue_days,
            })

            total_outstanding += balance

    return debtors, total_outstanding

# =========================
# 🛒 PRODUCT BUYERS
# =========================

def get_product_buyers(db, owner_phone, product_name, recorded_by_id=None):
    """
    All customers who have at least one BUY transaction for a given product.
    Sorted: customers with phone numbers first, then alphabetically.
    """
    from collections import defaultdict
    from datetime import datetime

    p = product_name.lower().strip()

    base = db.query(Transaction).join(
        Customer, Customer.id == Transaction.customer_id
    ).filter(
        Customer.owner_phone == owner_phone,
        Transaction.type == "BUY",
        Transaction.is_voided.isnot(True),
    )
    if recorded_by_id:
        base = base.filter(Transaction.recorded_by_id == recorded_by_id)

    # Match the product either in the transaction's own product field (simple
    # single-product sales) or in any line item (itemised / cart sales, which
    # store Transaction.product as a comma-joined summary like "sugar, rice").
    direct = base.filter(func.lower(Transaction.product) == p)
    itemised = base.join(
        TransactionItem, TransactionItem.transaction_id == Transaction.id
    ).filter(func.lower(TransactionItem.product) == p)

    # A sale can match both paths, or an itemised sale can carry the product on
    # more than one line — dedupe by transaction id.
    txs_by_id = {tx.id: tx for tx in list(direct) + list(itemised)}
    txs = sorted(txs_by_id.values(), key=lambda t: t.created_at or datetime.min, reverse=True)

    customer_data = defaultdict(lambda: {"count": 0, "last": None, "obj": None})
    for tx in txs:
        entry = customer_data[tx.customer_id]
        entry["count"] += 1
        if entry["last"] is None:
            entry["last"] = tx.created_at
        if entry["obj"] is None:
            entry["obj"] = db.query(Customer).filter(Customer.id == tx.customer_id).first()

    result = []
    for customer_id, data in customer_data.items():
        c = data["obj"]
        if not c:
            continue
        result.append({
            "customer_id": customer_id,
            "name": c.name,
            "customer_phone": c.customer_phone,
            "buy_count": data["count"],
            "last_bought": data["last"],
        })

    result.sort(key=lambda x: (x["customer_phone"] is None, x["name"]))
    return result

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

    today = _utcnow()

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

    today = _utcnow().date()

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
        _utcnow().date()
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


# =========================
# 📅 DUE THIS WEEK
# =========================

def get_due_this_week(db, owner_phone=None, recorded_by_id=None):

    due_list = []

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    today = _utcnow().date()
    week_end = today + timedelta(days=7)

    for customer in customers:
        balance = get_balance(db, customer.id, recorded_by_id)
        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None),
        )
        if recorded_by_id:
            latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
        latest_tx = latest_tx.order_by(Transaction.due_date.desc()).first()

        if not latest_tx:
            continue

        due_date = latest_tx.due_date.date()
        if today <= due_date <= week_end:
            due_list.append({
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date,
            })

    return due_list


# =========================
# 📊 CONVERSATIONAL ANALYTICS
# =========================

def get_period_comparison(db, owner_phone, recorded_by_id=None):
    """
    Compare this calendar month vs last calendar month.
    Returns totals, change, and top customers who went quiet.
    """
    now = _utcnow()
    # This month: 1st of current month → now
    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_end = now
    # Last month: 1st of prev month → last day of prev month
    if this_start.month == 1:
        last_start = this_start.replace(year=this_start.year - 1, month=12)
    else:
        last_start = this_start.replace(month=this_start.month - 1)
    last_end = this_start

    def _sales(start, end):
        return db.query(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).outerjoin(
            Customer, Transaction.customer_id == Customer.id
        ).filter(
            func.coalesce(Customer.owner_phone, owner_phone) == owner_phone,
            Transaction.type.in_(["BUY", "SALE"]),
            Transaction.created_at >= start,
            Transaction.created_at < end,
        ).scalar()

    def _active_customers(start, end):
        rows = db.query(Customer.name, func.coalesce(func.sum(Transaction.amount), 0)).join(
            Transaction, Transaction.customer_id == Customer.id
        ).filter(
            Customer.owner_phone == owner_phone,
            Transaction.type == "BUY",
            Transaction.created_at >= start,
            Transaction.created_at < end,
        ).group_by(Customer.name).order_by(
            func.coalesce(func.sum(Transaction.amount), 0).desc()
        ).limit(5).all()
        return [(name, amt) for name, amt in rows]

    this_sales = _sales(this_start, this_end)
    last_sales = _sales(last_start, last_end)
    this_customers = _active_customers(this_start, this_end)
    last_customers = _active_customers(last_start, last_end)

    this_names = {name for name, _ in this_customers}
    quiet = [(name, amt) for name, amt in last_customers if name not in this_names]

    change = this_sales - last_sales
    pct = int(abs(change) * 100 / last_sales) if last_sales else 0

    return {
        "this_month": this_sales,
        "last_month": last_sales,
        "change": change,
        "change_pct": pct,
        "direction": "up" if change >= 0 else "down",
        "this_top_customers": this_customers,
        "quiet_customers": quiet,  # bought last month, silent this month
    }


def get_sales_by_day_of_week(db, owner_phone, recorded_by_id=None):
    """
    Aggregate sales by day of week over last 90 days.
    Returns list of (day_name, total_sales) sorted by total desc.
    """
    cutoff = _utcnow() - timedelta(days=90)
    rows = db.query(
        Transaction.created_at, Transaction.amount
    ).outerjoin(
        Customer, Transaction.customer_id == Customer.id
    ).filter(
        func.coalesce(Customer.owner_phone, owner_phone) == owner_phone,
        Transaction.type.in_(["BUY", "SALE"]),
        Transaction.created_at >= cutoff,
    ).all()

    day_totals = {i: 0 for i in range(7)}
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for created_at, amount in rows:
        if created_at:
            day_totals[created_at.weekday()] += (amount or 0)

    ranked = sorted(
        [(day_names[i], day_totals[i]) for i in range(7)],
        key=lambda x: x[1],
        reverse=True
    )
    return ranked


def get_product_profit_detail(db, owner_phone, product_name, recorded_by_id=None):
    """
    For a specific product: sales volume, actual revenue, cost price,
    expected revenue at standard selling price, margin.
    """
    from models import InventoryItem, TransactionItem

    product_lower = product_name.lower().strip()

    item = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name).like(f"%{product_lower}%"),
    ).first()

    tx_items = db.query(TransactionItem).join(
        Transaction, TransactionItem.transaction_id == Transaction.id
    ).outerjoin(
        Customer, Transaction.customer_id == Customer.id
    ).filter(
        func.coalesce(Customer.owner_phone, owner_phone) == owner_phone,
        Transaction.type.in_(["BUY", "SALE"]),
        func.lower(TransactionItem.product).like(f"%{product_lower}%"),
    ).all()

    # Also pick up simple transactions recorded with Transaction.product directly
    direct_txns = db.query(Transaction).outerjoin(
        Customer, Transaction.customer_id == Customer.id
    ).filter(
        func.coalesce(Customer.owner_phone, owner_phone) == owner_phone,
        Transaction.type.in_(["BUY", "SALE"]),
        func.lower(Transaction.product).like(f"%{product_lower}%"),
        ~Transaction.id.in_([ti.transaction_id for ti in tx_items]),
    ).all() if not tx_items else []

    total_qty = (
        sum(ti.quantity or 1 for ti in tx_items) +
        sum(tx.quantity or 1 for tx in direct_txns)
    )
    total_revenue = (
        sum(ti.total or 0 for ti in tx_items) +
        sum(tx.amount or 0 for tx in direct_txns)
    )
    unit_prices = (
        [ti.unit_price for ti in tx_items if ti.unit_price] +
        [tx.unit_price for tx in direct_txns if tx.unit_price]
    )
    avg_sell_price = int(sum(unit_prices) / len(unit_prices)) if unit_prices else 0
    tx_count = len(tx_items) + len(direct_txns)

    cost_price = item.cost_price if item else None
    selling_price = item.selling_price if item else None
    stock_qty = item.quantity if item else None
    unit = item.unit if item else None

    expected_revenue = (selling_price * total_qty) if selling_price and total_qty else None
    cost_of_sales = (cost_price * total_qty) if cost_price and total_qty else None
    gross_profit = (total_revenue - cost_of_sales) if cost_of_sales is not None else None

    return {
        "product": product_name,
        "unit": unit,
        "total_qty_sold": total_qty,
        "total_revenue": total_revenue,
        "avg_sell_price": avg_sell_price,
        "standard_sell_price": selling_price,
        "cost_price": cost_price,
        "expected_revenue": expected_revenue,
        "cost_of_sales": cost_of_sales,
        "gross_profit": gross_profit,
        "stock_remaining": stock_qty,
        "transaction_count": tx_count,
    }

