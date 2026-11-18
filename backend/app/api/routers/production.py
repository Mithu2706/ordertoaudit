from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import MATERIAL_READERS, DbSession, client_ip, require_roles
from app.models import Bom, Item, ProductionRun, Unit, User
from app.models.enums import DocumentStatus, RoleCode
from app.schemas.common import Page
from app.schemas.production import (
    BomIn,
    BomLineOut,
    BomOut,
    ConsumptionOut,
    ProductionActualsIn,
    ProductionRunCreate,
    ProductionRunOut,
    ProductionRunSummaryOut,
)
from app.services import bom as bom_svc
from app.services import production as svc
from app.services.costing import run_costing

boms = APIRouter(prefix="/boms", tags=["boms"])
runs = APIRouter(prefix="/production-runs", tags=["production"])
Reader = Annotated[User, Depends(require_roles(*MATERIAL_READERS))]
Writer = Annotated[User, Depends(require_roles(RoleCode.PRODUCTION, RoleCode.ADMIN))]


def _maps(db: Session, item_ids: set[int]) -> tuple[dict[int, str], dict[int, Item]]:
    units = {u.id: u.code for u in db.scalars(select(Unit))}
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(item_ids)))} if item_ids else {}
    return units, items


def bom_out(db: Session, bom: Bom) -> BomOut:
    units, items = _maps(db, {li.item_id for li in bom.items} | {bom.product_id})
    product = items[bom.product_id]
    return BomOut(
        id=bom.id, product_id=bom.product_id, product_code=product.code, product_name=product.name,
        version=bom.version, batch_output_qty=bom.batch_output_qty, output_unit_code=units[bom.output_unit_id],
        is_active=bom.is_active, notes=bom.notes, created_at=bom.created_at,
        items=[BomLineOut(id=li.id, item_id=li.item_id, item_code=items[li.item_id].code,
                          item_name=items[li.item_id].name, component_type=li.component_type,
                          quantity=li.quantity, unit_code=units[li.unit_id], sequence=li.sequence)
               for li in bom.items],
    )


def run_out(db: Session, run: ProductionRun) -> ProductionRunOut:
    units, items = _maps(db, {c.item_id for c in run.consumption} | {run.product_id})
    product = items[run.product_id]
    consumption = []
    for c in sorted(run.consumption, key=lambda c: (c.component_type.value != "RAW_MATERIAL", c.id or 0)):
        consumed = None if c.actual_quantity is None else c.actual_quantity + c.damaged_quantity
        consumption.append(ConsumptionOut(
            item_id=c.item_id, item_code=items[c.item_id].code, item_name=items[c.item_id].name,
            component_type=c.component_type, unit_code=units[c.unit_id], planned_quantity=c.planned_quantity,
            actual_quantity=c.actual_quantity, damaged_quantity=c.damaged_quantity, total_consumed=consumed,
            variance_quantity=None if consumed is None else consumed - c.planned_quantity,
            variance_pct=c.variance_pct, is_variance_alert=c.is_variance_alert,
            unit_cost=c.unit_cost, total_cost=c.total_cost,
        ))
    costing = run_costing(db, run)
    return ProductionRunOut(
        selling_price=costing.selling_price if costing else None,
        gross_margin_per_unit=costing.margin_per_unit if costing else None,
        gross_margin_pct=costing.margin_pct if costing else None,
        id=run.id, run_no=run.run_no, product_id=run.product_id, product_code=product.code,
        product_name=product.name, output_unit_code=units[product.base_unit_id], bom_id=run.bom_id,
        bom_version=db.get(Bom, run.bom_id).version, production_date=run.production_date, status=run.status,
        batch_count=run.batch_count, expected_output=run.expected_output, actual_good_output=run.actual_good_output,
        damaged_output=run.damaged_output, wastage_qty=run.wastage_qty,
        wastage_unit_code=units.get(run.wastage_unit_id) if run.wastage_unit_id else None,
        labour_cost=run.labour_cost, power_gas_cost=run.power_gas_cost, material_cost=run.material_cost,
        packaging_cost=run.packaging_cost, total_cost=run.total_cost, cost_per_good_unit=run.cost_per_good_unit,
        yield_variance_pct=run.yield_variance_pct, variance_tolerance_pct=run.variance_tolerance_pct,
        has_variance_alert=run.has_variance_alert, remarks=run.remarks, posted_at=run.posted_at,
        consumption=consumption,
    )


# ---- BOMs ------------------------------------------------------------------------------
@boms.get("", response_model=Page[BomOut])
def list_boms(db: DbSession, _: Reader, product_id: int | None = None, active: bool | None = None,
              limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0):
    rows, total = bom_svc.list_boms(db, product_id, active, limit, offset)
    return Page(items=[bom_out(db, b) for b in rows], total=total, limit=limit, offset=offset)


@boms.get("/{bom_id}", response_model=BomOut)
def get_bom(bom_id: int, db: DbSession, _: Reader):
    return bom_out(db, bom_svc.get_bom(db, bom_id))


@boms.post("", response_model=BomOut, status_code=status.HTTP_201_CREATED)
def create_bom(data: BomIn, db: DbSession, actor: Writer, request: Request):
    """BOMs are immutable versions: to change one, create a new version."""
    return bom_out(db, bom_svc.create_bom(db, data, actor, client_ip(request)))


@boms.post("/{bom_id}/activate", response_model=BomOut)
def activate_bom(bom_id: int, db: DbSession, actor: Writer, request: Request):
    return bom_out(db, bom_svc.activate_bom(db, bom_id, actor, client_ip(request)))


# ---- production runs -------------------------------------------------------------------
@runs.get("", response_model=Page[ProductionRunSummaryOut])
def list_runs(
    db: DbSession, _: Reader, product_id: int | None = None,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    date_from: date | None = None, date_to: date | None = None,
    alerts_only: bool = Query(False, description="Only runs with a variance alert"),
    limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = svc.list_runs(db, product_id=product_id, status=status_, date_from=date_from, date_to=date_to,
                                alerts_only=alerts_only, limit=limit, offset=offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)


@runs.get("/{run_id}", response_model=ProductionRunOut)
def get_run(run_id: int, db: DbSession, _: Reader):
    """Planned vs actual consumption, costs and variance for one run."""
    return run_out(db, svc.get_run(db, run_id))


@runs.post("", response_model=ProductionRunOut, status_code=status.HTTP_201_CREATED)
def create_run(data: ProductionRunCreate, db: DbSession, actor: Writer, request: Request):
    return run_out(db, svc.create_run(db, data, actor, client_ip(request)))


@runs.put("/{run_id}/actuals", response_model=ProductionRunOut)
def record_actuals(run_id: int, data: ProductionActualsIn, db: DbSession, actor: Writer, request: Request):
    return run_out(db, svc.record_actuals(db, run_id, data, actor, client_ip(request)))


@runs.post("/{run_id}/post", response_model=ProductionRunOut)
def post_run(run_id: int, db: DbSession, actor: Writer, request: Request):
    """Issue materials, receive finished goods, compute cost and variance — all or nothing."""
    return run_out(db, svc.post_run(db, run_id, actor, client_ip(request)))


@runs.post("/{run_id}/cancel", response_model=ProductionRunOut)
def cancel_run(run_id: int, db: DbSession, actor: Writer, request: Request,
               reason: Annotated[str, Body(embed=True, min_length=3, max_length=255)]):
    return run_out(db, svc.cancel_run(db, run_id, reason, actor, client_ip(request)))
