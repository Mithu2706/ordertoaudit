"""Decimal precision policy, in one place. All rounding is ROUND_HALF_UP (commercial rounding).

    money(Decimal("187.499"))  -> 187.50
    qty(Decimal("10.5"))       -> 10.5000
"""
from decimal import ROUND_HALF_UP, Decimal

MONEY_STEP = Decimal("0.01")    # paise          NUMERIC(14,2)
QTY_STEP = Decimal("0.0001")    # quantities     NUMERIC(16,4)
RATE_STEP = Decimal("0.000001")  # unit costs     NUMERIC(18,6)
PCT_STEP = Decimal("0.0001")    # percentages    NUMERIC(9,4)


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def qty(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(QTY_STEP, rounding=ROUND_HALF_UP)


def rate(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(RATE_STEP, rounding=ROUND_HALF_UP)


def pct(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(PCT_STEP, rounding=ROUND_HALF_UP)
