"""
Partner, investor, and staff profile commands.

WhatsApp command surface
─────────────────────────────────────────────────────────────────────
Staff profile (owner sets for their staff):
  set staff profile Emeka position cashier level junior salary 50000 matric EMP001
  view staff profile Emeka
  view staff profiles           ← list all staff with profiles

Partner management (owner only):
  invite partner 08012345678 co_founder 30%    ← invite by phone, role, equity
  invite partner 08012345678 investor 500000   ← investor with capital amount
  remove partner 08012345678
  view partners                                ← list all partners/investors
  partner status                               ← own status in businesses you're partnered in

Partner acceptance (partner's own phone):
  ACCEPT PARTNER [owner_phone]
  DECLINE PARTNER [owner_phone]

Partner views (for the partner, after accepting):
  business overview     ← summary based on their access_level
  business sales        ← if access_level allows
  business stock        ← if access_level allows
  business notes        ← if visibility allows

Shared notes (owner creates, partners/investors read):
  note rent paid 45000            ← expense note, owner_only by default
  note rent paid 45000 partners   ← visible to partners
  note rent paid 45000 all        ← visible to all (partners + investors)
  view notes                      ← owner sees all; partners see their-level notes
  view notes expenses             ← filter by category
"""

from datetime import datetime, timezone

from models import BusinessNote, BusinessPartner, Transaction, User
from parser import normalize_phone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Role definitions ──────────────────────────────────────────────────────────

ROLE_ACCESS = {
    "co_founder":    "full",
    "partner":       "operations",
    "investor":      "financial",
    "silent":        "investment_only",
}

ROLE_LABELS = {
    "co_founder": "Co-Founder",
    "partner":    "Partner",
    "investor":   "Investor",
    "silent":     "Silent Investor",
}

ACCESS_LABELS = {
    "full":            "Full access (sales, stock, customers, costs)",
    "operations":      "Operations (sales, stock, customers)",
    "financial":       "Financial summary (P&L, returns)",
    "investment_only": "Investment status only",
}

NOTE_VISIBILITY_RANK = {
    "owner_only":   0,
    "partners":     1,
    "investors":    2,
    "all":          3,
}

PARTNER_VISIBILITY_RANK = {
    "co_founder": 3,
    "partner":    1,
    "investor":   2,
    "silent":     2,
}


# ── Staff profile ─────────────────────────────────────────────────────────────

def handle_set_staff_profile(db, phone, parsed, user, business_owner_phone, send_message):
    """Owner sets/updates a staff member's profile."""
    if user.phone != business_owner_phone:
        send_message(phone, "Only the business owner can set staff profiles.")
        return {"status": "staff_profile_permission_denied"}

    target_name = (parsed.get("staff_name") or "").strip().lower()
    if not target_name:
        send_message(phone, "Please include the staff name. Example:\nset staff profile Emeka position cashier salary 50000")
        return {"status": "staff_profile_missing_name"}

    from sqlalchemy import func
    staff = db.query(User).filter(
        User.parent_id == user.id,
        func.lower(User.name) == target_name,
    ).first()
    if not staff:
        send_message(phone, f"No staff named *{target_name.title()}* found.")
        return {"status": "staff_profile_not_found"}

    changed = []
    if parsed.get("position"):
        staff.staff_position = parsed["position"].title()
        changed.append(f"Position: {staff.staff_position}")
    if parsed.get("level"):
        staff.staff_level = parsed["level"].title()
        changed.append(f"Level: {staff.staff_level}")
    if parsed.get("salary") is not None:
        staff.staff_salary = int(parsed["salary"])
        changed.append(f"Salary: N{staff.staff_salary:,}")
    if parsed.get("matric"):
        staff.staff_matric = parsed["matric"].upper()
        changed.append(f"Matric: {staff.staff_matric}")

    if not changed:
        send_message(phone, "Nothing to update. Include at least one of: position, level, salary, matric.")
        return {"status": "staff_profile_nothing_changed"}

    db.commit()
    lines = "\n".join(changed)
    send_message(phone, f"Profile updated for *{staff.name.title()}*:\n{lines}")
    return {"status": "staff_profile_updated"}


