"""Unified item master (class-table inheritance).

`items` is the single thing the stock ledger, BOM and purchases point at.
Type-specific details live in raw_materials / packaging_materials / products.
"""
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, Pct, Qty, Rate, TimestampMixin, enum_col
from app.models.enums import ItemType, PackagingKind
from app.models.reference import Unit


class Item(TimestampMixin, Base):
    __tablename__ = "items"
    __table_args__ = (CheckConstraint("reorder_level >= 0", name="reorder_level_non_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    item_type: Mapped[ItemType] = mapped_column(enum_col(ItemType), nullable=False, index=True)
    # All ledger quantities for this item are stored in its base unit.
    base_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    standard_cost: Mapped[Decimal | None] = mapped_column(Rate())  # per base unit, for planning only
    reorder_level: Mapped[Decimal] = mapped_column(Qty(), default=Decimal("0"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    base_unit: Mapped[Unit] = relationship(lazy="joined")


class RawMaterial(Base):
    __tablename__ = "raw_materials"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[str | None] = mapped_column(String(64))  # flour, oil, spice...
    shelf_life_days: Mapped[int | None]

    item: Mapped[Item] = relationship(lazy="joined")


class PackagingMaterial(Base):
    __tablename__ = "packaging_materials"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    packaging_kind: Mapped[PackagingKind] = mapped_column(enum_col(PackagingKind), nullable=False)
    specification: Mapped[str | None] = mapped_column(String(255))

    item: Mapped[Item] = relationship(lazy="joined")


class Product(Base):
    """Finished good (saleable)."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("selling_price >= 0", name="selling_price_non_negative"),
        CheckConstraint("gst_rate >= 0 AND gst_rate <= 28", name="gst_rate_range"),
    )

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    hsn_code: Mapped[str] = mapped_column(String(8), nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Pct(), nullable=False)  # exercise: 5%
    selling_price: Mapped[Decimal] = mapped_column(Money(), nullable=False)  # per base unit, before GST
    net_weight_g: Mapped[Decimal | None] = mapped_column(Qty())

    item: Mapped[Item] = relationship(lazy="joined")
