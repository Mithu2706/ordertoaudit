"""Benchmark master data + opening stock (the assignment's mandatory scenario).

Everything is created through the normal services, so it is validated, audit-logged
and posted to the stock ledger exactly as if a user had entered it.

Assumption (documented): the 50 opening packets of Murukku have no cost in the brief.
They are valued at the BOM standard cost at opening rates, including the stated
labour and gas/power for a batch:
  flour 40x42 + oil 10x140 + spice 1.2x200 + pouch 200x2.50 + carton 10x15 = 3,970.00
  + labour 1,200 + gas/power 600 = 5,770.00 / 200 packets = Rs 28.85 per packet
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.gstin import gstin_check_char
from app.models import Customer, Item, Supplier, User
from app.models.enums import CustomerType, ItemType, PackagingKind
from app.schemas.items import PackagingMaterialCreate, ProductCreate, RawMaterialCreate
from app.schemas.parties import CustomerCreate, SupplierCreate
from app.schemas.production import BomIn, BomLineIn
from app.schemas.reference import UnitConversionCreate
from app.services import bom as bom_svc
from app.services import inventory, items, parties, reference

D = Decimal
FG_OPENING_UNIT_COST = D("28.85")


def gstin(first14: str) -> str:
    return first14 + gstin_check_char(first14)


@dataclass(frozen=True)
class OpeningLine:
    code: str
    quantity: Decimal
    unit: str
    unit_cost: Decimal


RAW = [
    RawMaterialCreate(code="RM-FLOUR", name="Flour (rice + urad blend)", base_unit_code="KG",
                      standard_cost=D("42"), reorder_level=D("50"), category="Flour"),
    RawMaterialCreate(code="RM-OIL", name="Cooking oil", base_unit_code="L",
                      standard_cost=D("140"), reorder_level=D("15"), category="Oil"),
    RawMaterialCreate(code="RM-SPICE", name="Salt and spice mix", base_unit_code="KG",
                      standard_cost=D("200"), reorder_level=D("2"), category="Spices"),
]
PACKAGING = [
    PackagingMaterialCreate(code="PM-POUCH200", name="200 g printed pouch", base_unit_code="PCS",
                            standard_cost=D("2.50"), reorder_level=D("250"), packaging_kind=PackagingKind.POUCH),
    PackagingMaterialCreate(code="PM-CARTON", name="Shipper carton (20 packets)", base_unit_code="PCS",
                            standard_cost=D("15"), reorder_level=D("15"), packaging_kind=PackagingKind.CARTON),
]
PRODUCT = ProductCreate(code="FG-MUR200", name="Murukku 200 g", base_unit_code="PKT", hsn_code="21069099",
                        gst_rate=D("5"), selling_price=D("50"), net_weight_g=D("200"), reorder_level=D("100"))

OPENING = [
    OpeningLine("RM-FLOUR", D("100"), "KG", D("42")),
    OpeningLine("RM-OIL", D("30"), "L", D("140")),
    OpeningLine("RM-SPICE", D("5"), "KG", D("200")),
    OpeningLine("PM-POUCH200", D("500"), "PCS", D("2.50")),
    OpeningLine("PM-CARTON", D("30"), "PCS", D("15")),
    OpeningLine("FG-MUR200", D("50"), "PKT", FG_OPENING_UNIT_COST),
]

# BOM per batch of 200 packets.
BOM_LINES = [("RM-FLOUR", "40", "KG"), ("RM-OIL", "10", "L"), ("RM-SPICE", "1.2", "KG"),
             ("PM-POUCH200", "200", "PCS"), ("PM-CARTON", "10", "PCS")]

SUPPLIERS = [
    SupplierCreate(code="SUP-FLOUR", name="Kovai Flour Mills", state_code="33",
                   gstin=gstin("33AABCK1111F1Z"), phone="0422-2111111"),
    SupplierCreate(code="SUP-OIL", name="Erode Oil Traders", state_code="33", gstin=gstin("33AABCE2222G1Z")),
    SupplierCreate(code="SUP-PACK", name="Bengaluru Flexi Packs", state_code="29", gstin=gstin("29AABCB3333H1Z")),
]


def _code_exists(db: Session, code: str) -> bool:
    return db.scalars(select(Item.id).where(Item.code == code)).first() is not None


def seed_benchmark(db: Session, opening_date: date | None = None) -> dict[str, int]:
    """Idempotent: does nothing if the benchmark product already exists. Returns item ids."""
    if _code_exists(db, PRODUCT.code):
        return {i.code: i.id for i in db.scalars(select(Item))}

    admin = db.scalars(select(User).where(User.username == "admin")).first()
    if admin is None:
        raise RuntimeError("Run the reference seed (demo users) first")
    opening_date = opening_date or date.today().replace(day=1)

    for s in SUPPLIERS:
        if db.scalars(select(Supplier.id).where(Supplier.code == s.code)).first() is None:
            parties.create_supplier(db, s, admin)
    for data in RAW:
        items.create_item(db, ItemType.RAW_MATERIAL, data, admin)
    for data in PACKAGING:
        items.create_item(db, ItemType.PACKAGING, data, admin)
    product = items.create_item(db, ItemType.FINISHED_GOOD, PRODUCT, admin)
    ids = {i.code: i.id for i in db.scalars(select(Item))}

    # 1 carton = 20 packets of Murukku (10 cartons per 200-packet batch).
    reference.create_conversion(db, UnitConversionCreate(from_unit_code="CTN", to_unit_code="PKT",
                                                         factor=D("20"), item_id=product.item_id), admin)

    salesmen = {u.username: u.id for u in db.scalars(select(User).where(User.username.in_(["salesman_a", "salesman_b"])))}
    customers = [
        CustomerCreate(code="RET-A", name="Retailer A (Sri Murugan Stores)", customer_type=CustomerType.RETAILER,
                       gstin=gstin("33AAFCR5678K1Z"), state_code="33", address="45 Big Bazaar Street, Coimbatore",
                       city="Coimbatore", pincode="641001", credit_limit=D("25000"), credit_days=30,
                       assigned_salesman_id=salesmen.get("salesman_a")),
        CustomerCreate(code="DIST-B", name="Distributor B (Karnataka Foods)", customer_type=CustomerType.DISTRIBUTOR,
                       gstin=gstin("29AAGCD4321P1Z"), state_code="29", address="12 KR Market Road, Bengaluru",
                       city="Bengaluru", pincode="560002", credit_limit=D("100000"), credit_days=45,
                       assigned_salesman_id=salesmen.get("salesman_b")),
    ]
    for c in customers:
        if db.scalars(select(Customer.id).where(Customer.code == c.code)).first() is None:
            parties.create_customer(db, c, admin)

    for line in OPENING:
        inventory.post_opening_stock(db, item_id=ids[line.code], quantity=line.quantity, unit_code=line.unit,
                                     unit_cost=line.unit_cost, movement_date=opening_date, actor=admin,
                                     remarks="Benchmark opening stock")

    bom_svc.create_bom(db, BomIn(
        product_id=product.item_id, batch_output_qty=D("200"), output_unit_code="PKT", activate=True,
        notes="Standard batch: 200 packets of 200 g",
        items=[BomLineIn(item_id=ids[c], quantity=D(q), unit_code=u) for c, q, u in BOM_LINES],
    ), admin)
    db.flush()
    return ids