def handle_view_staff_profile(db, phone, parsed, user, business_owner_phone, send_message):
    """View one or all staff profiles."""
    if user.phone != business_owner_phone:
        send_message(phone, "Only the business owner can view staff profiles.")
        return {"status": "staff_profile_permission_denied"}

    target_name = (parsed.get("staff_name") or "").strip().lower()

    if target_name:
        from sqlalchemy import func
        staff = db.query(User).filter(
            User.parent_id == user.id,
            func.lower(User.name) == target_name,
        ).first()
        if not staff:
            send_message(phone, f"No staff named *{target_name.title()}* found.")
            return {"status": "staff_profile_not_found"}
        send_message(phone, _format_single_staff_profile(staff))
        return {"status": "staff_profile_viewed"}

    # List all staff
    all_staff = db.query(User).filter(User.parent_id == user.id).all()
    if not all_staff:
        send_message(phone, "You have no staff registered.")
        return {"status": "staff_profile_empty"}

    lines = [f"*Staff Profiles ({len(all_staff)})*\n"]
    for s in all_staff:
        pos = s.staff_position or "—"
        lvl = s.staff_level or "—"
        sal = f"N{s.staff_salary:,}" if s.staff_salary else "—"
        mat = s.staff_matric or "—"
        lines.append(f"*{s.name.title()}*\n  Position: {pos} | Level: {lvl}\n  Salary: {sal} | ID: {mat}")
    send_message(phone, "\n\n".join(lines))
    return {"status": "staff_profiles_listed"}


def _format_single_staff_profile(staff):
    lines = [f"*Staff Profile — {staff.name.title()}*\n"]
    lines.append(f"Phone: {staff.phone}")
    lines.append(f"Position: {staff.staff_position or 'Not set'}")
    lines.append(f"Level: {staff.staff_level or 'Not set'}")
    lines.append(f"Salary: {'N' + f'{staff.staff_salary:,}' if staff.staff_salary else 'Not set'}")
    lines.append(f"Employee ID: {staff.staff_matric or 'Not set'}")
    return "\n".join(lines)


# ── Partner invite ────────────────────────────────────────────────────────────

def handle_invite_partner(db, phone, parsed, user, business_owner_phone, send_message):
    """Owner invites a partner or investor by phone number."""
    if user.phone != business_owner_phone:
        send_message(phone, "Only the business owner can invite partners.")
        return {"status": "partner_invite_permission_denied"}

    raw_phone = parsed.get("partner_phone", "")
    partner_phone = normalize_phone(raw_phone)
    if not partner_phone:
        send_message(phone, "Invalid phone number. Example:\ninvite partner 08012345678 co_founder 30%")
        return {"status": "partner_invite_bad_phone"}

    if partner_phone == business_owner_phone:
        send_message(phone, "You cannot invite yourself as a partner.")
        return {"status": "partner_invite_self"}

    role_raw = (parsed.get("role") or "partner").lower().replace(" ", "_").replace("-", "_")
    role = role_raw if role_raw in ROLE_ACCESS else "partner"
    access_level = ROLE_ACCESS[role]

    equity = parsed.get("equity_percent")
    investment = parsed.get("investment_amount")

    # Check for existing invite
    existing = db.query(BusinessPartner).filter(
        BusinessPartner.owner_phone == business_owner_phone,
        BusinessPartner.partner_phone == partner_phone,
    ).first()
    if existing and existing.status == "active":
        send_message(phone, f"This person is already an active {ROLE_LABELS.get(existing.role, 'partner')} in your business.")
        return {"status": "partner_already_active"}
    if existing and existing.status == "pending":
        send_message(phone, "An invitation is already pending for this person.")
        return {"status": "partner_invite_pending"}

    bp = BusinessPartner(
        owner_phone=business_owner_phone,
        partner_phone=partner_phone,
        role=role,
        access_level=access_level,
        equity_percent=float(equity) if equity is not None else None,
        investment_amount=int(investment) if investment is not None else None,
        status="pending",
        invited_at=_utcnow(),
    )
    db.add(bp)
    db.commit()

    # Build confirmation for owner
    equity_line = f"\nEquity: {equity}%" if equity is not None else ""
    invest_line = f"\nCapital: N{int(investment):,}" if investment is not None else ""
    send_message(
        phone,
        f"Invitation sent to *{partner_phone}*.\n\n"
        f"Role: {ROLE_LABELS[role]}\n"
        f"Access: {ACCESS_LABELS[access_level]}"
        f"{equity_line}{invest_line}\n\n"
        "They will receive an invitation on WhatsApp to accept or decline."
    )

    # Notify the invitee
    owner_name = user.name.title() if user else "A business owner"
    business_label = user.business_type_label or user.business_type or "their business"
    equity_note = f" with {equity}% equity" if equity is not None else ""
    invest_note = f" (capital: N{int(investment):,})" if investment is not None else ""
    send_message(
        partner_phone,
        f"*Partnership Invitation*\n\n"
        f"*{owner_name}* has invited you to join *{business_label}* as a "
        f"*{ROLE_LABELS[role]}*{equity_note}{invest_note}.\n\n"
        f"Access level: {ACCESS_LABELS[access_level]}\n\n"
        f"Reply:\n"
        f"*ACCEPT PARTNER {business_owner_phone}* to join\n"
        f"*DECLINE PARTNER {business_owner_phone}* to decline"
    )
    return {"status": "partner_invited"}


