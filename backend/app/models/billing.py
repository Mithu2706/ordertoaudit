"""GST invoices and credit notes. Invoices are never deleted; they are reversed by credit notes."""
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, Pct, Qty, TimestampMixin, enum_col
from app.models.enums import CreditNoteReason, InvoiceStatus, SupplyType

_TAX_SPLIT = (
    "(supply_type = 'INTRA_STATE' AND igst_amount = 0)"
    " OR (supply_type = 'INTER_STATE' AND cgst_amount = 0 AND sgst_amount = 0)"
)


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("financial_year", "sequence_no"),
        CheckConstraint(_TAX_SPLIT, name="tax_split_matches_supply_type"),
        CheckConstraint(
            "total_amount = taxable_amount + cgst_amount + sgst_amount + igst_amount + round_off",
            name="total_matches",
        ),
        CheckConstraint("taxable_amount >= 0", name="taxable_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # INV/2026-27/00001
    financial_year: Mapped[str] = mapped_column(String(7), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)

    # Snapshot of party details at time of invoicing (masters may change later).
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_gstin: Mapped[str | None] = mapped_column(String(15))
    billing_address: Mapped[str] = mapped_column(String(500), nullable=False)
    place_of_supply_state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), nullable=False)
    supplier_state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), nullable=False)
    supply_type: Mapped[SupplyType] = mapped_column(enum_col(SupplyType), nullable=False)

    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    round_off: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    status: Mapped[InvoiceStatus] = mapped_column(enum_col(InvoiceStatus), nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "line_total = taxable_amount + cgst_amount + sgst_amount + igst_amount", name="line_total_matches"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("sales_order_items.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.item_id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    hsn_code: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Pct(), nullable=False)
    cgst_rate: Mapped[Decimal] = mapped_column(Pct(), default=Decimal("0"), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_rate: Mapped[Decimal] = mapped_column(Pct(), default=Decimal("0"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_rate: Mapped[Decimal] = mapped_column(Pct(), default=Decimal("0"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class CreditNote(TimestampMixin, Base):
    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint("financial_year", "sequence_no"),
        CheckConstraint(
            "total_amount = taxable_amount + cgst_amount + sgst_amount + igst_amount", name="total_matches"
        ),
        CheckConstraint("total_amount > 0", name="total_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # CN/2026-27/00001
    financial_year: Mapped[str] = mapped_column(String(7), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    credit_note_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    reason_type: Mapped[CreditNoteReason] = mapped_column(enum_col(CreditNoteReason), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    restock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # posts SALES_RETURN
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    items: Mapped[list["CreditNoteItem"]] = relationship(back_populates="credit_note", cascade="all, delete-orphan")


class CreditNoteItem(Base):
    __tablename__ = "credit_note_items"
    __table_args__ = (CheckConstraint("quantity >= 0", name="quantity_non_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(
        ForeignKey("credit_notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.item_id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)  # 0 for pure price adjustment
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    credit_note: Mapped[CreditNote] = relationship(back_populates="items")
