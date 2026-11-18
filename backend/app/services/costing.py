"""Product costing for a posted production run.

Cost elements (all stored on the run at posting, from the ledger's weighted-average values):
    material  = raw-material issues
    packaging = packaging issues + damaged packaging
    labour, power & gas = entered with the run's actuals
    total / good output = cost per good packet

Gross margin is measured against the product's selling price (before GST):
    margin per unit = selling price - cost per good unit
    margin %        = margin per unit / selling price x 100
Benchmark: 5,855.00 / 188 = 31.143617 -> margin 18.856383 = 37.7128 %
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.models import Product, ProductionRun
from app.models.enums import DocumentStatus


@dataclass(frozen=True)
class RunCosting:
    material: Decimal
    packaging: Decimal
    labour: Decimal
    power_gas: Decimal
    total: Decimal
    good_output: Decimal
    cost_per_unit: Decimal | None
    selling_price: Decimal
    margin_per_unit: Decimal | None
    margin_pct: Decimal | None


def run_costing(db: Session, run: ProductionRun) -> RunCosting | None:
    if run.status != DocumentStatus.POSTED:
        return None
    price = Decimal(db.get(Product, run.product_id).selling_price)
    cpu = run.cost_per_good_unit
    margin = dec.rate(price - cpu) if cpu is not None else None
    pct = dec.pct(margin / price * 100) if margin is not None and price > 0 else None
    return RunCosting(run.material_cost, run.packaging_cost, run.labour_cost, run.power_gas_cost, run.total_cost,
                      run.actual_good_output, cpu, price, margin, pct)
