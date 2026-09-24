"""
Business scorecard — the evidence CreditVoice supplies to finance partners.

CreditVoice does not lend and carries no credit risk: a partner does its own
underwriting. What this module produces is EVIDENCE from what the business
already records — how much it sells, how steadily, at what margin, whether its
customers come back and pay, whether it pays its own suppliers — plus how much
of that is corroborated rather than merely typed in.

Every threshold, weight and tier lives in ScorecardConfig and is editable by
admin, so a new partner or a changed criterion never needs a code change. A
generated report stores the config version that produced it, so a score can
still be explained after the rules are re-tuned.
"""
import json
from datetime import timedelta

from sqlalchemy import func

from models import (
    Customer, InventoryItem, InventoryMovement, ScorecardConfig, SubscriptionPayment,
    SupplierPurchase, Transaction, User, utcnow,
)

# ── Default rules ────────────────────────────────────────────────────────────
# Deliberately generic: a motorcycle financier and a freezer vendor both fit.
# `full` = the value scoring 100 for that component, `zero` = the value scoring
# 0; scoring is linear between them, and reversed when higher_is_better is false.
DEFAULT_CONFIG = {
    "window_months": 6,          # how far back the metrics look
    "min_months_recorded": 1,    # below this, no score is produced at all
    "components": {
        "sales_volume": {
            "label": "Monthly sales", "metric": "avg_monthly_sales",
            "weight": 20, "zero": 0, "full": 1_000_000, "higher_is_better": True,
        },
        "sales_floor": {
            "label": "Worst month", "metric": "min_monthly_sales",
            "weight": 10, "zero": 0, "full": 500_000, "higher_is_better": True,
        },
        "consistency": {
            "label": "Recording consistency", "metric": "avg_active_days_per_month",
            "weight": 15, "zero": 2, "full": 20, "higher_is_better": True,
        },
        "tenure": {
            "label": "Track record", "metric": "months_recorded",
            "weight": 15, "zero": 1, "full": 12, "higher_is_better": True,
        },
        "margin": {
            "label": "Gross margin", "metric": "gross_margin_pct",
            "weight": 10, "zero": 0, "full": 30, "higher_is_better": True,
        },
        "repeat_customers": {
            "label": "Customers who return", "metric": "repeat_customer_pct",
            "weight": 10, "zero": 0, "full": 50, "higher_is_better": True,
        },
        "collections": {
            "label": "Credit collected", "metric": "collection_rate_pct",
            "weight": 10, "zero": 30, "full": 90, "higher_is_better": True,
        },
        "supplier_discipline": {
            "label": "Pays suppliers", "metric": "supplier_paid_pct",
            "weight": 10, "zero": 40, "full": 100, "higher_is_better": True,
        },
    },
    # Highest cut-off that the score reaches wins; below the lowest → "Unrated".
    "tiers": [
        {"name": "Emerging", "min_score": 0},
        {"name": "Established", "min_score": 45},
        {"name": "Strong", "min_score": 65},
        {"name": "Excellent", "min_score": 80},
    ],
    # Confidence = how much of the picture is evidenced rather than assumed.
    "confidence": {
        "months_full": 6,              # months of records for full marks
        "active_days_full": 15,        # recording days per month for full marks
        "corroboration_full": 60,      # % of revenue tied to a named customer
    },
    "unrated_label": "Unrated",
}


def _default_config_row(db, updated_by=None):
    row = ScorecardConfig(
        version=1, config_json=json.dumps(DEFAULT_CONFIG), is_active=True,
        note="Built-in defaults", updated_by=updated_by,
    )
    db.add(row)
    db.commit()
    return row


def active_config(db):
    """(version, config dict) — creating the default row on first use."""
    row = (
        db.query(ScorecardConfig)
        .filter(ScorecardConfig.is_active == True)  # noqa: E712
        .order_by(ScorecardConfig.version.desc())
        .first()
    )
    if not row:
        row = _default_config_row(db)
    try:
        cfg = json.loads(row.config_json)
    except (ValueError, TypeError):
        cfg = dict(DEFAULT_CONFIG)
    # Missing keys fall back to defaults so a partial edit can't break scoring.
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg or {})
    return row.version, merged


