"""Small helpers shared by services."""
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.gstin import gstin_error
from app.models import State

M = TypeVar("M")


def get_or_404(db: Session, model: type[M], pk: Any, label: str) -> M:
    obj = db.get(model, pk)
    if obj is None:
        raise NotFoundError(f"{label} {pk} not found")
    return obj


def ensure_unique(
    db: Session, column: InstrumentedAttribute, value: Any, label: str, exclude_pk: Any = None
) -> None:
    """Friendly pre-check; the DB unique constraint remains the real guarantee."""
    if value is None:
        return
    model = column.class_
    stmt = select(model).where(column == value)
    if exclude_pk is not None:
        stmt = stmt.where(model.id != exclude_pk)
    if db.scalars(stmt.limit(1)).first() is not None:
        raise ConflictError(f"{label} '{value}' already exists", {"field": column.key})


def ensure_state(db: Session, state_code: str) -> State:
    state = db.get(State, state_code)
    if state is None:
        raise BusinessRuleError(f"Unknown GST state code '{state_code}'", {"field": "state_code"})
    return state


def ensure_gstin(gstin: str | None, state_code: str) -> None:
    if gstin is None:
        return
    problem = gstin_error(gstin, state_code)
    if problem:
        raise BusinessRuleError(problem, {"field": "gstin"})


def apply_changes(obj: Any, changes: dict[str, Any], required: set[str]) -> None:
    """Apply a PATCH. Explicit null is refused for required (NOT NULL) fields."""
    nulled = sorted(k for k, v in changes.items() if v is None and k in required)
    if nulled:
        raise BusinessRuleError(f"Field(s) cannot be empty: {', '.join(nulled)}", {"fields": nulled})
    for key, value in changes.items():
        setattr(obj, key, value)


def paginate(db: Session, stmt: Select, limit: int, offset: int) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    return rows, total
