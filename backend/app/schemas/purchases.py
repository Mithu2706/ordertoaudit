from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.models.enums import DocumentStatus
from app.schemas.common import GstRate, OutSchema, PositiveQty, RateIn, Schema


class PurchaseLineIn(Schema):
    item_id: int
    quantity: PositiveQty
    unit_code: str = Field(min_length=1, max_length=10)
    rate: RateIn  # per unit_code, before GST
    gst_rate: GstRate = Decimal("0.0000")


class PurchaseIn(Schema):
    supplier_id: int
    supplier_invoice_no: str = Field(min_length=1, max_length=64)
    supplier_invoice_date: date
    received_date: date
    notes: str | None = Field(default=None, max_length=500)
    items: list[PurchaseLineIn] = Field(min_length=1, max_length=100)

    @field_validator("supplier_invoice_date", "received_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("date cannot be in the future")
        return v

    @model_validator(mode="after")
    def _unique_items(self) -> "PurchaseIn":
        ids = [line.item_id for line in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each item may appear only once per purchase")
        return self


class PurchaseLineOut(OutSchema):
    id: int
    item_id: int
    item_code: str
    item_name: str
    quantity: Decimal
    unit_code: str
    base_quantity: Decimal
    base_unit_code: str
    rate: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal
    returned_quantity: Decimal = Decimal("0.0000")  # sent back to the supplier (purchase returns)


class PurchaseOut(OutSchema):
    id: int
    purchase_no: str
    supplier_id: int
    supplier_name: str
    supplier_invoice_no: str
    supplier_invoice_date: date
    received_date: date
    status: DocumentStatus
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    notes: str | None
    created_by: int
    posted_by: int | None
    posted_at: datetime | None
    items: list[PurchaseLineOut]


class PurchaseSummaryOut(OutSchema):
    id: int
    purchase_no: str
    supplier_id: int
    supplier_invoice_no: str
    received_date: date
    status: DocumentStatus
    taxable_amount: Decimal
    total_amount: Decimal


# ---- purchase returns (debit notes) -----------------------------------------------------
class PurchaseReturnLineIn(Schema):
    purchase_item_id: int
    quantity: PositiveQty  # in the purchase line's unit


class PurchaseReturnIn(Schema):
    return_date: date | None = None  # default today
    reason: str = Field(min_length=3, max_length=500)
    items: list[PurchaseReturnLineIn] = Field(min_length=1, max_length=100)


class PurchaseReturnLineOut(OutSchema):
    purchase_item_id: int
    item_id: int
    item_code: str
    item_name: str
    quantity: Decimal
    unit_code: str
    taxable_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal
    stock_value: Decimal


class PurchaseReturnOut(OutSchema):
    id: int
    return_no: str
    purchase_id: int
    purchase_no: str
    supplier_id: int
    supplier_name: str
    return_date: date
    reason: str
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    stock_value: Decimal
    created_by: int
    items: list[PurchaseReturnLineOut]
