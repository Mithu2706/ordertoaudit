"""Re-run the mandatory benchmark scenario against a database, through the real services.

    python -m app.seed.scenario              # all 9 steps, then print results vs expected
    python -m app.seed.scenario --until 3    # stop after production (handy for a live demo)

Run on a fresh database after `alembic upgrade head`. It seeds reference data, demo users
and benchmark masters itself. Every step goes through the same services the API uses, so it
is validated, audited and posted to the ledger exactly like clicks in the UI.
"""
import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Customer, Item, ProductionRun, SalesOrder, Supplier, User
from app.models.enums import OrderStatus, PaymentMode
from app.schemas.production import ActualLineIn, ProductionActualsIn, ProductionRunCreate
from app.schemas.purchases import PurchaseIn, PurchaseLineIn
from app.schemas.sales import ApproveIn, OrderIn, OrderLineIn
from app.seed.benchmark import seed_benchmark
from app.seed.reference_data import seed_demo_users, seed_reference
from app.services import dispatch, inventory, invoicing, payments, production, purchases, sales
from app.services.availability import availability, check_order
from app.services.costing import run_costing
from app.services.invoicing import invoice_balance

D = Decimal


def run(db: Session, until: int = 9, today: date | None = None) -> dict:
    today = today or date.today()
    opening = today - timedelta(days=3) if today.day <= 3 else today.replace(day=1)
    seed_reference(db)
    seed_demo_users(db)
    ids = seed_benchmark(db, opening_date=opening)
    users = {u.username: u for u in db.scalars(select(User))}
    cust = {c.code: c for c in db.scalars(select(Customer))}
    admin, prod = users["admin"], users["production"]
    out: dict = {}

    if db.scalars(select(ProductionRun)).first() is not None:
        raise SystemExit("This database already contains scenario activity; use a fresh database.")

    # STEP 1: purchase 60 kg flour at Rs 45
    sup = db.scalars(select(Supplier).where(Supplier.code == "SUP-FLOUR")).one()
    p = purchases.create_purchase(db, PurchaseIn(
        supplier_id=sup.id, supplier_invoice_no="KFM-001", supplier_invoice_date=opening, received_date=opening,
        items=[PurchaseLineIn(item_id=ids["RM-FLOUR"], quantity=D("60"), unit_code="KG", rate=D("45"))]), admin)
    purchases.post_purchase(db, p.id, admin)
    if until < 2:
        return out

    # STEPS 2-3: production run, issues and output (labour + gas recorded with the actuals)
    run_ = production.create_run(db, ProductionRunCreate(product_id=ids["FG-MUR200"], production_date=opening), prod)
    lines = [("RM-FLOUR", "40", "0"), ("RM-OIL", "10.5", "0"), ("RM-SPICE", "1.2", "0"),
             ("PM-POUCH200", "188", "6"), ("PM-CARTON", "9", "0")]
    production.record_actuals(db, run_.id, ProductionActualsIn(
        consumption=[ActualLineIn(item_id=ids[c], actual_quantity=D(q), damaged_quantity=D(d)) for c, q, d in lines],
        actual_good_output=D("188"), labour_cost=D("1200"), power_gas_cost=D("600")), prod)
    production.post_run(db, run_.id, prod)
    if until < 4:
        return out

    def order(salesman: str, customer: str, q: str) -> SalesOrder:
        o = sales.create_order(db, OrderIn(customer_id=cust[customer].id,
                                           items=[OrderLineIn(product_id=ids["FG-MUR200"], quantity=D(q))]), users[salesman])
        return sales.submit_order(db, o.id, users[salesman])

    # STEP 4: Salesman A, Retailer A (TN), 150 packets
    order_a = order("salesman_a", "RET-A", "150")
    if until < 5:
        return out
    # STEP 5: approve, GST invoice (CGST+SGST), dispatch
    sales.approve_order(db, order_a.id, ApproveIn(version=order_a.version), admin)
    inv_a = invoicing.create_invoice(db, order_a.id, None, admin)
    dispatch.create_dispatch(db, order_id=order_a.id, lines=None, dispatch_date=None, vehicle_no="TN37 AB 1234",
                             transporter="Kovai Roadways", remarks=None, actor=admin)
    out["invoice_a"] = inv_a
    if until < 6:
        return out
    # STEP 6: Salesman B, Distributor B (KA), 120 packets: left pending, shortage flagged
    out["order_b"] = order("salesman_b", "DIST-B", "120")
    if until < 7:
        return out
    # STEP 7: Rs 4,000 from Retailer A
    payments.record_payment(db, customer_id=cust["RET-A"].id, payment_date=today, amount=D("4000"),
                            mode=PaymentMode.UPI, reference_no="UTR-RETA-001", remarks="Benchmark step 7",
                            allocations=None, actor=admin)
    return out


