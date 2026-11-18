"""Benchmark scenario steps driven through the services (reused by later-phase tests)."""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Supplier, User
from app.schemas.production import ActualLineIn, ProductionActualsIn, ProductionRunCreate
from app.schemas.purchases import PurchaseIn, PurchaseLineIn
from app.seed.benchmark import seed_benchmark
from app.seed.reference_data import seed_demo_users
from app.services import production, purchases
from tests.factories import days_ago

D = Decimal


@dataclass
class Bench:
    ids: dict[str, int]
    users: dict[str, User]
    customers: dict[str, Customer]


def setup(db: Session) -> Bench:
    seed_demo_users(db, password="Demo@1234")
    ids = seed_benchmark(db, opening_date=days_ago(10))
    users = {u.username: u for u in db.scalars(select(User))}
    customers = {c.code: c for c in db.scalars(select(Customer))}
    return Bench(ids, users, customers)


def step1_purchase(db: Session, b: Bench) -> None:
    sup = db.scalars(select(Supplier).where(Supplier.code == "SUP-FLOUR")).one()
    p = purchases.create_purchase(db, PurchaseIn(
        supplier_id=sup.id, supplier_invoice_no="KFM-001", supplier_invoice_date=days_ago(8),
        received_date=days_ago(8),
        items=[PurchaseLineIn(item_id=b.ids["RM-FLOUR"], quantity=D("60"), unit_code="KG", rate=D("45"))],
    ), b.users["admin"])
    purchases.post_purchase(db, p.id, b.users["admin"])


def steps2_3_production(db: Session, b: Bench):
    prod = b.users["production"]
    run = production.create_run(db, ProductionRunCreate(product_id=b.ids["FG-MUR200"],
                                                        production_date=days_ago(7)), prod)
    lines = [("RM-FLOUR", "40", "0"), ("RM-OIL", "10.5", "0"), ("RM-SPICE", "1.2", "0"),
             ("PM-POUCH200", "188", "6"), ("PM-CARTON", "9", "0")]
    production.record_actuals(db, run.id, ProductionActualsIn(
        consumption=[ActualLineIn(item_id=b.ids[c], actual_quantity=D(q), damaged_quantity=D(d)) for c, q, d in lines],
        actual_good_output=D("188"), labour_cost=D("1200"), power_gas_cost=D("600"),
    ), prod)
    return production.post_run(db, run.id, prod)


def through_step3(db: Session) -> Bench:
    b = setup(db)
    step1_purchase(db, b)
    steps2_3_production(db, b)
    return b


def place_order(db: Session, b: Bench, salesman: str, customer: str, qty: str, submit: bool = True):
    from app.schemas.sales import OrderIn, OrderLineIn
    from app.services import sales
    user = b.users[salesman]
    order = sales.create_order(db, OrderIn(customer_id=b.customers[customer].id,
                                           items=[OrderLineIn(product_id=b.ids["FG-MUR200"], quantity=D(qty))]), user)
    if submit:
        sales.submit_order(db, order.id, user)
    return order


def approve(db: Session, b: Bench, order, qty: str | None = None):
    from app.schemas.sales import ApprovalLineIn, ApproveIn
    from app.services import sales
    lines = [ApprovalLineIn(order_item_id=order.items[0].id, quantity_approved=D(qty))] if qty else []
    return sales.approve_order(db, order.id, ApproveIn(version=order.version, lines=lines,
                                                       reason="Partial: stock limited" if qty else None),
                               b.users["admin"])


def step4_5_order_a(db: Session, b: Bench):
    """Retailer A, 150 packets, approved (not yet invoiced)."""
    return approve(db, b, place_order(db, b, "salesman_a", "RET-A", "150"))


def through_step7(db: Session) -> Bench:
    """Steps 1-7: production posted; Retailer A approved, invoiced, dispatched, paid 4,000;
    Distributor B's 120-packet order submitted and left pending (short by 32)."""
    from datetime import date

    from app.models.enums import PaymentMode
    from app.services import dispatch, invoicing, payments
    b = through_step3(db)
    admin = b.users["admin"]
    order_a = step4_5_order_a(db, b)
    invoicing.create_invoice(db, order_a.id, None, admin)
    dispatch.create_dispatch(db, order_id=order_a.id, lines=None, dispatch_date=None, vehicle_no="TN37 AB 1234",
                             transporter=None, remarks=None, actor=admin)
    place_order(db, b, "salesman_b", "DIST-B", "120")
    payments.record_payment(db, customer_id=b.customers["RET-A"].id, payment_date=date.today(), amount=D("4000"),
                            mode=PaymentMode.UPI, reference_no="UTR-1", remarks=None, allocations=None, actor=admin)
    return b
