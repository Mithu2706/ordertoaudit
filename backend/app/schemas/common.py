"""Reusable Pydantic field types and base classes."""
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.core import decimals as dec

T = TypeVar("T")


class Schema(BaseModel):
    """Base for request bodies: unknown fields are rejected, strings trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OutSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def _upper(v: str) -> str:
    return v.upper()


Code = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-/]*$"),
    AfterValidator(_upper),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
StateCode = Annotated[str, StringConstraints(pattern=r"^[0-9]{2}$")]
Gstin = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=15, max_length=15)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9+\- ]{6,20}$")]
Pincode = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{5}$")]
HsnCode = Annotated[str, StringConstraints(pattern=r"^([0-9]{4}|[0-9]{6}|[0-9]{8})$")]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]

# Decimal types mirror the DB precision. Input with MORE decimals than allowed is
# rejected (never silently rounded); valid input is normalised to the column scale
# so "50" is stored and returned as "50.00" on every database.
MoneyIn = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2), AfterValidator(dec.money)]
QtyIn = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=4), AfterValidator(dec.qty)]
PositiveQty = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=4), AfterValidator(dec.qty)]
RateIn = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6), AfterValidator(dec.rate)]
PositiveFactor = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6), AfterValidator(dec.rate)]
GstRate = Annotated[Decimal, Field(ge=0, le=28, max_digits=9, decimal_places=4), AfterValidator(dec.pct)]
