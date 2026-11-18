"""The stock ledger. EVERY stock change in the system goes through post_movement().

post_movement() algorithm (all inside the caller's transaction):
  1. Lock the item row (SELECT ... FOR UPDATE) -> postings for one item are serialised.
  2. Refuse a posting_key that was already used          -> no duplicate postings.
  3. Convert the entered quantity to the item's base unit (exactly).
  4. Read the item's latest movement: balance and value before.
  5. Inbound  : value = given cost; new weighted average = total value / total qty.
     Outbound : refuse if qty > balance (InsufficientStockError with the shortage);
                value = value_before x qty / balance_before (weighted average cost).
  6. Insert the movement with balance_after / value_after. The DB CHECK
     balance_after >= 0 backs up step 5 even if this code had a bug.

Business rules:
  * Inactive items cannot move.
  * Count items (PKT, PCS, CTN) move in whole units.
  * No back-dating before the item's last movement, so ledger order = date order and
    every balance_after is a true point-in-time balance.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import Item, StockMovement, Unit, User
from app.models.enums import (
    INBOUND_MOVEMENTS,
    OUTBOUND_MOVEMENTS,
    DocumentType,
    ItemType,
    MovementType,
    RoleCode,
    UnitDimension,
)
from app.services import audit, numbering
from app.services.units import convert, get_unit

ZERO = Decimal("0")


class InsufficientStockError(BusinessRuleError):
    code = "insufficient_stock"


class DuplicatePostingError(ConflictError):
    code = "duplicate_posting"


@dataclass(frozen=True)
class Balance:
    quantity: Decimal
    value: Decimal

    @property
    def avg_cost(self) -> Decimal:
        return dec.rate(self.value / self.quantity) if self.quantity > 0 else ZERO


def lock_item(db: Session, item_id: int) -> Item:
    # of=Item: lock only the items row (the eager-loaded unit join must not be locked).
    item = db.scalars(select(Item).where(Item.id == item_id).with_for_update(of=Item)).first()
    if item is None:
        raise NotFoundError(f"Item {item_id} not found")
    return item


def _latest(db: Session, item_id: int) -> StockMovement | None:
    return db.scalars(
        select(StockMovement).where(StockMovement.item_id == item_id).order_by(StockMovement.id.desc()).limit(1)
    ).first()


def current_balance(db: Session, item_id: int) -> Balance:
    last = _latest(db, item_id)
    return Balance(last.balance_after, last.value_after) if last else Balance(ZERO, ZERO)


def post_movement(
    db: Session,
    *,
    item_id: int,
    movement_type: MovementType,
    quantity: Decimal,
    unit: Unit | str,
    actor_id: int,
    source_document_type: str,
    reference_no: str,
    posting_key: str,
    movement_date: date,
    source_document_id: int | None = None,
    total_value: Decimal | None = None,
    unit_cost: Decimal | None = None,
    remarks: str | None = None,
) -> StockMovement:
    """Post one stock movement.

    quantity   : positive magnitude, in `unit`; for ADJUSTMENT it is signed (+ gain / - loss).
    total_value: inbound value in rupees (preferred: exact, e.g. a purchase line's taxable value).
    unit_cost  : inbound cost per `unit` (used when total_value is not given).
    """
    quantity = Decimal(quantity)
    if quantity == 0:
        raise BusinessRuleError("Quantity must not be zero")
    if movement_type != MovementType.ADJUSTMENT and quantity < 0:
        raise BusinessRuleError("Quantity must be positive; the movement type decides the direction")

    item = lock_item(db, item_id)
    if not item.is_active:
        raise BusinessRuleError(f"Item {item.code} is inactive and cannot move")
    if db.scalar(select(StockMovement.id).where(StockMovement.posting_key == posting_key)) is not None:
        raise DuplicatePostingError(f"Stock for '{posting_key}' has already been posted", {"posting_key": posting_key})

    entered_unit = unit if isinstance(unit, Unit) else get_unit(db, unit)
    base_unit = item.base_unit
    base_qty = convert(db, abs(quantity), entered_unit, base_unit, item.id)
    if base_unit.dimension == UnitDimension.COUNT and base_qty != base_qty.to_integral_value():
        raise BusinessRuleError(f"{item.code} is counted in {base_unit.code}; quantity must be a whole number")

    last = _latest(db, item.id)
    before = Balance(last.balance_after, last.value_after) if last else Balance(ZERO, ZERO)
    if last is not None and movement_date < last.movement_date:
        raise BusinessRuleError(
            f"Cannot post {item.code} on {movement_date}: its last movement is dated {last.movement_date}",
            {"last_movement_date": last.movement_date.isoformat()},
        )

    inbound = movement_type in INBOUND_MOVEMENTS or (movement_type == MovementType.ADJUSTMENT and quantity > 0)
    if inbound:
        if total_value is None and unit_cost is None:
            if movement_type == MovementType.ADJUSTMENT and before.quantity > 0:
                unit_cost_base = before.avg_cost  # a stock gain is valued at the current average
                value = dec.money(base_qty * unit_cost_base)
            else:
                raise BusinessRuleError("An inbound movement needs a cost (total_value or unit_cost)")
        else:
            value = dec.money(total_value if total_value is not None else abs(quantity) * Decimal(unit_cost))
        if value < 0:
            raise BusinessRuleError("Cost cannot be negative")
        signed_qty = base_qty
        recorded_cost = dec.rate(value / base_qty)
    else:
        assert movement_type in OUTBOUND_MOVEMENTS or movement_type == MovementType.ADJUSTMENT
        if base_qty > before.quantity:
            shortage = base_qty - before.quantity
            raise InsufficientStockError(
                f"Insufficient stock of {item.code}: available {_fmt(before.quantity)} {base_unit.code}, "
                f"required {_fmt(base_qty)} {base_unit.code}, short by {_fmt(shortage)} {base_unit.code}",
                {"item_id": item.id, "item_code": item.code, "unit": base_unit.code,
                 "available": str(before.quantity), "required": str(base_qty), "shortage": str(shortage)},
            )
        # Issue at weighted-average cost; taking the last unit clears any rounding residue.
        out_value = before.value if base_qty == before.quantity else dec.money(before.value * base_qty / before.quantity)
        value = -out_value
        signed_qty = -base_qty
        recorded_cost = before.avg_cost

    movement = StockMovement(
        item_id=item.id,
        movement_type=movement_type,
        movement_date=movement_date,
        quantity=dec.qty(signed_qty),
        unit_id=base_unit.id,
        entered_quantity=dec.qty(abs(quantity)),
        entered_unit_id=entered_unit.id,
        unit_cost=recorded_cost,
        value=dec.money(value),
        balance_after=dec.qty(before.quantity + signed_qty),
        value_after=dec.money(before.value + value),
        source_document_type=source_document_type,
        source_document_id=source_document_id,
        reference_no=reference_no,
        posting_key=posting_key,
        remarks=remarks,
        created_by=actor_id,
    )
    db.add(movement)
    db.flush()
    return movement


def _fmt(q: Decimal) -> str:
    return f"{q.normalize():f}"


# ---- one-off postings ----------------------------------------------------------------
def post_opening_stock(
    db: Session, *, item_id: int, quantity: Decimal, unit_code: str, unit_cost: Decimal,
    movement_date: date, actor: User, remarks: str | None = None, ip: str | None = None,
) -> StockMovement:
    """Opening balance: allowed once, and only as an item's first movement."""
    lock_item(db, item_id)
    if _latest(db, item_id) is not None:
        raise BusinessRuleError("Opening stock can only be the first movement of an item; use an adjustment")
    m = post_movement(
        db, item_id=item_id, movement_type=MovementType.OPENING, quantity=quantity, unit=unit_code,
        unit_cost=unit_cost, actor_id=actor.id, source_document_type="OPENING", reference_no="OPENING",
        posting_key=f"OPENING:{item_id}", movement_date=movement_date, remarks=remarks,
    )
    audit.record(db, user_id=actor.id, action="POST", entity_type="stock_movement", entity_id=m.id,
                 after=audit.snapshot(m), summary="Opening stock", ip=ip)
    return m


def post_adjustment(
    db: Session, *, item_id: int, kind: MovementType, quantity: Decimal, unit_code: str, reason: str,
    movement_date: date, actor: User, unit_cost: Decimal | None = None, ip: str | None = None,
) -> StockMovement:
    """DAMAGE (write-off, quantity > 0) or ADJUSTMENT (signed physical-count correction)."""
    if kind not in (MovementType.DAMAGE, MovementType.ADJUSTMENT):
        raise BusinessRuleError("Only DAMAGE or ADJUSTMENT can be posted manually")
    if kind == MovementType.ADJUSTMENT and actor.role.code != RoleCode.ADMIN:
        raise PermissionDeniedError("Only an admin can post stock adjustments")
    doc = numbering.next_number(db, DocumentType.STOCK_ADJUSTMENT, movement_date)
    m = post_movement(
        db, item_id=item_id, movement_type=kind, quantity=quantity, unit=unit_code, unit_cost=unit_cost,
        actor_id=actor.id, source_document_type="STOCK_ADJUSTMENT", source_document_id=doc.sequence,
        reference_no=doc.number, posting_key=f"ADJ:{doc.number}", movement_date=movement_date, remarks=reason,
    )
    audit.record(db, user_id=actor.id, action="POST", entity_type="stock_movement", entity_id=m.id,
                 after=audit.snapshot(m), summary=f"{kind.value} {doc.number}", reason=reason, ip=ip)
    return m


# ---- queries --------------------------------------------------------------------------
@dataclass
class BalanceRow:
    item: Item
    quantity: Decimal
    value: Decimal

    @property
    def avg_cost(self) -> Decimal:
        return Balance(self.quantity, self.value).avg_cost

    @property
    def low_stock(self) -> bool:
        return self.item.reorder_level > 0 and self.quantity <= self.item.reorder_level


def balances(db: Session, item_type: ItemType | None = None, as_of: date | None = None,
             include_inactive: bool = False) -> list[BalanceRow]:
    """Stock per item, derived from the ledger (latest movement on/before as_of)."""
    latest = select(StockMovement.item_id, func.max(StockMovement.id).label("mid")).group_by(StockMovement.item_id)
    if as_of is not None:
        latest = latest.where(StockMovement.movement_date <= as_of)
    latest = latest.subquery()
    stmt = (
        select(Item, StockMovement.balance_after, StockMovement.value_after)
        .outerjoin(latest, latest.c.item_id == Item.id)
        .outerjoin(StockMovement, StockMovement.id == latest.c.mid)
        .order_by(Item.item_type, Item.name)
    )
    if item_type is not None:
        stmt = stmt.where(Item.item_type == item_type)
    if not include_inactive:
        stmt = stmt.where(Item.is_active)
    return [BalanceRow(item, q if q is not None else ZERO, v if v is not None else ZERO)
            for item, q, v in db.execute(stmt)]


def movements_query(
    *, item_id: int | None = None, movement_type: MovementType | None = None, source_document_type: str | None = None,
    reference_no: str | None = None, date_from: date | None = None, date_to: date | None = None,
) -> Select:
    stmt = select(StockMovement).order_by(StockMovement.id)
    if item_id is not None:
        stmt = stmt.where(StockMovement.item_id == item_id)
    if movement_type is not None:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if source_document_type:
        stmt = stmt.where(StockMovement.source_document_type == source_document_type)
    if reference_no:
        stmt = stmt.where(StockMovement.reference_no == reference_no)
    if date_from is not None:
        stmt = stmt.where(StockMovement.movement_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(StockMovement.movement_date <= date_to)
    return stmt


@dataclass
class Ledger:
    item: Item
    opening: Balance
    movements: list[StockMovement]
    closing: Balance


def item_ledger(db: Session, item_id: int, date_from: date | None = None, date_to: date | None = None) -> Ledger:
    """Stock card: opening balance at date_from, movements in range, closing balance."""
    item = db.get(Item, item_id)
    if item is None:
        raise NotFoundError(f"Item {item_id} not found")
    opening = Balance(ZERO, ZERO)
    if date_from is not None:
        prev = db.scalars(
            select(StockMovement)
            .where(StockMovement.item_id == item_id, StockMovement.movement_date < date_from)
            .order_by(StockMovement.id.desc()).limit(1)
        ).first()
        if prev:
            opening = Balance(prev.balance_after, prev.value_after)
    rows = list(db.scalars(movements_query(item_id=item_id, date_from=date_from, date_to=date_to)))
    closing = Balance(rows[-1].balance_after, rows[-1].value_after) if rows else opening
    return Ledger(item, opening, rows, closing)
