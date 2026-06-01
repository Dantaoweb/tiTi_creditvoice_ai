import re


def normalize_phone(phone_str):
    """Convert local Nigerian numbers to international format for the Meta API."""
    if not phone_str:
        return None
    clean = re.sub(r"\D", "", phone_str)
    if clean.startswith("0") and len(clean) == 11:
        return "234" + clean[1:]
    return clean
