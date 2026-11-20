from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.models.enums import OrderStatus, SupplyType
from app.schemas.common import MoneyIn, OutSchema, PositiveQty, QtyIn, Schema


class OrderLineIn(Schema):
    product_id: int
    quantity: PositiveQty


class OrderIn(Schema):
    customer_id: int
    remarks: str | None = Field(default=None, max_length=500)
    items: list[OrderLineIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique(self) -> "OrderIn":
        ids = [i.product_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each product may appear only once per order")
        return self


class ApprovalLineIn(Schema):
    order_item_id: int
    quantity_approved: QtyIn
    unit_price: MoneyIn | None = None  # admin price correction (audited)


class ApproveIn(Schema):
    version: int = Field(description="Order version the admin reviewed (optimistic lock)")
    lines: list[ApprovalLineIn] = Field(default_factory=list, description="Empty = approve as ordered")
    reason: str | None = Field(default=None, min_length=3, max_length=500)
    credit_override_reason: str | None = Field(
        default=None, min_length=3, max_length=500,
        description="Required only when the order takes the customer over its credit limit (audited)")


class RejectIn(Schema):
    version: int
    reason: str = Field(min_length=3, max_length=500)


class CancelIn(Schema):
    reason: str = Field(min_length=3, max_length=500)


class StockCheckOut(OutSchema):
    order_item_id: int
    product_id: int
    product_code: str
    requested: Decimal
    on_hand: Decimal
    reserved_by_others: Decimal
    available: Decimal
    shortage: Decimal
    can_fulfil: bool


class CreditOut(OutSchema):
    limit: Decimal
    unlimited: bool
    credit_days: int
    outstanding: Decimal
    open_orders: Decimal
    this_order: Decimal
    exposure: Decimal
    available: Decimal | None
    exceeds: bool
    excess: Decimal
    overdue: Decimal
    oldest_overdue_days: int | None


class OrderLineOut(OutSchema):
    id: int
    product_id: int
    product_code: str
    product_name: str
    unit_code: str
    quantity_ordered: Decimal
    quantity_approved: Decimal | None
    quantity_dispatched: Decimal
    unit_price: Decimal
    line_amount: Decimal
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    line_total: Decimal


class OrderOut(OutSchema):
    id: int
    order_no: str
    customer_id: int
    customer_name: str
    customer_state_code: str
    salesman_id: int
    salesman_name: str
    order_date: date
    status: OrderStatus
    remarks: str | None
    submitted_at: datetime | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    version: int
    supply_type: SupplyType
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    has_shortage: bool | None
    items: list[OrderLineOut]
    stock_check: list[StockCheckOut] | None
    credit: CreditOut | None = None  # staff only, while the order awaits approval


class OrderSummaryOut(OutSchema):
    id: int
    order_no: str
    customer_id: int
    customer_name: str
    salesman_id: int
    order_date: date
    status: OrderStatus
    taxable_amount: Decimal
    has_shortage: bool | None


class CatalogItemOut(OutSchema):
    product_id: int
    code: str
    name: str
    unit_code: str
    hsn_code: str
    gst_rate: Decimal
    selling_price: Decimal
    available: Decimal
