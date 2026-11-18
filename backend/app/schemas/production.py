from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.models.enums import DocumentStatus, ItemType
from app.schemas.common import MoneyIn, OutSchema, PositiveQty, QtyIn, Schema

UnitCode = Field(min_length=1, max_length=10)


# ---- BOM ---------------------------------------------------------------------------
class BomLineIn(Schema):
    item_id: int
    quantity: PositiveQty  # per batch
    unit_code: str = UnitCode


class BomIn(Schema):
    product_id: int
    batch_output_qty: PositiveQty  # expected yield per batch, e.g. 200
    output_unit_code: str = UnitCode  # PKT
    notes: str | None = Field(default=None, max_length=500)
    activate: bool = True
    items: list[BomLineIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique(self) -> "BomIn":
        ids = [i.item_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each component may appear only once")
        return self


class BomLineOut(OutSchema):
    id: int
    item_id: int
    item_code: str
    item_name: str
    component_type: ItemType
    quantity: Decimal
    unit_code: str
    sequence: int


class BomOut(OutSchema):
    id: int
    product_id: int
    product_code: str
    product_name: str
    version: int
    batch_output_qty: Decimal
    output_unit_code: str
    is_active: bool
    notes: str | None
    created_at: datetime
    items: list[BomLineOut]


# ---- production runs ---------------------------------------------------------------
class ProductionRunCreate(Schema):
    product_id: int
    bom_id: int | None = None  # default: the product's active BOM
    batch_count: PositiveQty = Decimal("1.0000")
    production_date: date | None = None  # default today
    remarks: str | None = Field(default=None, max_length=500)

    @field_validator("production_date")
    @classmethod
    def _not_future(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("date cannot be in the future")
        return v


class ActualLineIn(Schema):
    item_id: int
    actual_quantity: QtyIn  # used in good production
    unit_code: str | None = Field(default=None, max_length=10)  # default: item base unit
    damaged_quantity: QtyIn = Decimal("0.0000")  # packaging only: spoiled while packing


class ProductionActualsIn(Schema):
    consumption: list[ActualLineIn] = Field(min_length=1, max_length=50)
    actual_good_output: QtyIn
    damaged_output: QtyIn = Decimal("0.0000")  # finished packets unfit for sale (never stocked)
    wastage_qty: QtyIn = Decimal("0.0000")  # e.g. kg of dough lost
    wastage_unit_code: str | None = Field(default=None, max_length=10)
    labour_cost: MoneyIn = Decimal("0.00")
    power_gas_cost: MoneyIn = Decimal("0.00")
    remarks: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _unique(self) -> "ProductionActualsIn":
        ids = [c.item_id for c in self.consumption]
        if len(ids) != len(set(ids)):
            raise ValueError("each component may appear only once")
        return self


class ConsumptionOut(OutSchema):
    item_id: int
    item_code: str
    item_name: str
    component_type: ItemType
    unit_code: str
    planned_quantity: Decimal
    actual_quantity: Decimal | None
    damaged_quantity: Decimal
    total_consumed: Decimal | None
    variance_quantity: Decimal | None
    variance_pct: Decimal | None
    is_variance_alert: bool
    unit_cost: Decimal | None
    total_cost: Decimal | None


class ProductionRunOut(OutSchema):
    id: int
    run_no: str
    product_id: int
    product_code: str
    product_name: str
    output_unit_code: str
    bom_id: int
    bom_version: int
    production_date: date
    status: DocumentStatus
    batch_count: Decimal
    expected_output: Decimal
    actual_good_output: Decimal | None
    damaged_output: Decimal
    wastage_qty: Decimal
    wastage_unit_code: str | None
    labour_cost: Decimal
    power_gas_cost: Decimal
    material_cost: Decimal | None
    packaging_cost: Decimal | None
    total_cost: Decimal | None
    cost_per_good_unit: Decimal | None
    yield_variance_pct: Decimal | None
    variance_tolerance_pct: Decimal
    has_variance_alert: bool
    remarks: str | None
    posted_at: datetime | None
    consumption: list[ConsumptionOut]


class ProductionRunSummaryOut(OutSchema):
    id: int
    run_no: str
    product_id: int
    production_date: date
    status: DocumentStatus
    expected_output: Decimal
    actual_good_output: Decimal | None
    yield_variance_pct: Decimal | None
    has_variance_alert: bool
    total_cost: Decimal | None
    cost_per_good_unit: Decimal | None