def handle_accept_partner(db, phone, parsed, send_message):
    """Partner accepts or declines an invitation."""
    owner_phone = normalize_phone(parsed.get("owner_phone") or "")
    action = parsed.get("action", "accept").lower()

    bp = db.query(BusinessPartner).filter(
        BusinessPartner.owner_phone == owner_phone,
        BusinessPartner.partner_phone == phone,
        BusinessPartner.status == "pending",
    ).first()
    if not bp:
        send_message(phone, "No pending invitation found from that business.")
        return {"status": "partner_accept_not_found"}

    owner = db.query(User).filter(User.phone == owner_phone).first()
    business_label = (owner.business_type_label or owner.business_type or "the business") if owner else "the business"
    owner_name = owner.name.title() if owner else owner_phone

    if action == "decline":
        db.delete(bp)
        db.commit()
        send_message(phone, f"You have declined the partnership invitation from *{owner_name}*.")
        send_message(owner_phone, f"*{(db.query(User).filter(User.phone == phone).first() or type('x', (), {'name': phone})()).name.title()}* has declined your partnership invitation.")
        return {"status": "partner_declined"}

    bp.status = "active"
    bp.accepted_at = _utcnow()
    db.commit()

    send_message(
        phone,
        f"Welcome! You are now a *{ROLE_LABELS.get(bp.role, 'Partner')}* in *{business_label}*.\n\n"
        f"Access: {ACCESS_LABELS.get(bp.access_level, bp.access_level)}\n\n"
        "Send *business overview* to see a summary anytime."
    )
    partner_user = db.query(User).filter(User.phone == phone).first()
    partner_name = partner_user.name.title() if partner_user else phone
    send_message(
        owner_phone,
        f"*{partner_name}* has accepted your invitation as *{ROLE_LABELS.get(bp.role, 'Partner')}* in {business_label}."
    )
    return {"status": "partner_accepted"}


def handle_remove_partner(db, phone, parsed, user, business_owner_phone, send_message):
    """Owner removes a partner."""
    if user.phone != business_owner_phone:
        send_message(phone, "Only the business owner can remove partners.")
        return {"status": "partner_remove_permission_denied"}

    raw_phone = parsed.get("partner_phone", "")
    partner_phone = normalize_phone(raw_phone)
    bp = db.query(BusinessPartner).filter(
        BusinessPartner.owner_phone == business_owner_phone,
        BusinessPartner.partner_phone == partner_phone,
    ).first()
    if not bp:
        send_message(phone, "No partner found with that phone number.")
        return {"status": "partner_remove_not_found"}

    role_label = ROLE_LABELS.get(bp.role, "partner")
    db.delete(bp)
    db.commit()
    send_message(phone, f"{role_label} *{partner_phone}* has been removed from your business.")
    send_message(partner_phone, f"You have been removed as a {role_label} from *{user.name.title()}*'s business.")
    return {"status": "partner_removed"}


def handle_view_partners(db, phone, user, business_owner_phone, send_message):
    """Owner views all partners and investors."""
    if user.phone != business_owner_phone:
        send_message(phone, "Only the business owner can view partners.")
        return {"status": "partner_view_permission_denied"}

    partners = db.query(BusinessPartner).filter(
        BusinessPartner.owner_phone == business_owner_phone,
    ).all()
    if not partners:
        send_message(phone, "You have no partners or investors yet.\n\nTo invite one:\ninvite partner 08012345678 co_founder 30%")
        return {"status": "partner_list_empty"}

    lines = [f"*Partners & Investors ({len(partners)})*\n"]
    for p in partners:
        pu = db.query(User).filter(User.phone == p.partner_phone).first()
        name = pu.name.title() if pu else p.partner_phone
        status_icon = "✅" if p.status == "active" else "⏳"
        equity = f" | {p.equity_percent}%" if p.equity_percent else ""
        invest = f" | N{p.investment_amount:,}" if p.investment_amount else ""
        lines.append(f"{status_icon} *{name}* — {ROLE_LABELS.get(p.role, p.role)}{equity}{invest}\n  Access: {ACCESS_LABELS.get(p.access_level, p.access_level)}")
    send_message(phone, "\n\n".join(lines))
    return {"status": "partner_list_viewed"}


