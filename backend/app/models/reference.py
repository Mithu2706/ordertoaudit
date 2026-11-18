"""Reference/config data: GST states, units, conversions, company, settings, numbering."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Rate, TimestampMixin, enum_col
from app.models.enums import DocumentType, UnitDimension


class State(Base):
    """Indian states/UTs keyed by GST state code (e.g. '33' Tamil Nadu, '29' Karnataka)."""

    __tablename__ = "states"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_union_territory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # KG, G, L, ML, PCS, PKT, CTN
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    dimension: Mapped[UnitDimension] = mapped_column(enum_col(UnitDimension), nullable=False)


class UnitConversion(Base):
    """1 from_unit = factor x to_unit.

    item_id NULL  -> global conversion (1 KG = 1000 G).
    item_id set   -> item-specific packing (1 CTN of Murukku = 20 PKT).
    """

    __tablename__ = "unit_conversions"
    __table_args__ = (
        CheckConstraint("factor > 0", name="factor_positive"),
        CheckConstraint("from_unit_id <> to_unit_id", name="distinct_units"),
        # Partial unique indexes: NULLs are distinct in a normal UNIQUE constraint.
        Index(
            "uq_unit_conversions_global",
            "from_unit_id",
            "to_unit_id",
            unique=True,
            postgresql_where=text("item_id IS NULL"),
            sqlite_where=text("item_id IS NULL"),
        ),
        Index(
            "uq_unit_conversions_item",
            "from_unit_id",
            "to_unit_id",
            "item_id",
            unique=True,
            postgresql_where=text("item_id IS NOT NULL"),
            sqlite_where=text("item_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    to_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    factor: Mapped[Decimal] = mapped_column(Rate(), nullable=False)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)


class CompanyProfile(TimestampMixin, Base):
    """Single-row table with the manufacturer's legal / GST identity."""

    __tablename__ = "company_profile"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    legal_name: Mapped[str] = mapped_column(String(128), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(128))
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    state_code: Mapped[str] = mapped_column(ForeignKey("states.code"), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    fy_start_month: Mapped[int] = mapped_column(Integer, default=4, nullable=False)  # April


class AppSetting(Base):
    """Configurable business parameters, e.g. variance_tolerance_pct = 3."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentSequence(Base):
    """Gap-free numbering per document type and financial year (row is locked when used)."""

    __tablename__ = "document_sequences"
    __table_args__ = (
        UniqueConstraint("doc_type", "financial_year"),
        CheckConstraint("last_number >= 0", name="last_number_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_type: Mapped[DocumentType] = mapped_column(enum_col(DocumentType), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(7), nullable=False)  # '2026-27'
    prefix: Mapped[str] = mapped_column(String(10), nullable=False)  # 'INV'
    last_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
