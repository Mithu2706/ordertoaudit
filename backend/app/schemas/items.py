"""Raw material, packaging material and product schemas.

Each is stored as an `items` row + a subtype row; the API exposes them flattened.
`id` in responses is the item id (the same id used by the stock ledger).
"""
from decimal import Decimal

from pydantic import Field

from app.models import Item, PackagingMaterial, Product, RawMaterial
from app.models.enums import ItemType, PackagingKind
from app.schemas.common import Code, GstRate, HsnCode, MoneyIn, Name, OutSchema, QtyIn, RateIn, Schema

UnitCode = Field(min_length=1, max_length=10)


class _ItemCreate(Schema):
    code: Code
    name: Name
    base_unit_code: str = UnitCode
    standard_cost: RateIn | None = None
    reorder_level: QtyIn = Decimal("0.0000")


class _ItemUpdate(Schema):
    name: Name | None = None
    base_unit_code: str | None = Field(default=None, min_length=1, max_length=10)
    standard_cost: RateIn | None = None
    reorder_level: QtyIn | None = None
    is_active: bool | None = None


class _ItemOut(OutSchema):
    id: int
    code: str
    name: str
    item_type: ItemType
    base_unit_code: str
    standard_cost: Decimal | None
    reorder_level: Decimal
    is_active: bool

    @staticmethod
    def _item_fields(item: Item) -> dict:
        return dict(
            id=item.id, code=item.code, name=item.name, item_type=item.item_type,
            base_unit_code=item.base_unit.code, standard_cost=item.standard_cost,
            reorder_level=item.reorder_level, is_active=item.is_active,
        )


# ---- raw materials --------------------------------------------------------
class RawMaterialCreate(_ItemCreate):
    category: str | None = Field(default=None, max_length=64)
    shelf_life_days: int | None = Field(default=None, ge=0)


class RawMaterialUpdate(_ItemUpdate):
    category: str | None = Field(default=None, max_length=64)
    shelf_life_days: int | None = Field(default=None, ge=0)


class RawMaterialOut(_ItemOut):
    category: str | None
    shelf_life_days: int | None

    @classmethod
    def of(cls, rm: RawMaterial) -> "RawMaterialOut":
        return cls(**cls._item_fields(rm.item), category=rm.category, shelf_life_days=rm.shelf_life_days)


# ---- packaging materials --------------------------------------------------
class PackagingMaterialCreate(_ItemCreate):
    packaging_kind: PackagingKind
    specification: str | None = Field(default=None, max_length=255)


class PackagingMaterialUpdate(_ItemUpdate):
    packaging_kind: PackagingKind | None = None
    specification: str | None = Field(default=None, max_length=255)


class PackagingMaterialOut(_ItemOut):
    packaging_kind: PackagingKind
    specification: str | None

    @classmethod
    def of(cls, pm: PackagingMaterial) -> "PackagingMaterialOut":
        return cls(**cls._item_fields(pm.item), packaging_kind=pm.packaging_kind, specification=pm.specification)


# ---- products (finished goods) -------------------------------------------
class ProductCreate(_ItemCreate):
    hsn_code: HsnCode
    gst_rate: GstRate
    selling_price: MoneyIn
    net_weight_g: QtyIn | None = None


class ProductUpdate(_ItemUpdate):
    hsn_code: HsnCode | None = None
    gst_rate: GstRate | None = None
    selling_price: MoneyIn | None = None
    net_weight_g: QtyIn | None = None


class ProductOut(_ItemOut):
    hsn_code: str
    gst_rate: Decimal
    selling_price: Decimal
    net_weight_g: Decimal | None

    @classmethod
    def of(cls, p: Product) -> "ProductOut":
        return cls(
            **cls._item_fields(p.item), hsn_code=p.hsn_code, gst_rate=p.gst_rate,
            selling_price=p.selling_price, net_weight_g=p.net_weight_g,
        )