def handle_partner_status(db, phone, send_message):
    """Partner checks which businesses they are linked to."""
    partnerships = db.query(BusinessPartner).filter(
        BusinessPartner.partner_phone == phone,
        BusinessPartner.status == "active",
    ).all()
    if not partnerships:
        send_message(phone, "You are not a partner or investor in any business on tiTi.")
        return {"status": "partner_status_none"}

    lines = [f"*Your Partnerships ({len(partnerships)})*\n"]
    for p in partnerships:
        owner = db.query(User).filter(User.phone == p.owner_phone).first()
        biz = (owner.business_type_label or owner.business_type or "Unnamed Business") if owner else p.owner_phone
        owner_name = owner.name.title() if owner else p.owner_phone
        equity = f" | {p.equity_percent}% equity" if p.equity_percent else ""
        invest = f" | Capital N{p.investment_amount:,}" if p.investment_amount else ""
        lines.append(
            f"*{biz}* ({owner_name})\n"
            f"  Role: {ROLE_LABELS.get(p.role, p.role)}{equity}{invest}\n"
            f"  Access: {ACCESS_LABELS.get(p.access_level, p.access_level)}"
        )
    lines.append("\nSend *business overview* to view a linked business.")
    send_message(phone, "\n\n".join(lines))
    return {"status": "partner_status_viewed"}


# ── Partner business views ────────────────────────────────────────────────────

def _get_active_partnership(db, phone, owner_phone):
    """Return the BusinessPartner record if phone is an active partner of owner_phone."""
    return db.query(BusinessPartner).filter(
        BusinessPartner.owner_phone == owner_phone,
        BusinessPartner.partner_phone == phone,
        BusinessPartner.status == "active",
    ).first()


def handle_partner_business_overview(db, phone, parsed, send_message):
    """Partner requests a business overview. owner_phone may be specified or inferred."""
    owner_phone = parsed.get("owner_phone")

    if owner_phone:
        partnerships = [_get_active_partnership(db, phone, normalize_phone(owner_phone))]
        partnerships = [p for p in partnerships if p]
    else:
        partnerships = db.query(BusinessPartner).filter(
            BusinessPartner.partner_phone == phone,
            BusinessPartner.status == "active",
        ).all()

    if not partnerships:
        send_message(phone, "You are not linked to any active business. Check your invitations with *partner status*.")
        return {"status": "partner_overview_not_linked"}

    if len(partnerships) > 1:
        lines = ["You are linked to multiple businesses. Which one?\n"]
        for i, p in enumerate(partnerships, 1):
            owner = db.query(User).filter(User.phone == p.owner_phone).first()
            biz = (owner.business_type_label or owner.business_type or p.owner_phone) if owner else p.owner_phone
            lines.append(f"{i}. {biz}")
        lines.append("\nReply *business overview [owner_phone]* to select one.")
        send_message(phone, "\n".join(lines))
        return {"status": "partner_overview_select"}

    bp = partnerships[0]
    _send_partner_overview(db, phone, bp, send_message)
    return {"status": "partner_overview_sent"}


def _send_partner_overview(db, phone, bp, send_message):
    from reports import get_owner_transaction_query
    from sqlalchemy import func

    owner = db.query(User).filter(User.phone == bp.owner_phone).first()
    biz = (owner.business_type_label or owner.business_type or "Business") if owner else "Business"
    owner_name = owner.name.title() if owner else bp.owner_phone
    role_label = ROLE_LABELS.get(bp.role, bp.role)
    access = bp.access_level

    lines = [f"*{biz}* — {role_label} View\n"]

    if access in ("full", "operations", "financial"):
        # Sales summary (last 30 days)
        from datetime import timedelta
        since = _utcnow() - timedelta(days=30)
        txs = get_owner_transaction_query(db, bp.owner_phone).filter(
            Transaction.created_at >= since,
            Transaction.is_voided != True,
        ).all()
        sales = [t for t in txs if t.type in ("BUY", "SALE")]
        payments = [t for t in txs if t.type == "PAY"]
        total_sales = sum(t.amount for t in sales)
        total_payments = sum(t.amount for t in payments)
        lines.append(f"Sales (last 30 days): N{total_sales:,}")
        lines.append(f"Payments received: N{total_payments:,}")

    if access in ("full", "financial", "investment_only"):
        # Investment summary
        if bp.investment_amount:
            lines.append(f"\nYour capital: N{bp.investment_amount:,}")
        if bp.equity_percent:
            lines.append(f"Your equity: {bp.equity_percent}%")

    if access == "full":
        # Customer count
        from models import Customer
        cust_count = db.query(func.count(Customer.id)).filter(
            Customer.owner_phone == bp.owner_phone
        ).scalar() or 0
        lines.append(f"\nCustomers: {cust_count:,}")

    lines.append(f"\nOwner: {owner_name}")
    lines.append(f"Access level: {ACCESS_LABELS.get(access, access)}")
    send_message(phone, "\n".join(lines))


