from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.core import decimals as dec
from app.models.enums import ItemType, MovementType
from app.schemas.common import OutSchema, PositiveQty, RateIn, Schema


def _not_future(v: date | None) -> date | None:
    if v is not None and v > date.today():
        raise ValueError("date cannot be in the future")
    return v


class OpeningStockIn(Schema):
    item_id: int
    quantity: PositiveQty
    unit_code: str = Field(min_length=1, max_length=10)
    unit_cost: RateIn  # per unit_code
    movement_date: date | None = None  # defaults to today
    remarks: str | None = Field(default=None, max_length=255)

    _d = field_validator("movement_date")(classmethod(lambda cls, v: _not_future(v)))


class AdjustmentIn(Schema):
    item_id: int
    kind: Literal["DAMAGE", "ADJUSTMENT"]
    # DAMAGE: positive quantity written off. ADJUSTMENT: signed (+ found, - missing).
    quantity: Decimal = Field(max_digits=16, decimal_places=4)
    unit_code: str = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=3, max_length=255)
    unit_cost: RateIn | None = None  # only for a positive adjustment of an item with no stock
    movement_date: date | None = None

    _d = field_validator("movement_date")(classmethod(lambda cls, v: _not_future(v)))

    @model_validator(mode="after")
    def _sign(self) -> "AdjustmentIn":
        if self.quantity == 0:
            raise ValueError("quantity must not be zero")
        if self.kind == "DAMAGE" and self.quantity < 0:
            raise ValueError("damage quantity must be positive")
        self.quantity = dec.qty(self.quantity)
        return self


class BalanceOut(OutSchema):
    item_id: int
    item_code: str
    item_name: str
    item_type: ItemType
    unit_code: str
    quantity: Decimal
    value: Decimal
    avg_cost: Decimal
    reorder_level: Decimal
    low_stock: bool


class MovementOut(OutSchema):
    id: int
    item_id: int
    item_code: str
    item_name: str
    movement_type: MovementType
    movement_date: date
    quantity: Decimal  # signed, base unit
    unit_code: str
    entered_quantity: Decimal
    entered_unit_code: str
    unit_cost: Decimal
    value: Decimal
    balance_after: Decimal
    value_after: Decimal
    source_document_type: str
    source_document_id: int | None
    reference_no: str
    remarks: str | None
    created_by: int
    created_at: datetime


class LedgerOut(OutSchema):
    item_id: int
    item_code: str
    item_name: str
    unit_code: str
    date_from: date | None
    date_to: date | None
    opening_quantity: Decimal
    opening_value: Decimal
    total_in: Decimal
    total_out: Decimal
    closing_quantity: Decimal
    closing_value: Decimal
    movements: list[MovementOut]
