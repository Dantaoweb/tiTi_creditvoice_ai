"""
Marketers — people CreditVoice recruits to sell the app. Not referrers.

  Admin adds a marketer (name, phone, their bonus % or the default). They get
  a code (MKADE12) and a sign-up link. A business that signs up with it — on
  the web (?ref=MKADE12) or on WhatsApp ("join MKADE12") — is theirs, gets the
  same free GO trial a referral gives, and earns NO referral cashback.

  Every plan payment that business makes — the first and every renewal —
  earns the marketer their % of it (approve_subscription_payment calls
  record_earning; once per payment). Admin pays bonuses outside the app and
  marks them paid.

  A marketer logs in with an ordinary CreditVoice account on the same phone
  and sees their code, link, businesses and bonus.
"""
import re
from datetime import datetime

from models import Marketer, MarketerEarning, MarketerSettings, SubscriptionPayment, User, utcnow

SITE = "https://www.creditvoiceai.com"
DEFAULT_PERCENT = 10.0


class MarketerError(ValueError):
    pass


def _norm_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 11:
        digits = "234" + digits[1:]
    return digits


def default_percent(db):
    s = db.query(MarketerSettings).order_by(MarketerSettings.id.desc()).first()
    return float(s.default_percent) if s and s.default_percent is not None else DEFAULT_PERCENT


def set_default_percent(db, percent, by):
    pct = _clean_percent(percent)
    db.add(MarketerSettings(default_percent=pct, updated_by=by, updated_at=utcnow()))
    db.commit()
    return pct


def percent_for(db, m):
    return float(m.percent) if m.percent is not None else default_percent(db)


def _clean_percent(v):
    try:
        p = round(float(v), 2)
    except (TypeError, ValueError):
        raise MarketerError("Enter the bonus as a percentage, e.g. 10.")
    if not 0 < p <= 50:
        raise MarketerError("The bonus must be between 0 and 50%.")
    return p


def _code_taken(db, code, but=None):
    q = db.query(Marketer.id).filter(Marketer.code == code)
    if but:
        q = q.filter(Marketer.id != but)
    return bool(q.first()) or bool(db.query(User.id).filter(User.referral_code == code).first())


def _make_code(db, name):
    base = "MK" + (re.sub(r"[^A-Z]", "", (name or "").upper())[:4] or "CV")
    for n in range(10, 1000):
        code = f"{base}{n}"
        if not _code_taken(db, code):
            return code
    raise MarketerError("Couldn't make a code — type one.")


def add_marketer(db, name, phone, percent=None, code=None, note=None, by=None):
    name = " ".join((name or "").split())[:100]
    phone = _norm_phone(phone)
    if len(name) < 2:
        raise MarketerError("Enter the marketer's name.")
    if len(phone) < 10:
        raise MarketerError("Enter the marketer's phone number.")
    if db.query(Marketer.id).filter(Marketer.phone == phone).first():
        raise MarketerError("A marketer with that phone already exists.")
    if code:
        code = re.sub(r"[^A-Z0-9]", "", code.upper())[:16]
        if len(code) < 4:
            raise MarketerError("A code needs at least 4 letters or numbers.")
        if _code_taken(db, code):
            raise MarketerError(f"The code {code} is already used.")
    m = Marketer(name=name, phone=phone, code=code or _make_code(db, name),
                 percent=_clean_percent(percent) if percent not in (None, "") else None,
                 status="active", note=(note or "").strip()[:200] or None, created_at=utcnow(), created_by=by)
    db.add(m)
    db.commit()
    return m


def update_marketer(db, m, name=None, percent="keep", status=None, note=None):
    if name is not None:
        n = " ".join(name.split())[:100]
        if len(n) < 2:
            raise MarketerError("Enter the marketer's name.")
        m.name = n
    if percent != "keep":
        m.percent = _clean_percent(percent) if percent not in (None, "") else None
    if status is not None:
        if status not in ("active", "inactive"):
            raise MarketerError("Status is active or inactive.")
        m.status = status
    if note is not None:
        m.note = note.strip()[:200] or None
    db.commit()
    return m


def link_for(m):
    return f"{SITE}/app/login?mode=register&ref={m.code}"


# ── Sign-up ─────────────────────────────────────────────────────────────────

def find_by_code(db, code):
    """An ACTIVE marketer's code. (An inactive marketer's code no longer works.)"""
    if not code:
        return None
    return db.query(Marketer).filter(Marketer.code == code.strip().upper(), Marketer.status == "active").first()


def for_user(db, user):
    """The marketer this login belongs to, if it's an active marketer's phone."""
    if not user:
        return None
    return db.query(Marketer).filter(Marketer.phone == _norm_phone(user.phone), Marketer.status == "active").first()


# ── Bonus on every payment ──────────────────────────────────────────────────

