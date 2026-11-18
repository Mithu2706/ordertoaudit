"""A tiny report framework: every report is a function returning a `Report` (typed columns +
rows of Decimal/date/str values). The same object is rendered as JSON, CSV, Excel or PDF,
so the four formats can never disagree.

    @report("sales-register", "Sales register", roles=FINANCE, description="...")
    def sales_register(db, p: Params) -> Report: ...
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.models import User
from app.models.enums import RoleCode


class Kind(str, Enum):
    TEXT = "text"
    DATE = "date"
    INT = "int"
    QTY = "qty"
    MONEY = "money"
    RATE = "rate"
    PCT = "pct"
    BOOL = "bool"


NUMERIC = {Kind.INT, Kind.QTY, Kind.MONEY, Kind.RATE, Kind.PCT}


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: Kind = Kind.TEXT
    total: bool = False  # include in the totals row


@dataclass
class Params:
    date_from: date
    date_to: date
    item_id: int | None = None
    customer_id: int | None = None
    product_id: int | None = None
    actor: User | None = None


@dataclass
class Report:
    key: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    filters: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, Any] | None:
        cols = [c for c in self.columns if c.total]
        if not cols:
            return None
        return {c.key: sum((Decimal(r[c.key]) for r in self.rows if r.get(c.key) is not None), Decimal("0"))
                for c in cols}


Builder = Callable[[Session, Params], Report]


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: str
    description: str
    roles: frozenset[RoleCode]
    builder: Builder
    params: tuple[str, ...] = ()  # extra filters beyond the date range


REGISTRY: dict[str, ReportDef] = {}


def report(key: str, title: str, *, roles: tuple[RoleCode, ...], description: str,
           params: tuple[str, ...] = ()) -> Callable[[Builder], Builder]:
    def deco(fn: Builder) -> Builder:
        REGISTRY[key] = ReportDef(key, title, description, frozenset(roles), fn, params)
        return fn
    return deco


def plain(value: Any) -> Any:
    """JSON-safe value: Decimals as exact strings (never floats), dates as ISO strings."""
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def to_json(rep: Report) -> dict[str, Any]:
    totals = rep.totals
    return {
        "key": rep.key, "title": rep.title, "filters": rep.filters, "notes": rep.notes,
        "columns": [{"key": c.key, "label": c.label, "kind": c.kind.value, "total": c.total} for c in rep.columns],
        "rows": [{k: plain(v) for k, v in r.items()} for r in rep.rows],
        "totals": {k: plain(v) for k, v in totals.items()} if totals else None,
        "row_count": len(rep.rows),
    }
