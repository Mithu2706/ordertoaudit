"""Production runs: plan from the BOM, record actuals, post to the ledger in ONE transaction.

Lifecycle: DRAFT (planned, actuals editable) -> POSTED (stock moved, immutable) | CANCELLED.

Planned quantities
  raw materials : BOM per batch x batch count (input standard, fixed when the run is created)
  packaging     : BOM per packet x actual GOOD output, rounded down for count items
                  (recomputed at posting; see variance.packaging_standard)
  expected out  : BOM batch yield x batch count

post_production_run(), in order (the spec's steps 1-6):
  1. PRODUCTION_ISSUE for each raw material's actual consumption
  2. PRODUCTION_ISSUE for packaging used + DAMAGE for packaging spoiled
  3. PRODUCTION_OUTPUT of GOOD output into finished goods, valued at the run's total cost
  4-6. save costs, consumption rows, variance % and alert flags on the run
Any failure (e.g. insufficient oil) raises, and the request transaction rolls back all of it.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import Item, Product, ProductionConsumption, ProductionRun, Unit, User
from app.models.enums import DocumentStatus, DocumentType, ItemType, MovementType, UnitDimension
from app.schemas.production import ProductionActualsIn, ProductionRunCreate
from app.services import audit, numbering
from app.services.bom import active_bom, explode, get_bom, output_in_base
from app.services.common import paginate
from app.services.inventory import post_movement
from app.services.reference import get_setting
from app.services.units import convert, get_unit
from app.services.variance import is_alert, packaging_standard, variance_pct

ZERO = Decimal("0")


def _get(db: Session, run_id: int, lock: bool = False) -> ProductionRun:
    stmt = select(ProductionRun).where(ProductionRun.id == run_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    run = db.scalars(stmt).first()
    if run is None:
        raise NotFoundError(f"Production run {run_id} not found")
    return run


def get_run(db: Session, run_id: int) -> ProductionRun:
    return _get(db, run_id)


def _require_draft(run: ProductionRun) -> None:
    if run.status == DocumentStatus.POSTED:
        raise ConflictError(f"Production run {run.run_no} is already posted")
    if run.status != DocumentStatus.DRAFT:
        raise BusinessRuleError(f"Production run {run.run_no} is {run.status.value}")


def create_run(db: Session, data: ProductionRunCreate, actor: User, ip: str | None = None) -> ProductionRun:
    product = db.get(Product, data.product_id)
    if product is None or not product.item.is_active:
        raise BusinessRuleError("Product not found or inactive", {"field": "product_id"})
    if data.bom_id is not None:
        bom = get_bom(db, data.bom_id)
        if bom.product_id != product.item_id:
            raise BusinessRuleError("BOM does not belong to this product", {"field": "bom_id"})
    else:
        bom = active_bom(db, product.item_id)

    when = data.production_date or date.today()
    run = ProductionRun(
        run_no=numbering.next_number(db, DocumentType.PRODUCTION_RUN, when).number,
        product_id=product.item_id, bom_id=bom.id, production_date=when, status=DocumentStatus.DRAFT,
        batch_count=data.batch_count, expected_output=dec.qty(output_in_base(db, bom) * data.batch_count),
        variance_tolerance_pct=dec.pct(get_setting(db, "variance_tolerance_pct")),
        remarks=data.remarks, created_by=actor.id,
    )
    for req in explode(db, bom, data.batch_count):
        run.consumption.append(ProductionConsumption(
            item_id=req.item.id, component_type=req.item.item_type, unit_id=req.item.base_unit_id,
            # Packaging's real standard depends on good output; until then show the batch estimate.
            planned_quantity=dec.qty(req.quantity),
        ))
    db.add(run)
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="production_run", entity_id=run.id,
                 after=audit.snapshot(run), summary=f"Run {run.run_no} planned from BOM v{bom.version}", ip=ip)
    return run


def record_actuals(db: Session, run_id: int, data: ProductionActualsIn, actor: User, ip: str | None = None) -> ProductionRun:
    run = _get(db, run_id, lock=True)
    _require_draft(run)
    rows = {c.item_id: c for c in run.consumption}
    given = {line.item_id for line in data.consumption}
    unknown = given - rows.keys()
    if unknown:
        raise BusinessRuleError(f"Item(s) {sorted(unknown)} are not in this run's BOM")
    missing = rows.keys() - given
    if missing:
        raise BusinessRuleError(f"Actual consumption missing for item(s) {sorted(missing)}", {"items": sorted(missing)})

    before = audit.snapshot(run)
    for line in data.consumption:
        row = rows[line.item_id]
        item = db.get(Item, line.item_id)
        unit = get_unit(db, line.unit_code) if line.unit_code else item.base_unit
        if line.damaged_quantity > 0 and row.component_type != ItemType.PACKAGING:
            raise BusinessRuleError(f"{item.code}: spoiled raw material is part of its actual consumption, "
                                    "not a separate damaged quantity")
        row.actual_quantity = convert(db, line.actual_quantity, unit, item.base_unit, item.id)
        row.damaged_quantity = convert(db, line.damaged_quantity, unit, item.base_unit, item.id)

    run.actual_good_output = data.actual_good_output
    run.damaged_output = data.damaged_output
    run.wastage_qty = data.wastage_qty
    run.wastage_unit_id = get_unit(db, data.wastage_unit_code).id if data.wastage_unit_code else None
    run.labour_cost = data.labour_cost
    run.power_gas_cost = data.power_gas_cost
    if data.remarks is not None:
        run.remarks = data.remarks
    db.flush()
    audit.record_update(db, user_id=actor.id, entity_type="production_run", entity_id=run.id,
                        before=before, after=audit.snapshot(run), ip=ip)
    return run


def post_run(db: Session, run_id: int, actor: User, ip: str | None = None) -> ProductionRun:
    run = _get(db, run_id, lock=True)
    _require_draft(run)
    if run.actual_good_output is None or any(c.actual_quantity is None for c in run.consumption):
        raise BusinessRuleError("Record actual consumption and output before posting")

    bom = get_bom(db, run.bom_id)
    batch_output = output_in_base(db, bom)
    per_batch = {r.item.id: r.per_batch_base for r in explode(db, bom, Decimal(1))}
    tolerance = Decimal(run.variance_tolerance_pct)
    good = Decimal(run.actual_good_output)
    when = run.production_date

    def issue(row: ProductionConsumption, mtype: MovementType, qty: Decimal, tag: str):
        return post_movement(
            db, item_id=row.item_id, movement_type=mtype, quantity=qty, unit=db.get(Unit, row.unit_id),
            actor_id=actor.id, source_document_type="PRODUCTION_RUN", source_document_id=run.id,
            reference_no=run.run_no, posting_key=f"PRD:{run.id}:{tag}:{row.item_id}", movement_date=when,
        )

    material_cost = packaging_cost = ZERO
    any_alert = False
    # Raw materials first, then packaging (steps 1 and 2).
    for row in sorted(run.consumption, key=lambda c: c.component_type != ItemType.RAW_MATERIAL):
        cost = ZERO
        if row.actual_quantity > 0:
            cost += -issue(row, MovementType.PRODUCTION_ISSUE, row.actual_quantity, "ISSUE").value
        if row.damaged_quantity > 0:
            cost += -issue(row, MovementType.DAMAGE, row.damaged_quantity, "DAMAGE").value

        if row.component_type == ItemType.PACKAGING:
            item = db.get(Item, row.item_id)
            row.planned_quantity = packaging_standard(
                per_batch[row.item_id], batch_output, good, item.base_unit.dimension == UnitDimension.COUNT)
            packaging_cost += cost
        else:
            material_cost += cost

        consumed = row.actual_quantity + row.damaged_quantity
        row.total_cost = dec.money(cost)
        row.unit_cost = dec.rate(cost / consumed) if consumed > 0 else None
        row.variance_pct = variance_pct(row.planned_quantity, consumed)
        row.is_variance_alert = is_alert(row.variance_pct, tolerance, row.planned_quantity, consumed)
        any_alert |= row.is_variance_alert

    total = dec.money(material_cost + packaging_cost + run.labour_cost + run.power_gas_cost)
    # Step 3: only GOOD output enters stock; it carries the full cost (damaged packets never do).
    if good > 0:
        post_movement(
            db, item_id=run.product_id, movement_type=MovementType.PRODUCTION_OUTPUT, quantity=good,
            unit=db.get(Item, run.product_id).base_unit, total_value=total, actor_id=actor.id,
            source_document_type="PRODUCTION_RUN", source_document_id=run.id, reference_no=run.run_no,
            posting_key=f"PRD:{run.id}:OUTPUT", movement_date=when,
        )

    run.material_cost = dec.money(material_cost)
    run.packaging_cost = dec.money(packaging_cost)
    run.total_cost = total
    run.cost_per_good_unit = dec.rate(total / good) if good > 0 else None
    run.yield_variance_pct = variance_pct(run.expected_output, good)
    yield_alert = is_alert(run.yield_variance_pct, tolerance, run.expected_output, good)
    run.has_variance_alert = any_alert or yield_alert
    run.status = DocumentStatus.POSTED
    run.posted_by = actor.id
    run.posted_at = datetime.now(UTC)
    db.flush()
    audit.record(db, user_id=actor.id, action="POST", entity_type="production_run", entity_id=run.id,
                 after=audit.snapshot(run),
                 summary=f"Run {run.run_no} posted: {good.normalize():f} good, cost {total}"
                         + (" (variance alert)" if run.has_variance_alert else ""), ip=ip)
    return run


def cancel_run(db: Session, run_id: int, reason: str, actor: User, ip: str | None = None) -> ProductionRun:
    run = _get(db, run_id, lock=True)
    _require_draft(run)
    run.status = DocumentStatus.CANCELLED
    db.flush()
    audit.record(db, user_id=actor.id, action="CANCEL", entity_type="production_run", entity_id=run.id,
                 reason=reason, summary=f"Run {run.run_no} cancelled", ip=ip)
    return run


def list_runs(db: Session, *, product_id=None, status=None, date_from=None, date_to=None,
              alerts_only: bool = False, limit: int = 50, offset: int = 0):
    stmt = select(ProductionRun).order_by(ProductionRun.production_date.desc(), ProductionRun.id.desc())
    if product_id is not None:
        stmt = stmt.where(ProductionRun.product_id == product_id)
    if status is not None:
        stmt = stmt.where(ProductionRun.status == status)
    if date_from is not None:
        stmt = stmt.where(ProductionRun.production_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(ProductionRun.production_date <= date_to)
    if alerts_only:
        stmt = stmt.where(ProductionRun.has_variance_alert)
    return paginate(db, stmt, limit, offset)
