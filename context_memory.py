from datetime import datetime, timedelta, timezone

from models import CustomerMemory

SESSION_MINUTES = 10


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_memory(db, phone):
    return db.query(CustomerMemory).filter(CustomerMemory.phone == phone).first()


def _get_or_create(db, phone):
    memory = get_memory(db, phone)
    if not memory:
        memory = CustomerMemory(phone=phone)
        db.add(memory)
    return memory


def save_context(db, phone, **kwargs):
    """Write any subset of context fields and refresh the session window."""
    memory = _get_or_create(db, phone)
    for key, value in kwargs.items():
        setattr(memory, key, value)
    memory.session_expires_at = _now() + timedelta(minutes=SESSION_MINUTES)
    db.commit()
    return memory


def save_last_customer(db, phone, customer_name):
    """Update last_customer without touching session or other fields."""
    memory = _get_or_create(db, phone)
    memory.last_customer = customer_name
    db.commit()


def session_active(memory):
    """True if the context memory session has not yet expired."""
    if not memory or not memory.session_expires_at:
        return False
    return _now() < memory.session_expires_at


def get_active_menu(db, phone):
    """
    Return the last_menu name if the session is still active, else None.
    Used to recover numbered replies after the PendingAction has expired.
    """
    memory = get_memory(db, phone)
    if not session_active(memory):
        return None
    return memory.last_menu


def clear_menu(db, phone):
    """Clear the saved menu so a stale numbered reply doesn't misfire."""
    memory = get_memory(db, phone)
    if memory:
        memory.last_menu = None
        db.commit()
