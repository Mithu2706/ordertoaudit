"""Production runs, planned vs actual consumption, and costing results."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, Pct, Qty, Rate, TimestampMixin, enum_col
from app.models.enums import DocumentStatus, ItemType


class ProductionRun(TimestampMixin, Base):
    __tablename__ = "production_runs"
    __table_args__ = (
        CheckConstraint("batch_count > 0", name="batch_count_positive"),
        CheckConstraint("expected_output > 0", name="expected_output_positive"),
        CheckConstraint("actual_good_output IS NULL OR actual_good_output >= 0", name="good_output_non_negative"),
        CheckConstraint("damaged_output >= 0", name="damaged_output_non_negative"),
        CheckConstraint("wastage_qty >= 0", name="wastage_non_negative"),
        CheckConstraint("labour_cost >= 0 AND power_gas_cost >= 0", name="overheads_non_negative"),
        # A posted run must carry its actual output.
        CheckConstraint("status <> 'POSTED' OR actual_good_output IS NOT NULL", name="posted_has_output"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.item_id"), nullable=False, index=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id"), nullable=False)
    production_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[DocumentStatus] = mapped_column(enum_col(DocumentStatus), nullable=False)

    batch_count: Mapped[Decimal] = mapped_column(Qty(), nullable=False)
    expected_output: Mapped[Decimal] = mapped_column(Qty(), nullable=False)  # bom yield x batches
    actual_good_output: Mapped[Decimal | None] = mapped_column(Qty())  # saleable -> FG stock
    damaged_output: Mapped[Decimal] = mapped_column(Qty(), default=Decimal("0"), nullable=False)  # never stocked
    wastage_qty: Mapped[Decimal] = mapped_column(Qty(), default=Decimal("0"), nullable=False)
    wastage_unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"))

    labour_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    power_gas_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    # Filled on posting.
    material_cost: Mapped[Decimal | None] = mapped_column(Money())
    packaging_cost: Mapped[Decimal | None] = mapped_column(Money())
    total_cost: Mapped[Decimal | None] = mapped_column(Money())
    cost_per_good_unit: Mapped[Decimal | None] = mapped_column(Rate())

    yield_variance_pct: Mapped[Decimal | None] = mapped_column(Pct())
    variance_tolerance_pct: Mapped[Decimal] = mapped_column(Pct(), nullable=False)  # snapshot of setting
    has_variance_alert: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    remarks: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    consumption: Mapped[list["ProductionConsumption"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ProductionConsumption(Base):
    """One row per BOM component: planned (from BOM) vs actual (entered)."""

    __tablename__ = "production_consumption"
    __table_args__ = (
        UniqueConstraint("run_id", "item_id"),
        CheckConstraint("planned_quantity >= 0", name="planned_non_negative"),
        CheckConstraint("actual_quantity IS NULL OR actual_quantity >= 0", name="actual_non_negative"),
        CheckConstraint("damaged_quantity >= 0", name="damaged_non_negative"),
        CheckConstraint("component_type IN ('RAW_MATERIAL', 'PACKAGING')", name="component_not_finished_good"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False, index=True)
    component_type: Mapped[ItemType] = mapped_column(enum_col(ItemType), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)  # item base unit
    planned_quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)
    # Used in good production (packaging: pouches filled / cartons packed).
    actual_quantity: Mapped[Decimal | None] = mapped_column(Qty())
    # Packaging spoiled during packing (benchmark: 6 pouches). Posted as DAMAGE.
    damaged_quantity: Mapped[Decimal] = mapped_column(Qty(), default=Decimal("0"), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Rate())  # weighted average at posting
    total_cost: Mapped[Decimal | None] = mapped_column(Money())
    variance_pct: Mapped[Decimal | None] = mapped_column(Pct())  # (actual+damaged-planned)/planned
    is_variance_alert: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped[ProductionRun] = relationship(back_populates="consumption")
