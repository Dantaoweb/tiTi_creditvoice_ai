"""
Conversational business analytics — ARES format responses.

Handles natural language questions that query the owner's actual records
and return narrative answers, not just data dumps.
"""
from reports import (
    get_debtor_leaderboard,
    get_period_comparison,
    get_product_profit_detail,
    get_product_sales_by_period,
    get_sales_by_day_of_week,
    get_unpaid_debtors,
)


def _N(amount):
    return f"N{(amount or 0):,}"


# ── Who owes me the most ──────────────────────────────────────────────────────

def answer_top_debtors(db, owner_phone, send_message, phone, recorded_by_id=None):
    debtors = get_debtor_leaderboard(db, owner_phone, limit=5, recorded_by_id=recorded_by_id)
    _, total_outstanding = get_unpaid_debtors(db, owner_phone, recorded_by_id)

    if not debtors:
        send_message(phone,
            "*Answer:*\nNo outstanding debts. All your customers are up to date."
        )
        return {"status": "analytics_no_debtors"}

    lines = ["*Answer:*\nTop customers by outstanding balance:\n"]
    for i, d in enumerate(debtors, 1):
        lines.append(f"{i}. {d['name'].title()} — {_N(d['balance'])}")

    lines.append(f"\n*Reason:*\nThese customers have the largest unpaid balances from credit sales.")

    lines.append(f"\n*Elaborate:*\nTotal outstanding across all customers: {_N(total_outstanding)}")

    if debtors[0]["balance"] > 0:
        top_name = debtors[0]["name"].title()
        lines.append(f"{top_name} is your biggest debtor at {_N(debtors[0]['balance'])}.")

    lines.append(f"\n*Suggest:*\nSend payment reminders:\nsend reminders\n"
                 f"Or check one customer:\n{debtors[0]['name']} balance")

    send_message(phone, "\n".join(lines))
    return {"status": "analytics_top_debtors"}


# ── Why are sales declining ───────────────────────────────────────────────────

def answer_sales_trend(db, owner_phone, send_message, phone, recorded_by_id=None):
    data = get_period_comparison(db, owner_phone, recorded_by_id)

    this = data["this_month"]
    last = data["last_month"]
    change = data["change"]
    pct = data["change_pct"]
    direction = data["direction"]
    quiet = data["quiet_customers"]
    top_this = data["this_top_customers"]

    if last == 0 and this == 0:
        send_message(phone,
            "*Answer:*\nNo sales recorded yet for comparison.\n\n"
            "*Suggest:*\nRecord your first sale to start tracking trends."
        )
        return {"status": "analytics_no_sales_data"}

    arrow = "up" if direction == "up" else "down"
    change_line = (
        f"Sales are *{arrow}* {_N(abs(change))} ({pct}%) vs last month."
    )

    lines = [f"*Answer:*\n{change_line}\n"]
    lines.append(f"This month:  {_N(this)}")
    lines.append(f"Last month: {_N(last)}")

    lines.append("\n*Reason:*")
    if direction == "down":
        if quiet:
            names = ", ".join(n.title() for n, _ in quiet[:3])
            lines.append(f"Customers who were active last month but haven't bought yet this month: {names}.")
        else:
            lines.append("No major customer drop-off detected — lower order sizes may be the cause.")
    else:
        if top_this:
            names = ", ".join(n.title() for n, _ in top_this[:3])
            lines.append(f"Strong buyers this month: {names}.")

    lines.append("\n*Elaborate:*")
    if top_this:
        lines.append("Top buyers this month:")
        for name, amt in top_this[:3]:
            lines.append(f"  {name.title()} — {_N(amt)}")
    if quiet:
        lines.append("Silent this month (bought last month):")
        for name, amt in quiet[:3]:
            lines.append(f"  {name.title()} — bought {_N(amt)} last month")

    lines.append("\n*Suggest:*")
    if direction == "down" and quiet:
        quiet_name = quiet[0][0]
        lines.append(f"Follow up with inactive customers.\nOr send: {quiet_name} balance")
    else:
        lines.append("Keep tracking: sales today\nOr check: dashboard")

    send_message(phone, "\n".join(lines))
    return {"status": "analytics_sales_trend"}


# ── What sells most ───────────────────────────────────────────────────────────

def answer_best_product(db, owner_phone, send_message, phone, period=None, recorded_by_id=None):
    rows = get_product_sales_by_period(db, owner_phone, period, recorded_by_id)

    if not rows:
        send_message(phone,
            "*Answer:*\nNo product sales recorded yet.\n\n"
            "*Suggest:*\nStart selling and tiTi will track your top products."
        )
        return {"status": "analytics_no_product_data"}

    period_label = {"MONTH": "this month", "WEEK": "this week", "TODAY": "today",
                    "YEAR": "this year"}.get(period, "all time")

    lines = [f"*Answer:*\nYour best selling products {period_label}:\n"]
    for i, row in enumerate(rows[:5], 1):
        unit = f" {row.unit}" if getattr(row, "unit", None) else ""
        lines.append(f"{i}. {row.product.title()} — {row.total_quantity:,}{unit} sold / {_N(row.total_amount)}")

    top = rows[0]
    lines.append(f"\n*Reason:*\n{top.product.title()} leads in {'volume' if top.total_quantity > 1 else 'revenue'}.")

    lines.append(f"\n*Elaborate:*\nTotal products tracked: {len(rows)}")
    if len(rows) > 5:
        lines.append(f"Showing top 5 of {len(rows)}.")

    lines.append(f"\n*Suggest:*\nCheck profit on your top product:\nis {top.product} profitable\n"
                 f"Or see full margin report:\nmargin report")

    send_message(phone, "\n".join(lines))
    return {"status": "analytics_best_product"}


