"""Pure variance and standard-quantity maths (no database), easy to unit test.

Consumption variance % = (actual - planned) / planned x 100
Yield variance %       = (actual output - expected output) / expected output x 100
An alert is raised when |variance| is STRICTLY greater than the tolerance (default 3 %).
"""
from decimal import ROUND_FLOOR, Decimal

from app.core import decimals as dec


def variance_pct(planned: Decimal, actual: Decimal) -> Decimal | None:
    """None when there is no standard to compare against (planned = 0)."""
    if planned == 0:
        return None
    return dec.pct((Decimal(actual) - Decimal(planned)) / Decimal(planned) * 100)


def is_alert(variance: Decimal | None, tolerance: Decimal, planned: Decimal, actual: Decimal) -> bool:
    if variance is None:  # nothing was planned: any usage at all is unexpected
        return planned == 0 and actual > 0
    return abs(variance) > tolerance


def packaging_standard(bom_qty_per_batch: Decimal, batch_output: Decimal, good_output: Decimal,
                       whole_units: bool) -> Decimal:
    """Standard packaging for the GOOD output actually produced.

    Packaging is consumed per packet packed, not per kg of dough, so its standard is
    scaled to good output (a yield shortfall is already measured by yield variance).
    Count packaging is rounded DOWN: a part-filled carton is not packed.
      pouches : 200 per 200 packets, 188 good -> 188
      cartons :  10 per 200 packets, 188 good -> 9.4 -> 9 (8 packets stay loose)
    """
    exact = Decimal(bom_qty_per_batch) * Decimal(good_output) / Decimal(batch_output)
    if whole_units:
        exact = exact.to_integral_value(rounding=ROUND_FLOOR)
    return dec.qty(exact)