# ── Shared notes ─────────────────────────────────────────────────────────────

def handle_add_note(db, phone, parsed, user, business_owner_phone, send_message):
    """Owner creates a business note/expense entry."""
    if user.phone != business_owner_phone:
        send_message(phone, "Only the business owner can add business notes.")
        return {"status": "note_permission_denied"}

    body = (parsed.get("body") or "").strip()
    if not body:
        send_message(phone, "Please include note content. Example:\nnote rent paid 45000 partners")
        return {"status": "note_missing_body"}

    category = (parsed.get("category") or "memo").lower()
    amount = parsed.get("amount")
    visibility = (parsed.get("visibility") or "owner_only").lower()
    if visibility not in NOTE_VISIBILITY_RANK:
        visibility = "owner_only"

    note = BusinessNote(
        owner_phone=business_owner_phone,
        body=body,
        category=category,
        amount=int(amount) if amount else None,
        visibility=visibility,
        created_by_id=user.id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(note)
    db.commit()

    vis_label = {"owner_only": "only you", "partners": "partners", "investors": "investors", "all": "partners & investors"}.get(visibility, visibility)
    amount_line = f"\nAmount: N{int(amount):,}" if amount else ""
    send_message(
        phone,
        f"Note saved.\n\n"
        f"*{body.capitalize()}*{amount_line}\n"
        f"Category: {category.title()}\n"
        f"Visible to: {vis_label}"
    )
    return {"status": "note_saved"}


def handle_view_notes(db, phone, parsed, user, business_owner_phone, send_message):
    """View business notes. Owner sees all; partners/investors see what their access allows."""
    is_owner = user and user.phone == business_owner_phone

    if is_owner:
        query = db.query(BusinessNote).filter(BusinessNote.owner_phone == business_owner_phone)
    else:
        # Determine visibility rank for this partner
        bp = db.query(BusinessPartner).filter(
            BusinessPartner.owner_phone == business_owner_phone,
            BusinessPartner.partner_phone == phone,
            BusinessPartner.status == "active",
        ).first()
        if not bp:
            send_message(phone, "You do not have access to notes for this business.")
            return {"status": "note_access_denied"}
        partner_rank = PARTNER_VISIBILITY_RANK.get(bp.role, 0)
        allowed_visibility = [v for v, rank in NOTE_VISIBILITY_RANK.items() if rank <= partner_rank and v != "owner_only"]
        if not allowed_visibility:
            send_message(phone, "You do not have access to any shared notes for this business.")
            return {"status": "note_access_denied"}
        query = db.query(BusinessNote).filter(
            BusinessNote.owner_phone == business_owner_phone,
            BusinessNote.visibility.in_(allowed_visibility),
        )

    category_filter = (parsed.get("category") or "").lower()
    if category_filter:
        query = query.filter(BusinessNote.category == category_filter)

    notes = query.order_by(BusinessNote.created_at.desc()).limit(20).all()
    if not notes:
        send_message(phone, "No notes found." + (" Add one with: note rent paid 45000" if is_owner else ""))
        return {"status": "notes_empty"}

    lines = [f"*Business Notes ({len(notes)})*\n"]
    for n in notes:
        date = n.created_at.strftime("%d/%m/%Y") if n.created_at else ""
        amount_str = f" — N{n.amount:,}" if n.amount else ""
        vis = f" [{n.visibility}]" if is_owner else ""
        lines.append(f"[{n.category.upper()}]{amount_str} {date}{vis}\n{n.body.capitalize()}")
    send_message(phone, "\n\n".join(lines))
    return {"status": "notes_viewed"}
