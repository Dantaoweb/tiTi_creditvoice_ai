"""
The numbers behind the Insights graphs: how the business moves over time.

One call returns every series for a period, bucketed so a graph has 7–30
points: today by hour, this week and this month by day, this year by month,
all time by month. Times are Nigeria time (WAT).

- sales: what was sold per bucket, paid at once vs on credit (credit notes
  net out — they are negative sales)
- money: cash that came in (paid-at-once sales + payments) vs new debt given
- debt: what customers owed at the end of each bucket
- profit / expenses: owner and authorised staff only (same rule as profit
  everywhere); sales with no known cost are left out, as in profit_from_sales
- top: the five products or services that brought in the most
- busy_days / busy_hours: when the money comes in

Scoped like every report: branch staff see their branch, staff with no branch
their own records.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from models import Transaction, TransactionItem

WAT = timedelta(hours=1)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _local(dt):
    return dt + WAT if dt else None


def _hour_label(h):
    return "12am" if h == 0 else f"{h}am" if h < 12 else "12pm" if h == 12 else f"{h - 12}pm"


def _buckets(period, now_local, first_local=None):
    """[(label, start_local, end_local)] for the period, oldest first."""
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "TODAY":
        return [(_hour_label(h), today + timedelta(hours=h), today + timedelta(hours=h + 1))
                for h in range(0, now_local.hour + 1)], "hour"
    if period in ("WEEK", "MONTH"):
        days = 7 if period == "WEEK" else 30
        out = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            label = DAYS[d.weekday()] if period == "WEEK" else f"{d.day} {MONTHS[d.month - 1]}"
            out.append((label, d, d + timedelta(days=1)))
        return out, "day"
    # YEAR → last 12 months; all time → from the first record (at most 24 months)
    months = 12
    if period not in ("YEAR",) and first_local:
        months = max(1, min(24, (now_local.year - first_local.year) * 12 + now_local.month - first_local.month + 1))
    out = []
    y, m = now_local.year, now_local.month
    starts = []
    for _ in range(months):
        starts.append(datetime(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    starts.reverse()
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else datetime(
            s.year + (s.month == 12), (s.month % 12) + 1, 1)
        out.append((f"{MONTHS[s.month - 1]}" + (f" {str(s.year)[2:]}" if months > 12 else ""), s, e))
    return out, "month"


def build_charts(db, owner_phone, period=None, branch_id=None, recorded_by_id=None,
                 can_see_profit=False, labels=None, now=None):
    from reports import get_owner_transaction_query
    now_local = _local(now or datetime.now(timezone.utc).replace(tzinfo=None))
    period = (period or "").upper() or None

    base = get_owner_transaction_query(db, owner_phone, recorded_by_id=recorded_by_id, branch_id=branch_id)
    first = base.order_by(Transaction.created_at.asc()).first()
    buckets, grain = _buckets(period, now_local, _local(first.created_at) if first else None)
    start_utc = buckets[0][1] - WAT
    end_utc = buckets[-1][2] - WAT

    txs = base.filter(Transaction.created_at >= start_utc, Transaction.created_at < end_utc).all()

    def bucket_of(tx):
        t = _local(tx.created_at)
        for i, (_l, s, e) in enumerate(buckets):
            if s <= t < e:
                return i
        return None

    n = len(buckets)
    cash, credit, collected, new_debt = [0] * n, [0] * n, [0] * n, [0] * n
    by_day, by_hour = defaultdict(int), defaultdict(int)
    sale_txs = []
    for tx in txs:
        i = bucket_of(tx)
        if i is None:
            continue
        amt = int(tx.amount or 0)
        if tx.type == "SALE":
            cash[i] += amt
            collected[i] += amt
        elif tx.type == "BUY":
            credit[i] += amt
            new_debt[i] += amt
        elif tx.type == "PAY":
            collected[i] += amt
        if tx.type in ("SALE", "BUY"):
            sale_txs.append((i, tx))
            t = _local(tx.created_at)
            by_day[t.weekday()] += amt
            by_hour[t.hour] += amt

    # What customers owed at the end of each bucket: everything before the
    # period, then each bucket's credit minus payments on top.
    owed_before = 0
    for tx in base.filter(Transaction.created_at < start_utc,
                          Transaction.type.in_(("BUY", "PAY")), Transaction.customer_id.isnot(None)).all():
        owed_before += int(tx.amount or 0) * (1 if tx.type == "BUY" else -1)
    owed, running = [], owed_before
    pays = [0] * n
    for tx in txs:
        if tx.type == "PAY" and tx.customer_id:
            i = bucket_of(tx)
            if i is not None:
                pays[i] += int(tx.amount or 0)
    for i in range(n):
        running += new_debt[i] - pays[i]
        owed.append(max(running, 0))

    # Top products / services: revenue by line, the sale's discount spread across its lines
    ids = [tx.id for _i, tx in sale_txs]
    lines_by_tx = defaultdict(list)
    if ids:
        for line in db.query(TransactionItem).filter(TransactionItem.transaction_id.in_(ids)).all():
            lines_by_tx[line.transaction_id].append(line)
    revenue_by_name = defaultdict(float)
    per_bucket_lines = defaultdict(list)          # i → [(name, qty, revenue)]
    for i, tx in sale_txs:
        rows = lines_by_tx.get(tx.id)
        amount = float(tx.amount or 0)
        if rows:
            gross = sum(float(r.total or 0) for r in rows) or 1.0
            for r in rows:
                name = (r.product or "").strip().lower()
                rev = amount * float(r.total or 0) / gross
                revenue_by_name[name] += rev
                per_bucket_lines[i].append((name, float(r.quantity or 1), rev))
        else:
            name = (tx.product or "").strip().lower()
            if name.startswith("pos sale") or name.startswith("credit note"):
                name = "other sales"
            revenue_by_name[name] += amount
            per_bucket_lines[i].append((name, float(tx.quantity or 1), amount))
    top = sorted(((k, v) for k, v in revenue_by_name.items() if v > 0), key=lambda kv: -kv[1])[:5]

    profit = expenses = None
    if can_see_profit:
        from business_facts import _avg_cost_by_name
        from expenses import expenses_between
        costs = _avg_cost_by_name(db, owner_phone)
        profit = []
        for i in range(n):
            known = cost = 0.0
            for name, qty, rev in per_bucket_lines.get(i, []):
                if name in costs:
                    known += rev
                    cost += qty * costs[name]
            profit.append(int(round(known - cost)))
        expenses = [expenses_between(db, owner_phone, s - WAT, e - WAT, branch_id) for _l, s, e in buckets]

    lab = labels or {}
    series = [{"label": label, "cash": cash[i], "credit": credit[i], "collected": collected[i],
               "new_debt": new_debt[i], "owed": owed[i],
               **({"profit": profit[i], "expenses": expenses[i]} if profit is not None else {})}
              for i, (label, _s, _e) in enumerate(buckets)]
    hours = [(h, by_hour.get(h, 0)) for h in range(6, 23)]           # trading hours
    return {
        "period": period, "grain": grain, "series": series,
        "totals": {"sales": sum(cash) + sum(credit), "cash": sum(cash), "credit": sum(credit),
                   "collected": sum(collected), "new_debt": sum(new_debt),
                   "owed_now": owed[-1] if owed else 0,
                   **({"profit": sum(profit), "expenses": sum(expenses)} if profit is not None else {})},
        "top": [{"name": k.title() or "Unnamed", "revenue": int(round(v))} for k, v in top],
        "busy_days": [{"label": DAYS[d], "amount": by_day.get(d, 0)} for d in range(7)],
        "busy_hours": [{"label": _hour_label(h), "amount": a} for h, a in hours],
        "profit_hidden": not can_see_profit,
        "labels": {
            "sales": lab.get("total_sales") or "Sales",
            "cash": lab.get("direct_sales") or "Paid at once",
            "credit": lab.get("credit_sales") or "On credit",
            "collected": lab.get("payments") or "Money received",
        },
    }
