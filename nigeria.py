"""Shared Nigerian reference data."""

NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu",
    "FCT Abuja", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina",
    "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo",
    "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
]

# Identity documents a financier will accept. BVN is deliberately absent: it is
# far more sensitive than the rest, and a partner who needs it should collect it
# directly rather than have CreditVoice store it.
ID_TYPES = [
    ("NIN", "National Identity Number (NIN)"),
    ("DRIVERS_LICENCE", "Driver's licence"),
    ("VOTERS_CARD", "Voter's card"),
    ("PASSPORT", "International passport"),
]


def is_state(name):
    return (name or "").strip().lower() in {s.lower() for s in NIGERIAN_STATES}


def canonical_state(name):
    """The properly-cased state name, or None when unrecognised."""
    target = (name or "").strip().lower()
    for state in NIGERIAN_STATES:
        if state.lower() == target:
            return state
    return None
