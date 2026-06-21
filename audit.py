"""Lightweight audit trail helper.

Usage:
    from audit import audit
    audit(db, action="LOGIN_OK", actor_id=user.id, actor_phone=user.phone, ip=client_ip)
    db.commit()  # caller is responsible for committing
"""
import logging

from models import AuditLog

_log = logging.getLogger("creditvoice.audit")


def audit(db, *, action: str, actor_id=None, actor_phone: str = None,
          resource: str = None, ip: str = None) -> None:
    """Insert an AuditLog row. Swallows errors so a logging failure never
    breaks the actual operation — the error is still emitted to the log stream."""
    try:
        db.add(AuditLog(
            actor_id=actor_id,
            actor_phone=actor_phone,
            action=action,
            resource=resource,
            ip=ip,
        ))
    except Exception as exc:
        _log.error("audit log write failed [%s]: %s", action, exc)
