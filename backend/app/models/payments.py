"""Customer receipts and their allocation to invoices.

Outstanding per invoice = total - credit notes - allocations.
Unallocated receipt balance = on-account advance.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, TimestampMixin, enum_col
from app.models.enums import PaymentMode


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    mode: Mapped[PaymentMode] = mapped_column(enum_col(PaymentMode), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(64))  # UTR / cheque no.
    remarks: Mapped[str | None] = mapped_column(String(500))
    received_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("payment_id", "invoice_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="allocations")
