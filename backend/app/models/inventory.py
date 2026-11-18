"""Append-only stock ledger. Stock balances are DERIVED from these rows.

Invariants (enforced by the DB, not just the service):
  * quantity sign matches movement type            -> ck_stock_movements_sign_matches_type
  * running balance can never go negative          -> ck_stock_movements_balance_non_negative
  * one document line is posted at most once       -> unique posting_key
  * rows are never updated/deleted (PostgreSQL trigger added in the migration)
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, Qty, Rate, enum_col
from app.models.enums import MovementType

_IN = "'OPENING','PURCHASE_RECEIPT','PRODUCTION_OUTPUT','SALES_RETURN'"
_OUT = "'PRODUCTION_ISSUE','SALES_DISPATCH','DAMAGE','PURCHASE_RETURN'"


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            f"(movement_type IN ({_IN}) AND quantity > 0)"
            f" OR (movement_type IN ({_OUT}) AND quantity < 0)"
            " OR (movement_type = 'ADJUSTMENT' AND quantity <> 0)",
            name="sign_matches_type",
        ),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
        CheckConstraint("value_after >= 0", name="value_non_negative"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),
        Index("ix_stock_movements_item_seq", "item_id", "id"),
        Index("ix_stock_movements_source", "source_document_type", "source_document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(enum_col(MovementType), nullable=False, index=True)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # business date

    # Signed quantity in the item's base unit (+ in, - out).
    quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    # What the user actually typed, for traceability (e.g. 10.5 L, 1 CTN).
    entered_quantity: Mapped[Decimal] = mapped_column(Qty(), nullable=False)
    entered_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)

    # Valuation (weighted average).
    unit_cost: Mapped[Decimal] = mapped_column(Rate(), nullable=False)  # per base unit
    value: Mapped[Decimal] = mapped_column(Money(), nullable=False)  # signed
    balance_after: Mapped[Decimal] = mapped_column(Qty(), nullable=False)
    value_after: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    # Traceability to the originating document.
    source_document_type: Mapped[str] = mapped_column(String(32), nullable=False)  # PURCHASE, PRODUCTION_RUN...
    source_document_id: Mapped[int | None]
    reference_no: Mapped[str] = mapped_column(String(64), nullable=False)  # PUR/2026-27/00001
    posting_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)  # idempotency
    remarks: Mapped[str | None] = mapped_column(String(255))

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
