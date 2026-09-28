"""
Know-your-customer details for financing applications.

Deliberately NOT asked at sign-up: a trader should be able to start keeping
records without proving who they are. It is asked once, at the point a financier
genuinely needs it — when the owner applies — and shared only with the partner
they applied to.
"""
from models import BusinessKyc, utcnow
from nigeria import ID_TYPES, canonical_state

# What a financier needs before an introduction is worth making. Anything here
# that is missing blocks an application, with the gaps named so the app can send
# the owner straight to the form.
REQUIRED_FIELDS = [
    ("legal_name", "Your full name as written on your ID"),
    ("state", "State where the business operates"),
    ("city", "Town or city"),
    ("address", "Business address"),
    ("id_type", "Type of ID"),
    ("id_number", "ID number"),
    # Yes or no is required; being unregistered is a normal answer, and only a
    # partner that insists on registration will turn it away.
    ("is_registered", "Whether the business is registered (CAC)"),
]

OPTIONAL_FIELDS = [
    ("date_of_birth", "Date of birth"),
    ("registered_name", "Registered business name (if registered)"),
    ("registration_number", "RC / BN number (if registered)"),
    ("guarantor_name", "Guarantor's name"),
    ("guarantor_phone", "Guarantor's phone"),
    ("years_in_business", "Years in business"),
    ("employees", "Number of people working with you"),
]

_ID_KEYS = {key for key, _label in ID_TYPES}


def get_kyc(db, owner_phone):
    return db.query(BusinessKyc).filter(BusinessKyc.owner_phone == owner_phone).first()


def missing_fields(kyc):
    """[(field, label)] still needed before an application can be submitted."""
    if kyc is None:
        return list(REQUIRED_FIELDS)
    gaps = []
    for field, label in REQUIRED_FIELDS:
        value = getattr(kyc, field, None)
        # A boolean answer of False is an answer; only None is missing.
        missing = value is None if field == "is_registered" else not (value or "")
        if missing:
            gaps.append((field, label))
    # Claiming registration without the number leaves a partner unable to check it.
    if kyc.is_registered and not (kyc.registration_number or "").strip():
        gaps.append(("registration_number", "RC / BN number"))
    return gaps


def mask_id(number):
    """Show only the last 4 digits — enough to check against a document, not
    enough to be worth stealing."""
    value = (number or "").strip()
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * (len(value) - 4) + value[-4:]


def save_kyc(db, owner_phone, payload):
    """Create or update the record. Returns (kyc, error). Validates the state
    against the real list so coverage matching can rely on it."""
    kyc = get_kyc(db, owner_phone)
    if kyc is None:
        kyc = BusinessKyc(owner_phone=owner_phone)
        db.add(kyc)

    if payload.get("state"):
        state = canonical_state(payload["state"])
        if not state:
            return None, f"'{payload['state']}' is not a Nigerian state."
        kyc.state = state
    if payload.get("id_type"):
        if payload["id_type"] not in _ID_KEYS:
            return None, f"ID type must be one of {sorted(_ID_KEYS)}."
        kyc.id_type = payload["id_type"]

    if "is_registered" in payload and payload.get("is_registered") is not None:
        kyc.is_registered = bool(payload["is_registered"])
    for field in ("legal_name", "city", "address", "id_number",
                  "guarantor_name", "guarantor_phone", "date_of_birth",
                  "registered_name", "registration_number"):
        if field in payload:
            value = (payload.get(field) or "").strip()
            setattr(kyc, field, value or None)
    for field in ("years_in_business", "employees"):
        if field in payload and payload.get(field) not in (None, ""):
            try:
                setattr(kyc, field, max(0, int(payload[field])))
            except (TypeError, ValueError):
                return None, f"{field.replace('_', ' ').title()} must be a number."

    kyc.updated_at = utcnow()
    kyc.completed_at = utcnow() if not missing_fields(kyc) else None
    return kyc, None


def kyc_dict(kyc, full_id=False):
    """The record for the owner's own form, or for an admin. `full_id` is only
    ever True for the owner and app admins."""
    if kyc is None:
        return None
    return {
        "legal_name": kyc.legal_name,
        "date_of_birth": kyc.date_of_birth,
        "state": kyc.state,
        "city": kyc.city,
        "address": kyc.address,
        "id_type": kyc.id_type,
        "id_number": kyc.id_number if full_id else mask_id(kyc.id_number),
        "is_registered": kyc.is_registered,
        "registered_name": kyc.registered_name,
        "registration_number": kyc.registration_number,
        "guarantor_name": kyc.guarantor_name,
        "guarantor_phone": kyc.guarantor_phone,
        "years_in_business": kyc.years_in_business,
        "employees": kyc.employees,
        "complete": kyc.completed_at is not None,
        "updated_at": kyc.updated_at.isoformat() if kyc.updated_at else None,
    }


# ── Partner coverage ─────────────────────────────────────────────────────────

def partner_covers(partner, state):
    """Does this partner operate where the business is?

    Unknown state → treated as covered, so a missing profile shows the partner
    and the KYC step asks for the state, rather than hiding offers for a reason
    nobody explained.
    """
    if partner is None:
        return False
    if getattr(partner, "nationwide", True):
        return True
    import json
    try:
        states = json.loads(partner.states_covered or "[]")
    except (ValueError, TypeError):
        states = []
    if not states:
        return True          # nothing recorded — don't hide them
    if not state:
        return True
    return state.lower() in {str(s).lower() for s in states}


def coverage_label(partner):
    if getattr(partner, "nationwide", True):
        return "Nationwide"
    import json
    try:
        states = json.loads(partner.states_covered or "[]")
    except (ValueError, TypeError):
        states = []
    return ", ".join(states) if states else "Nationwide"


def kyc_checks(partner, kyc, eligibility):
    """Requirements a partner sets on WHO the business is, rather than on its
    trading record — currently registration. Same shape as the scorecard checks
    so the card lists them together."""
    checks = []
    if (eligibility or {}).get("requires_registered_business"):
        registered = bool(kyc and kyc.is_registered)
        checks.append({
            "requirement": "registered business (CAC)",
            "required": "Yes",
            "actual": "Yes" if registered else "No",
            "passed": registered,
        })
    return checks
