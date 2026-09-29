"""
Explaining the scorecard, and saying what to do about it.

A score is useless to a trader who can't see what moved it. This turns the
components into plain language — what each one means, where they stand, and the
one concrete thing that would raise it most — and answers the same questions
when they ask tiTi in chat or on WhatsApp.

Nothing here decides anything; it reads the scorecard and says what it sees.
"""
from business_scorecard import score_business

# What each measurement actually means, in the words a trader would use. The
# labels themselves stay as they are — this is the explanation behind them.
GLOSSARY = {
    "avg_monthly_sales":        "What you sell in an average month, from what you record.",
    "min_monthly_sales":        "Your worst month. Lenders size a weekly repayment on this, not the average.",
    "avg_active_days_per_month": "How many days a month you actually record something.",
    "months_recorded":          "How many months of records you have — the longer, the more it is trusted.",
    "gross_margin_pct":         "Profit left on what you sell, after what it cost you to buy.",
    "margin_coverage_pct":      "How much of your sales this profit figure is based on. Low means few cost prices recorded.",
    "repeat_customer_pct":      "Share of your customers who came back and bought again.",
    "collection_rate_pct":      "Of the goods you gave on credit, how much has been paid back to you.",
    "supplier_paid_pct":        "Of what you owe your suppliers, how much you have paid.",
    "repayment_on_time_pct":    "Of the financing installments you have settled, how many were paid by the due date.",
    "corroborated_revenue_pct": "Sales recorded against a named customer rather than typed in anonymously.",
    "receivables":              "Money your customers still owe you.",
    "expected_next_30_days":    "Customer debts with a due date inside the next 30 days.",
}

# The one thing to do about each component, filled in with the business's own
# numbers so it reads as an instruction rather than a suggestion.
def _action(key, metrics, spec, value):
    target = spec.get("full")
    if key == "sales_volume":
        return ("Record every sale, including small cash ones — anything unrecorded is "
                "invisible to a financier.")
    if key == "sales_floor":
        return (f"Your weakest month was {_naira(metrics.get('min_monthly_sales'))}. "
                "Steadier months, even small ones, count for more than one big month.")
    if key == "consistency":
        days = metrics.get("avg_active_days_per_month") or 0
        need = max(0, round(float(target or 0) - float(days)))
        if need:
            return f"You record on about {days} days a month. Record on {need} more days a month."
        return "Keep recording most days — this is already strong."
    if key == "tenure":
        return ("Keep recording month after month. This one only improves with time, "
                "and it is the hardest thing to fake.")
    if key == "margin":
        coverage = metrics.get("margin_coverage_pct") or 0
        if coverage < 50:
            return (f"Only {coverage}% of your sales have a cost price behind them. "
                    "Add cost prices to your products so your profit can be measured.")
        return "Review prices on your slowest-moving products — your margin is what lenders read as room to repay."
    if key == "repeat_customers":
        return ("Record sales against a customer's name, not as anonymous cash, so "
                "returning customers can be seen.")
    if key == "collections":
        owed = metrics.get("receivables") or 0
        return (f"Your customers owe you {_naira(owed)}. Collecting it raises this and "
                "puts cash in your hand.")
    if key == "supplier_discipline":
        overdue = metrics.get("overdue_payables") or 0
        if overdue:
            return f"You have {_naira(overdue)} overdue to suppliers. Clearing it is the fastest lift here."
        return "Record your supplier purchases and payments — paying on time is strong evidence."
    if key == "repayment_record":
        return "Pay each installment on or before its due date. This carries the most weight of all."
    return "Keep recording."


def _naira(amount):
    return f"N{int(amount or 0):,}"


def explain(card):
    """Each counted component: what it means, where they stand, what to do."""
    out = []
    for c in card.get("components", []):
        out.append({
            "key": c["key"],
            "label": c["label"],
            "meaning": GLOSSARY.get(c["metric"], ""),
            "value": c["value"],
            "score": c["score"],
            "weight": c["weight"],
        })
    return out


def improvement_plan(db, owner_phone, card=None, config=None, partner=None, limit=3):
    """The actions worth taking, biggest gain first.

    Gain is the weight of the component times how much of it is unearned — so a
    heavily-weighted component scoring badly comes first, which is what actually
    moves the number.
    """
    if card is None:
        card = score_business(db, owner_phone, config=config, partner=partner)
    metrics = card.get("metrics", {})
    specs = {}
    if config:
        specs = config.get("components", {})

    actions = []
    for c in card.get("components", []):
        headroom = 100.0 - float(c["score"] or 0)
        if headroom <= 5:
            continue          # already near the top of this band
        gain = round(headroom * float(c["weight"] or 0) / 100.0, 1)
        actions.append({
            "key": c["key"],
            "label": c["label"],
            "score": c["score"],
            "possible_gain": gain,
            "action": _action(c["key"], metrics, specs.get(c["key"], {}), c["value"]),
        })
    actions.sort(key=lambda a: -a["possible_gain"])

    # Components that aren't counted at all are an opportunity, not a penalty —
    # starting to record that thing adds a whole component.
    for skipped in card.get("not_applicable", []):
        actions.append({
            "key": skipped["key"],
            "label": skipped["label"],
            "score": None,
            "possible_gain": 0.0,
            "action": _start_recording_hint(skipped["key"]),
        })
    return actions[:limit + len(card.get("not_applicable", []))]


def _start_recording_hint(key):
    return {
        "margin": "Add cost prices to your products and your profit margin starts counting.",
        "collections": "Record credit sales and the payments against them, and your collection record starts counting.",
        "repeat_customers": "Record sales against customer names and returning customers start counting.",
        "supplier_discipline": "Record what you buy from suppliers and what you pay them, and that starts counting.",
        "repayment_record": "Once you have financed an asset through CreditVoice, your repayment record counts — and it carries the most weight.",
    }.get(key, "Start recording this and it will begin to count.")