def save_config(db, config, updated_by=None, note=None):
    """Store a new active version (the previous one is kept for old reports)."""
    latest = db.query(func.max(ScorecardConfig.version)).scalar() or 0
    db.query(ScorecardConfig).filter(ScorecardConfig.is_active == True).update(  # noqa: E712
        {"is_active": False}, synchronize_session=False
    )
    row = ScorecardConfig(
        version=latest + 1, config_json=json.dumps(config), is_active=True,
        note=note, updated_by=updated_by,
    )
    db.add(row)
    db.commit()
    return row


# ── Metrics ──────────────────────────────────────────────────────────────────

def _month_key(dt):
    return dt.strftime("%Y-%m")


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def compute_metrics(db, owner_phone, window_months=6):
    """Everything measurable about this business's trading record.

    Revenue counts cash sales (SALE) and credit sales (BUY) — a credit sale is
    revenue when it happens; PAY rows are collections against it, not new sales.
    """
    from reports import get_owner_transaction_query

    now = utcnow()
    start = now - timedelta(days=30 * window_months)
    owner = db.query(User).filter(User.phone == owner_phone).first()

    txs = (
        get_owner_transaction_query(db, owner_phone)
        .filter(Transaction.created_at >= start)
        .all()
    )

    by_month, active_days, revenue, credit_sales, collected = {}, set(), 0, 0, 0
    revenue_with_customer = 0
    first_record = None
    for tx in txs:
        when = tx.created_at
        if not when:
            continue
        first_record = when if first_record is None or when < first_record else first_record
        amount = int(tx.amount or 0)
        if tx.type in ("SALE", "BUY"):
            revenue += amount
            by_month[_month_key(when)] = by_month.get(_month_key(when), 0) + amount
            active_days.add(when.date())
            if tx.customer_id:
                revenue_with_customer += amount
            if tx.type == "BUY":
                credit_sales += amount
        elif tx.type == "PAY":
            collected += amount
            active_days.add(when.date())

    months_recorded = len(by_month)
    # The floor matters more than the average to anyone sizing a weekly
    # repayment, but the current (part) month would understate it unfairly.
    this_month = _month_key(now)
    complete_months = {m: v for m, v in by_month.items() if m != this_month}
    avg_monthly = int(revenue / months_recorded) if months_recorded else 0
    min_monthly = int(min(complete_months.values())) if complete_months else 0
    avg_active_days = round(len(active_days) / months_recorded, 1) if months_recorded else 0.0

    # Margin, from stock that actually has a cost price recorded. `coverage`
    # says how much of the sales this margin is based on — a margin drawn from
    # 4% of sales is not a fact about the business.
    out_rows = (
        db.query(
            func.coalesce(func.sum(InventoryMovement.quantity * InventoryMovement.unit_price), 0),
            func.coalesce(func.sum(InventoryMovement.quantity * InventoryItem.cost_price), 0),
        )
        .join(InventoryItem, InventoryMovement.item_id == InventoryItem.id)
        .filter(
            InventoryMovement.owner_phone == owner_phone,
            InventoryMovement.movement_type == "OUT",
            InventoryMovement.created_at >= start,
            InventoryMovement.unit_price.isnot(None),
            InventoryItem.cost_price.isnot(None),
        )
        .first()
    )
    priced_revenue, priced_cost = int(out_rows[0] or 0), int(out_rows[1] or 0)
    gross_margin_pct = _pct(priced_revenue - priced_cost, priced_revenue)
    margin_coverage_pct = _pct(priced_revenue, revenue)

    # Customers: how many, how many came back, and what they still owe.
    buyers = {}
    for tx in txs:
        if tx.type in ("SALE", "BUY") and tx.customer_id:
            buyers[tx.customer_id] = buyers.get(tx.customer_id, 0) + 1
    repeat_pct = _pct(sum(1 for n in buyers.values() if n > 1), len(buyers))

    total_customers = db.query(func.count(Customer.id)).filter(
        Customer.owner_phone == owner_phone).scalar() or 0
    receivables = int(db.query(func.coalesce(func.sum(Customer.balance), 0)).filter(
        Customer.owner_phone == owner_phone, Customer.balance > 0).scalar() or 0)
    debtor_count = db.query(func.count(Customer.id)).filter(
        Customer.owner_phone == owner_phone, Customer.balance > 0).scalar() or 0

    # Credit behaviour of this business's own customers.
    collection_rate_pct = _pct(collected, credit_sales)
    days_in_window = max(1, (now - start).days)
    daily_credit = credit_sales / days_in_window if credit_sales else 0
    days_to_collect = int(receivables / daily_credit) if daily_credit else 0

    # What's contracted to come in within 30 days (credit sales with a due date).
    due_soon = int(
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.customer_id.in_(
                db.query(Customer.id).filter(Customer.owner_phone == owner_phone)
            ),
            Transaction.type == "BUY",
            Transaction.is_voided.isnot(True),
            Transaction.due_date.isnot(None),
            Transaction.due_date <= now + timedelta(days=30),
            Transaction.due_date >= now,
        ).scalar() or 0
    )

    # Does the business pay what IT owes? The closest thing to repayment
    # behaviour that exists before any financing has happened.
    sup = (
        db.query(
            func.coalesce(func.sum(SupplierPurchase.total), 0),
            func.coalesce(func.sum(SupplierPurchase.paid_amount), 0),
        ).filter(SupplierPurchase.owner_phone == owner_phone).first()
    )
    supplier_total, supplier_paid = int(sup[0] or 0), int(sup[1] or 0)
    overdue_payables = int(
        db.query(func.coalesce(func.sum(SupplierPurchase.total - SupplierPurchase.paid_amount), 0))
        .filter(
            SupplierPurchase.owner_phone == owner_phone,
            SupplierPurchase.due_date.isnot(None),
            SupplierPurchase.due_date < now,
            SupplierPurchase.total > SupplierPurchase.paid_amount,
        ).scalar() or 0
    )

    subscription_payments = db.query(func.count(SubscriptionPayment.id)).filter(
        SubscriptionPayment.phone == owner_phone,
        SubscriptionPayment.status == "APPROVED",
    ).scalar() or 0

    staff_count = 0
    if owner:
        staff_count = db.query(func.count(User.id)).filter(
            User.parent_id == owner.id).scalar() or 0
    stock_items = db.query(func.count(InventoryItem.id)).filter(
        InventoryItem.owner_phone == owner_phone).scalar() or 0

    months_on_platform = 0
    if owner and owner.created_at:
        months_on_platform = max(0, int((now - owner.created_at).days / 30))

    return {
        # Trading
        "window_months": window_months,
        "months_recorded": months_recorded,
        "months_on_platform": months_on_platform,
        "first_record_at": first_record.isoformat() if first_record else None,
        "total_sales": int(revenue),
        "avg_monthly_sales": avg_monthly,
        "min_monthly_sales": min_monthly,
        "monthly_sales": dict(sorted(by_month.items())),
        "avg_active_days_per_month": avg_active_days,
        # Profitability
        "gross_margin_pct": gross_margin_pct,
        "margin_coverage_pct": margin_coverage_pct,
        # Customers
        "total_customers": int(total_customers),
        "active_customers": len(buyers),
        "repeat_customer_pct": repeat_pct,
        # Credit given out and coming back
        "credit_sales": int(credit_sales),
        "collected": int(collected),
        "collection_rate_pct": collection_rate_pct,
        "receivables": receivables,
        "debtor_count": int(debtor_count),
        "avg_days_to_collect": days_to_collect,
        "expected_next_30_days": due_soon,
        # Obligations the business already carries
        "supplier_purchases_total": supplier_total,
        "supplier_paid_pct": _pct(supplier_paid, supplier_total),
        "overdue_payables": overdue_payables,
        "subscription_payments": int(subscription_payments),
        # Depth of the record
        "corroborated_revenue_pct": _pct(revenue_with_customer, revenue),
        "staff_count": int(staff_count),
        "stock_items": int(stock_items),
    }


