"""Bills of Materials: versioned and immutable.

A BOM that production runs have used must never change (it would rewrite history),
so there is no edit: a change is a new version, and activating it retires the old one.
At most one version per product is active (also enforced by a partial unique index).
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Bom, BomItem, Item, Product, Unit, User
from app.models.enums import ItemType
from app.schemas.production import BomIn
from app.services import audit
from app.services.common import paginate
from app.services.units import convert, get_unit


@dataclass(frozen=True)
class Requirement:
    """One BOM component scaled to a run, in the component's base unit."""

    bom_item: BomItem
    item: Item
    per_batch_base: Decimal
    quantity: Decimal  # per_batch_base x batch_count


def get_bom(db: Session, bom_id: int) -> Bom:
    bom = db.get(Bom, bom_id)
    if bom is None:
        raise NotFoundError(f"BOM {bom_id} not found")
    return bom


def active_bom(db: Session, product_id: int) -> Bom:
    bom = db.scalars(select(Bom).where(Bom.product_id == product_id, Bom.is_active)).first()
    if bom is None:
        raise BusinessRuleError("This product has no active BOM", {"product_id": product_id})
    return bom


def output_in_base(db: Session, bom: Bom) -> Decimal:
    """BOM batch yield expressed in the product's base unit (e.g. 200 PKT)."""
    product_item = db.get(Item, bom.product_id)
    return convert(db, bom.batch_output_qty, db.get(Unit, bom.output_unit_id), product_item.base_unit, product_item.id)


def explode(db: Session, bom: Bom, batch_count: Decimal) -> list[Requirement]:
    reqs = []
    for line in bom.items:
        item = db.get(Item, line.item_id)
        per_batch = convert(db, line.quantity, db.get(Unit, line.unit_id), item.base_unit, item.id)
        reqs.append(Requirement(line, item, per_batch, per_batch * Decimal(batch_count)))
    return reqs


def list_boms(db: Session, product_id: int | None, active: bool | None, limit: int, offset: int):
    stmt = select(Bom).order_by(Bom.product_id, Bom.version.desc())
    if product_id is not None:
        stmt = stmt.where(Bom.product_id == product_id)
    if active is not None:
        stmt = stmt.where(Bom.is_active == active)
    return paginate(db, stmt, limit, offset)


def create_bom(db: Session, data: BomIn, actor: User, ip: str | None = None) -> Bom:
    product = db.get(Product, data.product_id)
    if product is None or not product.item.is_active:
        raise BusinessRuleError("Product not found or inactive", {"field": "product_id"})
    out_unit = get_unit(db, data.output_unit_code)
    # Must be expressible in the product's base unit (e.g. 10 CTN -> 200 PKT is fine).
    convert(db, data.batch_output_qty, out_unit, product.item.base_unit, product.item_id)

    version = (db.scalar(select(func.max(Bom.version)).where(Bom.product_id == product.item_id)) or 0) + 1
    bom = Bom(product_id=product.item_id, version=version, batch_output_qty=data.batch_output_qty,
              output_unit_id=out_unit.id, is_active=False, notes=data.notes, created_by=actor.id)
    for seq, line in enumerate(data.items, start=1):
        item = db.get(Item, line.item_id)
        if item is None or not item.is_active:
            raise BusinessRuleError(f"Line {seq}: item {line.item_id} not found or inactive")
        if item.item_type not in (ItemType.RAW_MATERIAL, ItemType.PACKAGING):
            raise BusinessRuleError(f"Line {seq}: {item.code} is not a raw or packaging material")
        unit = get_unit(db, line.unit_code)
        convert(db, line.quantity, unit, item.base_unit, item.id)  # validates the unit
        bom.items.append(BomItem(item_id=item.id, component_type=item.item_type, quantity=line.quantity,
                                 unit_id=unit.id, sequence=seq))
    db.add(bom)
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="bom", entity_id=bom.id,
                 after={**audit.snapshot(bom), "items": [audit.snapshot(i) for i in bom.items]},
                 summary=f"BOM v{version} for {product.item.code}", ip=ip)
    if data.activate:
        activate_bom(db, bom.id, actor, ip)
    return bom


def activate_bom(db: Session, bom_id: int, actor: User, ip: str | None = None) -> Bom:
    bom = get_bom(db, bom_id)
    if bom.is_active:
        return bom
    current = db.scalars(select(Bom).where(Bom.product_id == bom.product_id, Bom.is_active)).first()
    if current is not None:
        current.is_active = False
        db.flush()  # free the "one active BOM" slot before taking it
    bom.is_active = True
    db.flush()
    audit.record(db, user_id=actor.id, action="ACTIVATE", entity_type="bom", entity_id=bom.id,
                 summary=f"BOM v{bom.version} activated" + (f", v{current.version} retired" if current else ""), ip=ip)
    return bom
