"""Test data builders (direct ORM, fast). Mirrors the benchmark's master data."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item, PackagingMaterial, Product, RawMaterial, Supplier, Unit, UnitConversion
from app.models.enums import ItemType, PackagingKind


def unit(db: Session, code: str) -> Unit:
    return db.scalars(select(Unit).where(Unit.code == code)).one()


def make_item(db: Session, code: str, name: str, item_type: ItemType, unit_code: str, **sub) -> Item:
    item = Item(code=code, name=name, item_type=item_type, base_unit_id=unit(db, unit_code).id,
                reorder_level=sub.pop("reorder_level", Decimal("0")), is_active=True)
    db.add(item)
    db.flush()
    if item_type == ItemType.RAW_MATERIAL:
        db.add(RawMaterial(item_id=item.id, category=sub.get("category")))
    elif item_type == ItemType.PACKAGING:
        db.add(PackagingMaterial(item_id=item.id, packaging_kind=sub.get("kind", PackagingKind.OTHER)))
    else:
        db.add(Product(item_id=item.id, hsn_code="2106", gst_rate=Decimal("5"),
                       selling_price=sub.get("price", Decimal("50.00")), net_weight_g=Decimal("200")))
    db.flush()
    db.refresh(item)
    return item


def make_supplier(db: Session, code: str = "SUP-TN", state: str = "33") -> Supplier:
    s = Supplier(code=code, name=f"Supplier {code}", state_code=state, is_active=True)
    db.add(s)
    db.flush()
    return s


def benchmark_materials(db: Session) -> dict:
    """Flour, oil, spice mix, pouch, carton, Murukku 200 g (1 CTN = 20 PKT)."""
    m = {
        "flour": make_item(db, "RM-FLOUR", "Flour", ItemType.RAW_MATERIAL, "KG", reorder_level=Decimal("50")),
        "oil": make_item(db, "RM-OIL", "Cooking oil", ItemType.RAW_MATERIAL, "L"),
        "spice": make_item(db, "RM-SPICE", "Salt and spice mix", ItemType.RAW_MATERIAL, "KG"),
        "pouch": make_item(db, "PM-POUCH200", "200 g pouch", ItemType.PACKAGING, "PCS", kind=PackagingKind.POUCH),
        "carton": make_item(db, "PM-CARTON", "Carton", ItemType.PACKAGING, "PCS", kind=PackagingKind.CARTON),
        "murukku": make_item(db, "FG-MUR200", "Murukku 200 g", ItemType.FINISHED_GOOD, "PKT"),
    }
    db.add(UnitConversion(from_unit_id=unit(db, "CTN").id, to_unit_id=unit(db, "PKT").id,
                          factor=Decimal("20"), item_id=m["murukku"].id))
    db.flush()
    return m


def days_ago(n: int) -> date:
    from datetime import timedelta
    return date.today() - timedelta(days=n)
