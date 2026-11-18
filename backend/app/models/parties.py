"""Customers and suppliers."""
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, enum_col
from app.models.enums import CustomerType

# GSTIN format (15 chars, first two = state code) is validated in Pydantic schemas;
# the DB only guarantees the length so unregistered parties can keep it NULL.


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint("gstin IS NULL OR length(gstin) = 15", name="gstin_length"),
        CheckConstraint("credit_limit >= 0", name="credit_limit_non_negative"),
        CheckConstraint("credit_days >= 0", name="credit_days_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_type: Mapped[CustomerType] = mapped_column(enum_col(CustomerType), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), nullable=False)  # drives place of supply
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str | None] = mapped_column(String(64))
    pincode: Mapped[str | None] = mapped_column(String(6))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    credit_limit: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    credit_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    assigned_salesman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (CheckConstraint("gstin IS NULL OR length(gstin) = 15", name="gstin_length"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
