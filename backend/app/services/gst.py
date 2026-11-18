"""GST calculation (pure functions, no database). Used by order previews and invoices.

Place-of-supply rule for goods (simplified for this exercise):
  supplier state == place of supply (customer state)  -> intra-state: CGST + SGST, each = rate / 2
  otherwise                                           -> inter-state: IGST = rate
Tax is computed per line and rounded half-up to the paisa; CGST and SGST are each
rounded separately (so their sum is always exactly what is shown on the invoice).
The exercise uses a flat 5 % rate; the rate comes from the product master, so it is
configurable per product.
"""
from dataclasses import dataclass
from decimal import Decimal

from app.core import decimals as dec
from app.models.enums import SupplyType

ZERO = Decimal("0.00")


def supply_type(supplier_state: str, place_of_supply: str) -> SupplyType:
    return SupplyType.INTRA_STATE if supplier_state == place_of_supply else SupplyType.INTER_STATE


@dataclass(frozen=True)
class LineTax:
    taxable: Decimal
    gst_rate: Decimal
    cgst_rate: Decimal
    cgst: Decimal
    sgst_rate: Decimal
    sgst: Decimal
    igst_rate: Decimal
    igst: Decimal

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst

    @property
    def total(self) -> Decimal:
        return self.taxable + self.tax


def line_tax(quantity: Decimal, unit_price: Decimal, gst_rate: Decimal, kind: SupplyType) -> LineTax:
    taxable = dec.money(Decimal(quantity) * Decimal(unit_price))
    rate = Decimal(gst_rate)
    if kind == SupplyType.INTRA_STATE:
        half = dec.pct(rate / 2)
        part = dec.money(taxable * half / 100)
        return LineTax(taxable, dec.pct(rate), half, part, half, part, dec.pct(0), ZERO)
    return LineTax(taxable, dec.pct(rate), dec.pct(0), ZERO, dec.pct(0), ZERO, dec.pct(rate),
                   dec.money(taxable * rate / 100))


@dataclass(frozen=True)
class TaxTotals:
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal

    @property
    def total(self) -> Decimal:
        return self.taxable + self.cgst + self.sgst + self.igst


def totals(lines: list[LineTax]) -> TaxTotals:
    return TaxTotals(
        taxable=sum((x.taxable for x in lines), ZERO),
        cgst=sum((x.cgst for x in lines), ZERO),
        sgst=sum((x.sgst for x in lines), ZERO),
        igst=sum((x.igst for x in lines), ZERO),
    )