# ── Scoring ──────────────────────────────────────────────────────────────────

def _component_score(value, spec):
    zero, full = float(spec.get("zero", 0)), float(spec.get("full", 100))
    value = float(value or 0)
    if full == zero:
        return 0.0
    pct = (value - zero) / (full - zero) * 100.0
    if not spec.get("higher_is_better", True):
        pct = 100.0 - pct
    return max(0.0, min(100.0, round(pct, 1)))


def _tier_for(score, cfg):
    tiers = sorted(cfg.get("tiers") or [], key=lambda t: t.get("min_score", 0))
    name = cfg.get("unrated_label", "Unrated")
    for tier in tiers:
        if score >= float(tier.get("min_score", 0)):
            name = tier.get("name") or name
    return name


def _confidence(metrics, cfg):
    """How much of this picture is evidenced. Reported alongside the score so a
    partner is never handed a flattering number drawn from two weeks of data."""
    c = cfg.get("confidence") or {}
    parts = [
        _component_score(metrics["months_recorded"], {"zero": 0, "full": c.get("months_full", 6)}),
        _component_score(metrics["avg_active_days_per_month"], {"zero": 0, "full": c.get("active_days_full", 15)}),
        _component_score(metrics["corroborated_revenue_pct"], {"zero": 0, "full": c.get("corroboration_full", 60)}),
    ]
    return round(sum(parts) / len(parts), 1)


