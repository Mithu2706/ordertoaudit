"""Purchases (raw-material / packaging receipts)."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, Pct, Qty, Rate, TimestampMixin, enum_col
from app.models.enums import DocumentStatus


class Purchase(TimestampMixin, Base):
    __tablename__ = "purchases"
    __table_args__ = (
        # The same supplier bill cannot be entered twice.
        UniqueConstraint("supplier_id", "supplier_invoice_no"),
        CheckConstraint(
            "total_amount = taxable_amount + cgst_amount + sgst_amount + igst_amount", name="total_matches"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier_invoice_no: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[DocumentStatus] = mapped_column(enum_col(DocumentStatus), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["PurchaseItem"]] = relationship(back_populates="purchase", cascade="all, delete-orphan")


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("base_quantity > 0", name="base_quantity_positive"),
        CheckConstraint("rate >= 0", name="rate_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)  # as entered
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    base_quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)  # converted to item base unit
    rate: Mapped[Decimal] = mapped_column(Rate(), nullable=False)  # per entered unit, before GST
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Pct(), default=Decimal("0"), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    purchase: Mapped[Purchase] = relationship(back_populates="items")