def record_earning(db, owner, payment):
    """A plan payment was approved: the marketer who brought the business earns
    their %. Once per payment; the caller commits."""
    if not owner or not getattr(owner, "marketer_id", None) or not payment or not payment.amount:
        return None
    if db.query(MarketerEarning.id).filter(MarketerEarning.payment_id == payment.id).first():
        return None
    m = db.query(Marketer).filter(Marketer.id == owner.marketer_id).first()
    if not m:
        return None
    pct = percent_for(db, m)
    earlier = db.query(MarketerEarning.id).filter(MarketerEarning.business_id == owner.id).first()
    e = MarketerEarning(marketer_id=m.id, business_id=owner.id, payment_id=payment.id, plan=payment.plan,
                        billing_period=payment.billing_period, amount=int(payment.amount), percent=pct,
                        bonus=round(int(payment.amount) * pct / 100), renewal=bool(earlier),
                        status="owed", created_at=utcnow())
    db.add(e)
    db.flush()
    return e


def mark_paid(db, m, earning_ids=None, reference=None, by=None):
    """Admin paid the marketer (outside the app): these bonuses, or all owed."""
    q = db.query(MarketerEarning).filter(MarketerEarning.marketer_id == m.id, MarketerEarning.status == "owed")
    if earning_ids:
        q = q.filter(MarketerEarning.id.in_([int(i) for i in earning_ids]))
    rows = q.all()
    if not rows:
        raise MarketerError("Nothing owed to mark as paid.")
    now = utcnow()
    for e in rows:
        e.status, e.paid_at, e.paid_by = "paid", now, by
        e.pay_reference = (reference or "").strip()[:80] or None
    db.commit()
    return sum(e.bonus or 0 for e in rows), len(rows)


# ── What admin and the marketer see ─────────────────────────────────────────

def _business_rows(db, m):
    from subscriptions import app_user_effective_plan
    from plans import is_paid_plan
    from business_templates import business_display_name
    out = []
    for u in db.query(User).filter(User.marketer_id == m.id, User.parent_id.is_(None)).order_by(User.created_at.desc()).all():
        plan = app_user_effective_plan(u)
        earned = db.query(MarketerEarning).filter(MarketerEarning.marketer_id == m.id,
                                                  MarketerEarning.business_id == u.id).all()
        out.append({
            "id": u.id, "name": business_display_name(u), "owner": u.name, "phone": u.phone,
            "business_type": u.business_type_label or u.business_type,
            "joined": u.created_at.isoformat() if u.created_at else None,
            "plan": plan, "paying": is_paid_plan(plan) and bool(earned),
            "payments": len(earned), "paid_total": sum(e.amount or 0 for e in earned),
            "bonus": sum(e.bonus or 0 for e in earned),
        })
    return out


def earning_row(db, e, names=None):
    names = names if names is not None else {}
    if e.business_id not in names:
        from business_templates import business_display_name
        u = db.query(User).filter(User.id == e.business_id).first()
        names[e.business_id] = business_display_name(u) if u else "?"
    return {"id": e.id, "business": names[e.business_id], "plan": e.plan, "billing_period": e.billing_period,
            "amount": e.amount, "percent": e.percent, "bonus": e.bonus, "renewal": bool(e.renewal),
            "status": e.status, "created_at": e.created_at.isoformat() if e.created_at else None,
            "paid_at": e.paid_at.isoformat() if e.paid_at else None, "pay_reference": e.pay_reference}


def summary(db, m, with_detail=False):
    earned = db.query(MarketerEarning).filter(MarketerEarning.marketer_id == m.id).all()
    month = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    biz = _business_rows(db, m)
    out = {
        "id": m.id, "name": m.name, "phone": m.phone, "code": m.code, "link": link_for(m),
        "percent": percent_for(db, m), "own_percent": m.percent, "status": m.status, "note": m.note,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "businesses": len(biz),
        "paying": sum(1 for b in biz if b["paying"]),
        "joined_this_month": sum(1 for b in biz if b["joined"] and datetime.fromisoformat(b["joined"]) >= month),
        "payments_total": sum(e.amount or 0 for e in earned),
        "bonus_total": sum(e.bonus or 0 for e in earned),
        "bonus_paid": sum(e.bonus or 0 for e in earned if e.status == "paid"),
        "bonus_owed": sum(e.bonus or 0 for e in earned if e.status == "owed"),
        "bonus_this_month": sum(e.bonus or 0 for e in earned if e.created_at and e.created_at >= month),
    }
    if with_detail:
        names = {}
        out["business_list"] = biz
        out["earnings"] = [earning_row(db, e, names) for e in
                           sorted(earned, key=lambda e: e.created_at or utcnow(), reverse=True)[:500]]
    return out


def admin_overview(db):
    ms = db.query(Marketer).order_by(Marketer.created_at.desc()).all()
    rows = [summary(db, m) for m in ms]
    return {
        "default_percent": default_percent(db),
        "marketers": sorted(rows, key=lambda r: (-r["bonus_this_month"], -r["businesses"])),
        "totals": {
            "marketers": len(rows), "active": sum(1 for r in rows if r["status"] == "active"),
            "businesses": sum(r["businesses"] for r in rows), "paying": sum(r["paying"] for r in rows),
            "bonus_total": sum(r["bonus_total"] for r in rows), "bonus_owed": sum(r["bonus_owed"] for r in rows),
            "bonus_paid": sum(r["bonus_paid"] for r in rows),
        },
    }
