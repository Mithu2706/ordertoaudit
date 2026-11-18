"""Audit trail helpers. Every service that changes important data calls record()."""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import AuditLog

# Never written to the audit log.
_SENSITIVE = {"password_hash"}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def snapshot(obj: Any) -> dict[str, Any]:
    """Column values of an ORM object as a JSON-safe dict."""
    mapper = inspect(obj).mapper
    return {
        attr.key: _json_safe(getattr(obj, attr.key))
        for attr in mapper.column_attrs
        if attr.key not in _SENSITIVE and attr.key not in {"created_at", "updated_at"}
    }


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in after.items() if before.get(k) != v}


def record(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    summary: str | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before_data=before,
        after_data=after,
        summary=summary,
        reason=reason,
        ip_address=ip,
    )
    db.add(log)
    return log


def record_update(
    db: Session, *, user_id: int, entity_type: str, entity_id: Any, before: dict, after: dict,
    reason: str | None = None, ip: str | None = None,
) -> AuditLog | None:
    """Log only the fields that actually changed; no row if nothing changed."""
    diff = changed_fields(before, after)
    if not diff:
        return None
    return record(
        db, user_id=user_id, action="UPDATE", entity_type=entity_type, entity_id=entity_id,
        before={k: before.get(k) for k in diff}, after=diff,
        summary=f"Updated {', '.join(sorted(diff))}", reason=reason, ip=ip,
    )