# ── When am I busiest ─────────────────────────────────────────────────────────

def answer_busiest_period(db, owner_phone, send_message, phone, recorded_by_id=None):
    ranked = get_sales_by_day_of_week(db, owner_phone, recorded_by_id)
    active = [(day, amt) for day, amt in ranked if amt > 0]

    if not active:
        send_message(phone,
            "*Answer:*\nNot enough sales data yet for day-of-week analysis.\n\n"
            "*Suggest:*\nKeep recording sales and tiTi will identify your busiest days."
        )
        return {"status": "analytics_no_day_data"}

    busiest_day, busiest_amt = active[0]
    quietest_day, quietest_amt = active[-1]

    lines = [f"*Answer:*\n*{busiest_day}* is your busiest day — {_N(busiest_amt)} in sales over the last 90 days.\n"]

    lines.append("*Reason:*")
    lines.append(f"Based on all your sales in the last 3 months, grouped by day of week.")

    lines.append("\n*Elaborate:*\nSales by day (last 90 days):")
    for day, amt in active:
        bar = "▓" * min(int(amt * 15 / busiest_amt), 15) if busiest_amt else ""
        lines.append(f"  {day[:3]}: {bar} {_N(amt)}")

    lines.append(f"\n*Suggest:*\nPrepare more stock before {busiest_day}.\n"
                 f"Consider fast mode on your busy days:\nfast mode on")

    send_message(phone, "\n".join(lines))
    return {"status": "analytics_busiest_period"}


# ── Is [product] profitable ───────────────────────────────────────────────────

def answer_product_profit(db, owner_phone, product_name, send_message, phone, recorded_by_id=None):
    data = get_product_profit_detail(db, owner_phone, product_name, recorded_by_id)

    if not data["transaction_count"]:
        send_message(phone,
            f"*Answer:*\nNo sales recorded for {product_name.title()} yet.\n\n"
            f"*Suggest:*\nAdd it to stock with a cost and selling price:\n"
            f"add stock {product_name} cost [price] sell [price]"
        )
        return {"status": "analytics_no_product_found"}

    lines = [f"*Answer:*\n{data['product'].title()} — ", ]

    if data["gross_profit"] is not None:
        if data["gross_profit"] > 0:
            margin_pct = int(data["gross_profit"] * 100 / data["total_revenue"]) if data["total_revenue"] else 0
            lines[0] += f"profitable. {margin_pct}% gross margin."
        else:
            lines[0] += f"selling at a loss."
    else:
        lines[0] += f"revenue: {_N(data['total_revenue'])}."

    lines.append(f"\n*Reason:*")
    if data["cost_price"] and data["avg_sell_price"]:
        lines.append(f"Cost price: {_N(data['cost_price'])}")
        lines.append(f"Average sell price: {_N(data['avg_sell_price'])}")
        diff = data["avg_sell_price"] - data["cost_price"]
        lines.append(f"Margin per unit: {_N(diff)} ({'profit' if diff >= 0 else 'loss'})")

    lines.append(f"\n*Elaborate:*")
    unit = f" {data['unit']}" if data["unit"] else ""
    lines.append(f"Total sold: {data['total_qty_sold']:,}{unit} across {data['transaction_count']} transactions")
    lines.append(f"Total revenue: {_N(data['total_revenue'])}")
    if data["cost_of_sales"]:
        lines.append(f"Cost of sales: {_N(data['cost_of_sales'])}")
    if data["gross_profit"] is not None:
        lines.append(f"Gross profit: {_N(data['gross_profit'])}")
    if data["stock_remaining"] is not None:
        lines.append(f"Stock remaining: {data['stock_remaining']:,}{unit}")

    lines.append(f"\n*Suggest:*")
    if data["gross_profit"] is not None and data["gross_profit"] < 0:
        lines.append(f"You are selling {product_name.title()} below cost. Consider raising the price:\n"
                     f"add stock {product_name} cost {data['cost_price'] or ''} sell [new price]")
    else:
        lines.append(f"See all products below cost:\nproducts below cost\nOr full margin:\nmargin report")

    send_message(phone, "\n".join(lines))
    return {"status": "analytics_product_profit"}


# ── Dispatcher ────────────────────────────────────────────────────────────────

def handle_analytics_command(db, phone, parsed, user, business_owner_phone,
                              visible_recorded_by_id, send_message):
    ptype = parsed.get("type")

    if ptype == "CONVO_TOP_DEBTORS":
        return answer_top_debtors(db, business_owner_phone, send_message, phone, visible_recorded_by_id)

    if ptype == "CONVO_SALES_TREND":
        return answer_sales_trend(db, business_owner_phone, send_message, phone, visible_recorded_by_id)

    if ptype == "CONVO_BEST_PRODUCT":
        return answer_best_product(db, business_owner_phone, send_message, phone,
                                   parsed.get("period"), visible_recorded_by_id)

    if ptype == "CONVO_BUSIEST_PERIOD":
        return answer_busiest_period(db, business_owner_phone, send_message, phone, visible_recorded_by_id)

    if ptype == "CONVO_PRODUCT_PROFIT":
        return answer_product_profit(db, business_owner_phone, parsed["product"],
                                     send_message, phone, visible_recorded_by_id)

    return None
