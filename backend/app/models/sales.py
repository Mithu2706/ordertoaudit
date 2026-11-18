"""Sales orders and dispatches."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, Qty, TimestampMixin, enum_col
from app.models.enums import DispatchStatus, OrderStatus


class SalesOrder(TimestampMixin, Base):
    __tablename__ = "sales_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    salesman_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[OrderStatus] = mapped_column(enum_col(OrderStatus), nullable=False, index=True)
    remarks: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    # Optimistic locking: an admin edit fails if the order changed underneath.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    items: Mapped[list["SalesOrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")

    __mapper_args__ = {"version_id_col": version}


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id"),
        CheckConstraint("quantity_ordered > 0", name="ordered_positive"),
        CheckConstraint("quantity_approved IS NULL OR quantity_approved >= 0", name="approved_non_negative"),
        CheckConstraint("quantity_dispatched >= 0", name="dispatched_non_negative"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.item_id"), nullable=False, index=True)
    quantity_ordered: Mapped[Decimal] = mapped_column(Qty(), nullable=False)
    quantity_approved: Mapped[Decimal | None] = mapped_column(Qty())  # set by admin on approval
    quantity_dispatched: Mapped[Decimal] = mapped_column(Qty(), default=Decimal("0"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money(), nullable=False)  # price before GST, captured at order
    line_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    order: Mapped[SalesOrder] = relationship(back_populates="items")


class Dispatch(TimestampMixin, Base):
    __tablename__ = "dispatches"

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False, index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    dispatch_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[DispatchStatus] = mapped_column(enum_col(DispatchStatus), nullable=False)
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    transporter: Mapped[str | None] = mapped_column(String(128))
    remarks: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    items: Mapped[list["DispatchItem"]] = relationship(back_populates="dispatch", cascade="all, delete-orphan")


class DispatchItem(Base):
    __tablename__ = "dispatch_items"
    __table_args__ = (
        UniqueConstraint("dispatch_id", "order_item_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("sales_order_items.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.item_id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)

    dispatch: Mapped[Dispatch] = relationship(back_populates="items")
