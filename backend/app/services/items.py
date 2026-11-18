"""Item masters: raw materials, packaging materials and products.

One generic implementation handles all three, because each is an `items` row plus
a 1-to-1 subtype row. Creating both happens in the request's single transaction.
"""
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Item, PackagingMaterial, Product, RawMaterial, StockMovement, Unit, User
from app.models.enums import ItemType, UnitDimension
from app.services import audit
from app.services.common import apply_changes, ensure_unique, paginate

SubModel = RawMaterial | PackagingMaterial | Product

_SUBTYPES: dict[ItemType, tuple[type, frozenset[str], str]] = {
    ItemType.RAW_MATERIAL: (RawMaterial, frozenset({"category", "shelf_life_days"}), "raw_material"),
    ItemType.PACKAGING: (PackagingMaterial, frozenset({"packaging_kind", "specification"}), "packaging_material"),
    ItemType.FINISHED_GOOD: (Product, frozenset({"hsn_code", "gst_rate", "selling_price", "net_weight_g"}), "product"),
}
_ITEM_FIELDS = frozenset({"name", "standard_cost", "reorder_level", "is_active"})
_REQUIRED = {"name", "reorder_level", "is_active", "packaging_kind", "hsn_code", "gst_rate", "selling_price"}


def resolve_unit(db: Session, code: str) -> Unit:
    unit = db.scalars(select(Unit).where(Unit.code == code.strip().upper())).first()
    if unit is None:
        raise BusinessRuleError(f"Unknown unit '{code}'", {"field": "base_unit_code"})
    return unit


def _check_unit_for_type(item_type: ItemType, unit: Unit) -> None:
    # Finished goods are counted and sold per packet/piece, never by weight.
    if item_type == ItemType.FINISHED_GOOD and unit.dimension != UnitDimension.COUNT:
        raise BusinessRuleError("A product's base unit must be a count unit (e.g. PKT)", {"field": "base_unit_code"})


def _snapshot(sub: SubModel) -> dict[str, Any]:
    data = audit.snapshot(sub.item)
    data.update({k: v for k, v in audit.snapshot(sub).items() if k != "item_id"})
    return data


def list_items(db: Session, item_type: ItemType, q: str | None, active: bool | None, limit: int, offset: int):
    model = _SUBTYPES[item_type][0]
    stmt = select(model).join(Item, Item.id == model.item_id).order_by(Item.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Item.name.ilike(like), Item.code.ilike(like)))
    if active is not None:
        stmt = stmt.where(Item.is_active == active)
    return paginate(db, stmt, limit, offset)


def get_item(db: Session, item_type: ItemType, item_id: int) -> SubModel:
    model, _, label = _SUBTYPES[item_type]
    sub = db.get(model, item_id)
    if sub is None:
        raise NotFoundError(f"{label.replace('_', ' ').capitalize()} {item_id} not found")
    return sub


def create_item(db: Session, item_type: ItemType, data, actor: User, ip: str | None = None) -> SubModel:
    model, sub_fields, label = _SUBTYPES[item_type]
    ensure_unique(db, Item.code, data.code, "Item code")
    unit = resolve_unit(db, data.base_unit_code)
    _check_unit_for_type(item_type, unit)
    payload = data.model_dump()
    item = Item(
        code=payload["code"], name=payload["name"], item_type=item_type, base_unit_id=unit.id,
        standard_cost=payload["standard_cost"], reorder_level=payload["reorder_level"], is_active=True,
    )
    db.add(item)
    db.flush()
    sub = model(item_id=item.id, **{k: payload[k] for k in sub_fields})
    db.add(sub)
    db.flush()
    db.refresh(sub)
    audit.record(db, user_id=actor.id, action="CREATE", entity_type=label, entity_id=item.id,
                 after=_snapshot(sub), summary=f"{item.code} created", ip=ip)
    return sub


def update_item(db: Session, item_type: ItemType, item_id: int, data, actor: User, ip: str | None = None) -> SubModel:
    _, sub_fields, label = _SUBTYPES[item_type]
    sub = get_item(db, item_type, item_id)
    item = sub.item
    before = _snapshot(sub)
    changes = data.model_dump(exclude_unset=True)

    unit_code = changes.pop("base_unit_code", None)
    if unit_code is not None:
        unit = resolve_unit(db, unit_code)
        if unit.id != item.base_unit_id:
            # Ledger quantities are stored in the base unit; changing it would corrupt history.
            if db.scalar(select(exists().where(StockMovement.item_id == item.id))):
                raise BusinessRuleError("Base unit cannot change once stock movements exist for this item",
                                        {"field": "base_unit_code"})
            _check_unit_for_type(item_type, unit)
            item.base_unit_id = unit.id

    apply_changes(item, {k: v for k, v in changes.items() if k in _ITEM_FIELDS}, _REQUIRED)
    apply_changes(sub, {k: v for k, v in changes.items() if k in sub_fields}, _REQUIRED)
    db.flush()
    db.refresh(item)
    audit.record_update(db, user_id=actor.id, entity_type=label, entity_id=item.id,
                        before=before, after=_snapshot(sub), ip=ip)
    return sub
