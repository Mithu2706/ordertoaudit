"""Stock balances, stock card (ledger), movement listing, opening stock, damage/adjustments.

There is deliberately NO endpoint that sets a stock quantity: stock only changes by
posting movements, and balances are always derived from the ledger.
"""
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import MATERIAL_READERS, DbSession, client_ip, require_roles
from app.models import Item, StockMovement, Unit, User
from app.models.enums import ItemType, MovementType, RoleCode
from app.schemas.common import Page
from app.schemas.inventory import AdjustmentIn, BalanceOut, LedgerOut, MovementOut, OpeningStockIn
from app.services import inventory as svc
from app.services.common import paginate

router = APIRouter(prefix="/inventory", tags=["inventory"])
Reader = Annotated[User, Depends(require_roles(*MATERIAL_READERS))]


def movement_outs(db: Session, rows: list[StockMovement]) -> list[MovementOut]:
    units = {u.id: u.code for u in db.scalars(select(Unit))}
    item_ids = {m.item_id for m in rows}
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(item_ids)))} if item_ids else {}
    return [
        MovementOut(
            id=m.id, item_id=m.item_id, item_code=items[m.item_id].code, item_name=items[m.item_id].name,
            movement_type=m.movement_type, movement_date=m.movement_date, quantity=m.quantity,
            unit_code=units[m.unit_id], entered_quantity=m.entered_quantity,
            entered_unit_code=units[m.entered_unit_id], unit_cost=m.unit_cost, value=m.value,
            balance_after=m.balance_after, value_after=m.value_after,
            source_document_type=m.source_document_type, source_document_id=m.source_document_id,
            reference_no=m.reference_no, remarks=m.remarks, created_by=m.created_by, created_at=m.created_at,
        )
        for m in rows
    ]


@router.get("/balances", response_model=list[BalanceOut])
def balances(
    db: DbSession, _: Reader,
    item_type: Annotated[ItemType | None, Query()] = None,
    as_of: Annotated[date | None, Query(description="Balance at end of this date")] = None,
    low_stock_only: bool = False,
):
    rows = svc.balances(db, item_type=item_type, as_of=as_of)
    if low_stock_only:
        rows = [r for r in rows if r.low_stock]
    return [
        BalanceOut(item_id=r.item.id, item_code=r.item.code, item_name=r.item.name, item_type=r.item.item_type,
                   unit_code=r.item.base_unit.code, quantity=r.quantity, value=r.value, avg_cost=r.avg_cost,
                   reorder_level=r.item.reorder_level, low_stock=r.low_stock)
        for r in rows
    ]


@router.get("/items/{item_id}/ledger", response_model=LedgerOut)
def ledger(item_id: int, db: DbSession, _: Reader,
           date_from: Annotated[date | None, Query()] = None, date_to: Annotated[date | None, Query()] = None):
    led = svc.item_ledger(db, item_id, date_from, date_to)
    total_in = sum((m.quantity for m in led.movements if m.quantity > 0), Decimal("0"))
    total_out = sum((-m.quantity for m in led.movements if m.quantity < 0), Decimal("0"))
    return LedgerOut(
        item_id=led.item.id, item_code=led.item.code, item_name=led.item.name, unit_code=led.item.base_unit.code,
        date_from=date_from, date_to=date_to, opening_quantity=led.opening.quantity, opening_value=led.opening.value,
        total_in=total_in, total_out=total_out, closing_quantity=led.closing.quantity,
        closing_value=led.closing.value, movements=movement_outs(db, led.movements),
    )


@router.get("/movements", response_model=Page[MovementOut])
def movements(
    db: DbSession, _: Reader,
    item_id: int | None = None,
    movement_type: Annotated[MovementType | None, Query()] = None,
    source_document_type: Annotated[str | None, Query(max_length=32)] = None,
    reference_no: Annotated[str | None, Query(max_length=64)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = svc.movements_query(item_id=item_id, movement_type=movement_type, source_document_type=source_document_type,
                               reference_no=reference_no, date_from=date_from, date_to=date_to)
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=movement_outs(db, rows), total=total, limit=limit, offset=offset)


@router.post("/opening-stock", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def opening_stock(data: OpeningStockIn, db: DbSession, request: Request,
                  actor: Annotated[User, Depends(require_roles(RoleCode.ADMIN))]):
    m = svc.post_opening_stock(
        db, item_id=data.item_id, quantity=data.quantity, unit_code=data.unit_code, unit_cost=data.unit_cost,
        movement_date=data.movement_date or date.today(), actor=actor, remarks=data.remarks, ip=client_ip(request),
    )
    return movement_outs(db, [m])[0]


@router.post("/adjustments", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def adjustment(data: AdjustmentIn, db: DbSession, request: Request,
               actor: Annotated[User, Depends(require_roles(RoleCode.ADMIN, RoleCode.PRODUCTION))]):
    """DAMAGE: admin or production. ADJUSTMENT (stock-count correction): admin only."""
    m = svc.post_adjustment(
        db, item_id=data.item_id, kind=MovementType(data.kind), quantity=data.quantity, unit_code=data.unit_code,
        reason=data.reason, movement_date=data.movement_date or date.today(), actor=actor,
        unit_cost=data.unit_cost, ip=client_ip(request),
    )
    return movement_outs(db, [m])[0]
