"""Bill of Materials: standard inputs for one batch of a finished product."""
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Qty, TimestampMixin, enum_col
from app.models.enums import ItemType


class Bom(TimestampMixin, Base):
    __tablename__ = "boms"
    __table_args__ = (
        UniqueConstraint("product_id", "version"),
        CheckConstraint("batch_output_qty > 0", name="batch_output_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        # At most one active BOM per product.
        Index(
            "uq_boms_one_active_per_product",
            "product_id",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.item_id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    batch_output_qty: Mapped[Decimal] = mapped_column(Qty(), nullable=False)  # expected yield, e.g. 200
    output_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)  # PKT
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    items: Mapped[list["BomItem"]] = relationship(
        back_populates="bom", cascade="all, delete-orphan", order_by="BomItem.sequence"
    )


class BomItem(Base):
    __tablename__ = "bom_items"
    __table_args__ = (
        UniqueConstraint("bom_id", "item_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("component_type IN ('RAW_MATERIAL', 'PACKAGING')", name="component_not_finished_good"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    component_type: Mapped[ItemType] = mapped_column(enum_col(ItemType), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)  # per batch, in unit_id
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    bom: Mapped[Bom] = relationship(back_populates="items")
