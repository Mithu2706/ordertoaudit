"""Unit conversion.

Conversions form a graph: each `unit_conversions` row is an edge (1 from = factor x to)
and its inverse (1 to = 1/factor x from). To convert, we search for a path from the
source unit to the target unit, using global edges plus the item's own packing edges
(item-specific edges override a global edge for the same pair).

Examples:  40 KG -> 40000 G;   10500 ML -> 10.5 L;   9 CTN -> 180 PKT (Murukku, 1 CTN = 20 PKT)

Rules:
* Factors are multiplied as exact fractions, so inverse edges (1/3) never introduce
  rounding. Results must be exact to 4 decimal places (the ledger's precision); a
  conversion that would silently round (e.g. 1 PCS -> 0.333... of a 3-piece carton)
  is refused.
* There is no path between dimensions (kg <-> L) unless an item-specific edge provides it.
"""
from collections import deque
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.decimals import QTY_STEP
from app.core.errors import BusinessRuleError
from app.models import Unit, UnitConversion


def get_unit(db: Session, code_or_id: str | int) -> Unit:
    if isinstance(code_or_id, int):
        unit = db.get(Unit, code_or_id)
    else:
        unit = db.scalars(select(Unit).where(Unit.code == code_or_id.strip().upper())).first()
    if unit is None:
        raise BusinessRuleError(f"Unknown unit '{code_or_id}'", {"field": "unit"})
    return unit


def _edges(db: Session, item_id: int | None) -> dict[int, dict[int, Fraction]]:
    """Adjacency map with EXACT factors (fractions), so 1/3 x 3 is exactly 1."""
    rows = db.scalars(
        select(UnitConversion).where(
            or_(UnitConversion.item_id.is_(None), UnitConversion.item_id == item_id)
            if item_id is not None
            else UnitConversion.item_id.is_(None)
        )
    ).all()
    graph: dict[int, dict[int, Fraction]] = {}
    # Global first, then item-specific, so item-specific overwrites the same pair.
    for conv in sorted(rows, key=lambda c: c.item_id is not None):
        f = Fraction(Decimal(conv.factor))
        graph.setdefault(conv.from_unit_id, {})[conv.to_unit_id] = f
        graph.setdefault(conv.to_unit_id, {})[conv.from_unit_id] = 1 / f
    return graph


def conversion_factor(db: Session, from_unit: Unit, to_unit: Unit, item_id: int | None = None) -> Fraction:
    """Exact multiplier such that qty_in_to = qty_in_from x factor."""
    if from_unit.id == to_unit.id:
        return Fraction(1)
    graph = _edges(db, item_id)
    # Breadth-first search: shortest chain of conversions.
    queue: deque[tuple[int, Fraction]] = deque([(from_unit.id, Fraction(1))])
    seen = {from_unit.id}
    while queue:
        node, acc = queue.popleft()
        for nxt, f in graph.get(node, {}).items():
            if nxt in seen:
                continue
            if nxt == to_unit.id:
                return acc * f
            seen.add(nxt)
            queue.append((nxt, acc * f))
    raise BusinessRuleError(
        f"No conversion from {from_unit.code} to {to_unit.code}"
        + (" for this item" if item_id else ""),
        {"from_unit": from_unit.code, "to_unit": to_unit.code},
    )


_QTY_SCALE = 10_000  # 4 decimal places


def convert(db: Session, quantity: Decimal, from_unit: Unit, to_unit: Unit, item_id: int | None = None) -> Decimal:
    """Convert exactly; refuse results that need more than 4 decimal places."""
    exact = Fraction(Decimal(quantity)) * conversion_factor(db, from_unit, to_unit, item_id)
    scaled = exact * _QTY_SCALE
    if scaled.denominator != 1:
        raise BusinessRuleError(
            f"{quantity} {from_unit.code} cannot be expressed exactly in {to_unit.code}",
            {"from_unit": from_unit.code, "to_unit": to_unit.code},
        )
    return (Decimal(scaled.numerator) / _QTY_SCALE).quantize(QTY_STEP)