def partner_gaps(offer):
    """Why this business falls short of one partner, as instructions."""
    gaps = []
    for check in offer.get("checks", []):
        if check.get("passed"):
            continue
        requirement = check.get("requirement")
        required, actual = check.get("required"), check.get("actual")
        if requirement == "registered business (CAC)":
            gaps.append("They only finance CAC-registered businesses. Add your RC/BN number once registered.")
        elif requirement == "months of records":
            gaps.append(f"They want {required} months of records; you have {actual}. Keep recording.")
        elif requirement in ("average monthly sales", "lowest monthly sales"):
            gaps.append(f"They want {requirement} of {_naira(required)}; yours is {_naira(actual)}.")
        elif requirement == "scorecard score":
            gaps.append(f"They want a score of {required}; with their rules yours is {actual}.")
        else:
            gaps.append(f"They want {requirement} of {required}; yours is {actual}.")
    if offer.get("covered") is False:
        gaps.append(f"They don't operate in your state yet (they cover: {offer.get('coverage')}).")
    return gaps


# ── tiTi: answering in chat and on WhatsApp ──────────────────────────────────

def _tier_line(card):
    if not card.get("scored"):
        return f"You don't have a score yet. {card.get('not_scored_reason') or ''}".strip()
    return (f"Your business score is *{card['score']} out of 100* ({card['tier']}). "
            f"Records complete: {card['confidence']}%.")


def score_summary(db, owner_phone):
    """'What is my score' — the number, what it rests on, and the top actions."""
    card = score_business(db, owner_phone)
    lines = [_tier_line(card), ""]
    top = sorted(card.get("components", []), key=lambda c: -c["weight"])[:4]
    if top:
        lines.append("What it is built on:")
        for c in top:
            value = c["value"]
            shown = _naira(value) if isinstance(value, (int, float)) and value > 1000 else value
            lines.append(f"• {c['label']}: {shown} ({c['score']}/100)")
    skipped = card.get("not_applicable", [])
    if skipped:
        lines.append("")
        lines.append("Not counted (you have no records for these): "
                     + ", ".join(s["label"] for s in skipped) + ".")
    lines.append("")
    lines.append("Send *improve my score* to see what to do next.")
    return "\n".join(lines)


def improve_summary(db, owner_phone):
    """'How do I improve' — the two or three things that would move it most."""
    from business_scorecard import active_config
    _version, config = active_config(db)
    card = score_business(db, owner_phone, config=config)
    actions = improvement_plan(db, owner_phone, card=card, config=config, limit=3)
    if not actions:
        return "Your record is strong across the board — keep recording as you are."
    lines = ["To raise your business score:"]
    for i, a in enumerate(actions[:4], 1):
        gain = f" (up to +{a['possible_gain']} points)" if a["possible_gain"] else ""
        lines.append(f"{i}. *{a['label']}*{gain}\n   {a['action']}")
    return "\n".join(lines)


def explain_metric(term):
    """'What is credit collected' — plain meaning for a term they saw."""
    needle = (term or "").lower().strip()
    aliases = {
        "credit collected": "collection_rate_pct",
        "collections": "collection_rate_pct",
        "evidence": "corroborated_revenue_pct",
        "evidence strength": "corroborated_revenue_pct",
        "records complete": "corroborated_revenue_pct",
        "margin": "gross_margin_pct",
        "gross margin": "gross_margin_pct",
        "worst month": "min_monthly_sales",
        "recording consistency": "avg_active_days_per_month",
        "track record": "months_recorded",
        "customers who return": "repeat_customer_pct",
        "pays suppliers": "supplier_paid_pct",
        "repays financing on time": "repayment_on_time_pct",
        "credit given to customers": "receivables",
    }
    key = aliases.get(needle, needle.replace(" ", "_"))
    meaning = GLOSSARY.get(key)
    return f"*{term.strip().title()}* — {meaning}" if meaning else None


def financing_summary(db, owner_phone):
    """'Can I get financing' — what they qualify for and what is missing."""
    from business_kyc import coverage_label, get_kyc, kyc_checks, missing_fields, partner_covers
    from business_scorecard import check_eligibility, eligible
    from models import FinancePartner
    import json

    partners = db.query(FinancePartner).filter(
        FinancePartner.is_active == True  # noqa: E712
    ).order_by(FinancePartner.name).all()
    if not partners:
        return "No financing partners are listed yet. You'll see them here as they join."

    kyc = get_kyc(db, owner_phone)
    lines = []
    ready, blocked = [], []
    for p in partners:
        card = score_business(db, owner_phone, partner=p)
        try:
            rules = json.loads(p.eligibility_json or "{}")
        except (ValueError, TypeError):
            rules = {}
        checks = check_eligibility(card, rules) + kyc_checks(p, kyc, rules)
        offer = {
            "checks": checks,
            "covered": partner_covers(p, kyc.state if kyc else None),
            "coverage": coverage_label(p),
        }
        if eligible(checks) and offer["covered"]:
            ready.append(p.name)
        else:
            blocked.append((p.name, partner_gaps(offer)))

    if ready:
        lines.append("You meet the requirements for: " + ", ".join(f"*{n}*" for n in ready) + ".")
    for name, gaps in blocked[:3]:
        lines.append(f"\n*{name}* — not yet:")
        lines.extend(f"• {g}" for g in gaps[:3])

    gaps_kyc = missing_fields(kyc)
    if gaps_kyc:
        lines.append("\nBefore you can apply, add your details: "
                     + ", ".join(label for _k, label in gaps_kyc) + ".")
    lines.append("\nOpen Business Score in the app to apply.")
    return "\n".join(lines)