def results(db: Session) -> list[tuple[str, str, str]]:
    """(check, expected, actual) for the benchmark table."""
    item = {i.code: i.id for i in db.scalars(select(Item))}
    q = lambda v: f"{v.normalize():f}"  # noqa: E731  (120.0000 -> '120', never '1.2E+2')
    bal = lambda code: q(inventory.current_balance(db, item[code]).quantity)  # noqa: E731
    run_ = db.scalars(select(ProductionRun)).first()
    oil = next((c for c in run_.consumption if c.item_id == item["RM-OIL"]), None) if run_ else None
    from app.models import Invoice
    inv_a = db.scalars(select(Invoice).order_by(Invoice.id)).first()
    order_b = db.scalars(select(SalesOrder).where(SalesOrder.status == OrderStatus.SUBMITTED)).first()
    short = next((c.shortage for c in check_order(db, order_b)), None) if order_b else None
    costing = run_costing(db, run_) if run_ else None
    fg_after_prod = q(inventory.current_balance(db, item["FG-MUR200"]).quantity
                      + sum((li.quantity_dispatched for o in db.scalars(select(SalesOrder)) for li in o.items), D(0)))
    return [
        ("Flour closing stock", "120 kg", f"{bal('RM-FLOUR')} kg"),
        ("Oil closing stock", "19.5 L", f"{bal('RM-OIL')} L"),
        ("Pouch closing stock", "306", f"{bal('PM-POUCH200')}"),
        ("Carton closing stock", "21", f"{bal('PM-CARTON')}"),
        ("Finished goods after production", "238 packets", f"{fg_after_prod} packets"),
        ("Finished goods after Retailer A dispatch", "88 packets", f"{bal('FG-MUR200')} packets"),
        ("Yield variance", "-6%", f"{q(run_.yield_variance_pct)}%" if run_ else "-"),
        ("Oil consumption variance", "+5%", f"+{q(oil.variance_pct)}%" if oil else "-"),
        ("Retailer A taxable value", "7500.00", f"{inv_a.taxable_amount}" if inv_a else "-"),
        ("CGST", "187.50", f"{inv_a.cgst_amount}" if inv_a else "-"),
        ("SGST", "187.50", f"{inv_a.sgst_amount}" if inv_a else "-"),
        ("Invoice total", "7875.00", f"{inv_a.total_amount}" if inv_a else "-"),
        ("Retailer A outstanding", "3875.00", f"{invoice_balance(db, inv_a)}" if inv_a else "-"),
        ("Distributor B shortage", "32 packets", f"{q(short)} packets" if short is not None else "-"),
        ("Cost per good packet", "(5,855 / 188)", f"{costing.cost_per_unit}" if costing else "-"),
        ("Gross margin", "(vs Rs 50)", f"{costing.margin_pct}%" if costing else "-"),
        ("FG available for sale", "88", q(availability(db, item['FG-MUR200']).available)),
    ]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--until", type=int, default=9, choices=range(1, 10), help="last benchmark step to run")
    args = ap.parse_args(argv)
    with SessionLocal.begin() as db:
        run(db, args.until)
    print(f"Benchmark scenario executed through step {args.until}.")
    if args.until >= 7:
        with SessionLocal() as db:
            width = max(len(r[0]) for r in results(db))
            print(f"\n{'Check':<{width}}  {'Expected':>14}  {'Actual':>16}")
            for check, exp, act in results(db):
                print(f"{check:<{width}}  {exp:>14}  {act:>16}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