def score_business(db, owner_phone, config=None, version=None):
    """Metrics, per-component scores, weighted total, tier and confidence."""
    if config is None:
        version, config = active_config(db)
    metrics = compute_metrics(db, owner_phone, int(config.get("window_months", 6)))

    components, weighted, total_weight = [], 0.0, 0.0
    for key, spec in (config.get("components") or {}).items():
        value = metrics.get(spec.get("metric"))
        sub = _component_score(value, spec)
        weight = float(spec.get("weight", 0) or 0)
        components.append({
            "key": key, "label": spec.get("label", key), "metric": spec.get("metric"),
            "value": value, "score": sub, "weight": weight,
        })
        weighted += sub * weight
        total_weight += weight

    score = round(weighted / total_weight, 1) if total_weight else 0.0
    enough = metrics["months_recorded"] >= int(config.get("min_months_recorded", 1))
    return {
        "config_version": version,
        "scored": enough,
        "score": score if enough else None,
        "tier": _tier_for(score, config) if enough else config.get("unrated_label", "Unrated"),
        "confidence": _confidence(metrics, config),
        "components": sorted(components, key=lambda c: -c["weight"]),
        "metrics": metrics,
        "not_scored_reason": None if enough else (
            f"Only {metrics['months_recorded']} month(s) of records — "
            f"{config.get('min_months_recorded', 1)} required."
        ),
    }


# ── Partner eligibility ──────────────────────────────────────────────────────
# Checked against the partner's own admin-entered minimums. This is a filter for
# what CreditVoice shows a business, NOT an approval: the partner still decides.

_ELIGIBILITY_RULES = {
    "min_months_recorded":    ("months_recorded",        "months of records"),
    "min_months_on_platform": ("months_on_platform",     "months on CreditVoice"),
    "min_avg_monthly_sales":  ("avg_monthly_sales",      "average monthly sales"),
    "min_monthly_sales_floor": ("min_monthly_sales",     "lowest monthly sales"),
    "min_repeat_customer_pct": ("repeat_customer_pct",   "% customers who return"),
    "min_collection_rate_pct": ("collection_rate_pct",   "% of credit collected"),
    "min_supplier_paid_pct":  ("supplier_paid_pct",      "% of suppliers paid"),
    "min_score":              (None,                    "scorecard score"),
    "min_confidence":         (None,                    "evidence confidence"),
}


def check_eligibility(scorecard, eligibility):
    """[(passed, requirement, required, actual)] for a partner's minimums."""
    checks = []
    metrics = scorecard.get("metrics") or {}
    for key, required in (eligibility or {}).items():
        rule = _ELIGIBILITY_RULES.get(key)
        if rule is None or required in (None, ""):
            continue
        metric_key, label = rule
        if key == "min_score":
            actual = scorecard.get("score") or 0
        elif key == "min_confidence":
            actual = scorecard.get("confidence") or 0
        else:
            actual = metrics.get(metric_key) or 0
        checks.append({
            "requirement": label,
            "required": required,
            "actual": actual,
            "passed": float(actual) >= float(required),
        })
    return checks


def eligible(checks):
    return all(c["passed"] for c in checks) if checks else True
