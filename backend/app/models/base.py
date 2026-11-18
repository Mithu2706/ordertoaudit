"""Declarative base, shared column types and mixins."""
import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names -> stable Alembic migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---- Decimal column types (never float for money or stock) -----------------
def Money() -> Numeric:  # noqa: N802 - reads like a type
    """Rupee amounts, 2 decimal places (paise)."""
    return Numeric(14, 2, asdecimal=True)


def Qty() -> Numeric:  # noqa: N802
    """Stock quantities in an item's unit, 4 decimal places."""
    return Numeric(16, 4, asdecimal=True)


def Rate() -> Numeric:  # noqa: N802
    """Unit costs / conversion factors; weighted average needs extra precision."""
    return Numeric(18, 6, asdecimal=True)


def Pct() -> Numeric:  # noqa: N802
    """Percentages such as GST rate or variance %."""
    return Numeric(9, 4, asdecimal=True)


JSONType = JSON().with_variant(JSONB(), "postgresql")


def enum_col(enum_cls: type[enum.Enum]) -> Enum:
    """Store enums as VARCHAR + CHECK (portable, easy to extend via migration)."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        validate_strings=True,
        create_constraint=True,
        name=enum_cls.__name__.lower(),
        values_callable=lambda e: [m.value for m in e],
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
