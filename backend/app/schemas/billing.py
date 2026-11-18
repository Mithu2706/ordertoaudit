from datetime import date
from decimal import Decimal

from pydantic import Field, model_validator

from app.models.enums import CreditNoteReason, InvoiceStatus, PaymentMode, SupplyType
from app.schemas.common import MoneyIn, OutSchema, PositiveQty, QtyIn, Schema


# ---- invoices ---------------------------------------------------------------------------
class InvoiceCreate(Schema):
    order_id: int
    invoice_date: date | None = None


class InvoiceLineOut(OutSchema):
    id: int
    order_item_id: int
    product_id: int
    description: str
    hsn_code: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal
    taxable_amount: Decimal
    gst_rate: Decimal
    cgst_rate: Decimal
    cgst_amount: Decimal
    sgst_rate: Decimal
    sgst_amount: Decimal
    igst_rate: Decimal
    igst_amount: Decimal
    line_total: Decimal


class InvoiceOut(OutSchema):
    id: int
    invoice_no: str
    financial_year: str
    invoice_date: date
    order_id: int
    order_no: str
    customer_id: int
    customer_name: str
    customer_gstin: str | None
    billing_address: str
    place_of_supply_state_code: str
    place_of_supply: str
    supplier_state_code: str
    supply_type: SupplyType
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    round_off: Decimal
    total_amount: Decimal
    credited_amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    status: InvoiceStatus
    amount_in_words: str
    items: list[InvoiceLineOut]


class InvoiceSummaryOut(OutSchema):
    id: int
    invoice_no: str
    invoice_date: date
    customer_id: int
    customer_name: str
    supply_type: SupplyType
    taxable_amount: Decimal
    total_amount: Decimal
    balance: Decimal
    status: InvoiceStatus


# ---- dispatch ---------------------------------------------------------------------------
class DispatchLineIn(Schema):
    order_item_id: int
    quantity: PositiveQty


class DispatchCreate(Schema):
    order_id: int
    dispatch_date: date | None = None
    vehicle_no: str | None = Field(default=None, max_length=20)
    transporter: str | None = Field(default=None, max_length=128)
    remarks: str | None = Field(default=None, max_length=500)
    items: list[DispatchLineIn] | None = Field(default=None, description="Omit to dispatch everything pending")


class DispatchLineOut(OutSchema):
    order_item_id: int
    product_id: int
    quantity: Decimal


class DispatchOut(OutSchema):
    id: int
    dispatch_no: str
    order_id: int
    invoice_id: int | None
    dispatch_date: date
    vehicle_no: str | None
    transporter: str | None
    remarks: str | None
    items: list[DispatchLineOut]


# ---- credit notes -----------------------------------------------------------------------
class CreditLine(Schema):
    invoice_item_id: int
    quantity: QtyIn = Decimal("0.0000")
    taxable_amount: MoneyIn | None = None


class CreditNoteCreate(Schema):
    reason_type: CreditNoteReason
    reason: str = Field(min_length=3, max_length=500)
    restock: bool = False
    credit_note_date: date | None = None
    lines: list[CreditLine] = Field(default_factory=list, description="Not used for CANCELLATION")

    @model_validator(mode="after")
    def _shape(self) -> "CreditNoteCreate":
        if self.reason_type == CreditNoteReason.PRICE_ADJUSTMENT and self.restock:
            raise ValueError("a price adjustment cannot restock goods")
        return self


class CreditNoteLineOut(OutSchema):
    invoice_item_id: int
    product_id: int
    quantity: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    line_total: Decimal


class CreditNoteOut(OutSchema):
    id: int
    credit_note_no: str
    credit_note_date: date
    invoice_id: int
    customer_id: int
    reason_type: CreditNoteReason
    reason: str
    restock: bool
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    items: list[CreditNoteLineOut]


# ---- payments ---------------------------------------------------------------------------
class AllocationIn(Schema):
    invoice_id: int
    amount: MoneyIn


class PaymentCreate(Schema):
    customer_id: int
    payment_date: date | None = None
    amount: MoneyIn
    mode: PaymentMode
    reference_no: str | None = Field(default=None, max_length=64)
    remarks: str | None = Field(default=None, max_length=500)
    allocations: list[AllocationIn] | None = Field(default=None, description="Omit for automatic oldest-first")

    @model_validator(mode="after")
    def _positive(self) -> "PaymentCreate":
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        return self


class AllocationOut(OutSchema):
    invoice_id: int
    invoice_no: str
    amount: Decimal


class PaymentOut(OutSchema):
    id: int
    receipt_no: str
    customer_id: int
    customer_name: str
    payment_date: date
    amount: Decimal
    mode: PaymentMode
    reference_no: str | None
    remarks: str | None
    unallocated: Decimal
    allocations: list[AllocationOut]


# ---- receivables ------------------------------------------------------------------------
class OpenInvoiceOut(OutSchema):
    invoice_id: int
    invoice_no: str
    invoice_date: date
    total_amount: Decimal
    balance: Decimal
    age_days: int


class ReceivableOut(OutSchema):
    customer_id: int
    customer_code: str
    customer_name: str
    invoiced: Decimal
    credited: Decimal
    received: Decimal
    invoice_outstanding: Decimal
    unallocated_advance: Decimal
    outstanding: Decimal
    ageing: dict[str, Decimal]
    open_invoices: list[OpenInvoiceOut]
