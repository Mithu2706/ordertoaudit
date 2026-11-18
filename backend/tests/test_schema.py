"""Phase 1: the database schema itself enforces the critical invariants.

These tests deliberately bypass the (future) service layer and write rows directly,
proving the database rejects bad data even if application code has a bug.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Bom,
    Customer,
    Invoice,
    Item,
    Product,
    Role,
    SalesOrder,
    State,
    StockMovement,
    Unit,
    UnitConversion,
    User,
)
from app.models.enums import (
    CustomerType,
    InvoiceStatus,
    ItemType,
    MovementType,
    OrderStatus,
    RoleCode,
    SupplyType,

)

EXPECTED_TABLES = {
    "users", "roles", "customers", "products", "suppliers", "raw_materials", "packaging_materials",
    "units", "unit_conversions", "boms", "bom_items", "purchases", "purchase_items", "sales_orders",
    "sales_order_items", "invoices", "invoice_items", "dispatches", "production_runs",
    "production_consumption", "stock_movements", "payments", "credit_notes", "audit_logs",
}


@pytest.fixture
def ref(db: Session) -> dict:
    """Rows needed by the constraint tests (roles, states, units come from the seed)."""
    role = db.scalars(select(Role).where(Role.code == RoleCode.ADMIN)).one()
    user = User(username="schema_admin", full_name="Admin", password_hash="x", role_id=role.id)
    db.add(user)
    db.flush()
    tn = db.get(State, "33")
    kg, g, pkt, ctn = (db.scalars(select(Unit).where(Unit.code == c)).one() for c in ("KG", "G", "PKT", "CTN"))
    flour = Item(code="RM-FLOUR", name="Flour", item_type=ItemType.RAW_MATERIAL, base_unit_id=kg.id)
    fg = Item(code="FG-MUR200", name="Murukku 200 g", item_type=ItemType.FINISHED_GOOD, base_unit_id=pkt.id)
    db.add_all([flour, fg])
    db.flush()
    db.add(Product(item_id=fg.id, hsn_code="2106", gst_rate=Decimal("5"), selling_price=Decimal("50.00")))
    db.flush()
    return {"user": user, "kg": kg, "g": g, "pkt": pkt, "ctn": ctn, "flour": flour, "fg": fg, "tn": tn}


def _movement(ref: dict, *, qty: str, balance: str, key: str, mtype=MovementType.OPENING) -> StockMovement:
    q = Decimal(qty)
    return StockMovement(
        item_id=ref["flour"].id, movement_type=mtype, movement_date=date(2026, 11, 1),
        quantity=q, unit_id=ref["kg"].id, entered_quantity=abs(q), entered_unit_id=ref["kg"].id,
        unit_cost=Decimal("42"), value=q * 42, balance_after=Decimal(balance),
        value_after=max(Decimal(balance), Decimal(0)) * 42,
        source_document_type="TEST", source_document_id=1, reference_no="T-1",
        posting_key=key, created_by=ref["user"].id,
    )


def _expect_integrity_error(db: Session) -> None:
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_all_required_tables_exist(engine):
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_valid_movement_round_trips_decimals_exactly(db, ref):
    db.add(_movement(ref, qty="100", balance="100", key="OPEN:flour"))
    db.flush()
    m = db.scalars(select(StockMovement)).one()
    assert m.balance_after == Decimal("100.0000")
    assert m.value_after == Decimal("4200.00")
    assert isinstance(m.value_after, Decimal)


def test_negative_running_balance_is_rejected(db, ref):
    db.add(_movement(ref, qty="-5", balance="-5", key="ISSUE:1", mtype=MovementType.PRODUCTION_ISSUE))
    _expect_integrity_error(db)


def test_movement_sign_must_match_type(db, ref):
    # A production issue that *adds* stock is nonsense.
    db.add(_movement(ref, qty="5", balance="5", key="ISSUE:bad", mtype=MovementType.PRODUCTION_ISSUE))
    _expect_integrity_error(db)


def test_duplicate_posting_key_is_rejected(db, ref):
    db.add(_movement(ref, qty="100", balance="100", key="PUR:1:LINE:1"))
    db.flush()
    db.add(_movement(ref, qty="100", balance="200", key="PUR:1:LINE:1"))
    _expect_integrity_error(db)


def test_only_one_active_bom_per_product(db, ref):
    def bom(version: int, active: bool) -> Bom:
        return Bom(product_id=ref["fg"].id, version=version, batch_output_qty=Decimal("200"),
                   output_unit_id=ref["pkt"].id, is_active=active)

    db.add_all([bom(1, False), bom(2, True)])
    db.flush()  # inactive + active is fine
    db.add(bom(3, True))
    _expect_integrity_error(db)


def test_unit_conversion_global_and_item_specific(db, ref):
    # KG->G (global) is already seeded; an item-specific CTN->PKT is allowed alongside it.
    db.add(UnitConversion(from_unit_id=ref["ctn"].id, to_unit_id=ref["pkt"].id, factor=Decimal("20"),
                          item_id=ref["fg"].id))
    db.flush()
    db.add(UnitConversion(from_unit_id=ref["kg"].id, to_unit_id=ref["g"].id, factor=Decimal("1000")))
    _expect_integrity_error(db)


def _invoice(ref: dict, order_id: int, customer_id: int, **amounts) -> Invoice:
    base = dict(taxable_amount=Decimal("7500.00"), cgst_amount=Decimal("187.50"), sgst_amount=Decimal("187.50"),
                igst_amount=Decimal("0"), round_off=Decimal("0"), total_amount=Decimal("7875.00"))
    base.update(amounts)
    return Invoice(
        invoice_no=f"INV/2026-27/{order_id:05d}", financial_year="2026-27", sequence_no=order_id,
        invoice_date=date(2026, 11, 2), order_id=order_id, customer_id=customer_id,
        customer_name="Retailer A", billing_address="Chennai", place_of_supply_state_code="33",
        supplier_state_code="33", supply_type=SupplyType.INTRA_STATE, status=InvoiceStatus.ISSUED,
        created_by=ref["user"].id, **base,
    )


@pytest.fixture
def order(db, ref) -> SalesOrder:
    cust = Customer(code="C-A", name="Retailer A", customer_type=CustomerType.RETAILER, state_code="33",
                    address="Chennai")
    db.add(cust)
    db.flush()
    so = SalesOrder(order_no="SO-1", customer_id=cust.id, salesman_id=ref["user"].id,
                    order_date=date(2026, 11, 2), status=OrderStatus.APPROVED)
    db.add(so)
    db.flush()
    return so


def test_benchmark_invoice_amounts_are_accepted(db, ref, order):
    db.add(_invoice(ref, order.id, order.customer_id))
    db.flush()


def test_intra_state_invoice_cannot_carry_igst(db, ref, order):
    db.add(_invoice(ref, order.id, order.customer_id, igst_amount=Decimal("375.00"), total_amount=Decimal("8250.00")))
    _expect_integrity_error(db)


def test_invoice_total_must_equal_components(db, ref, order):
    db.add(_invoice(ref, order.id, order.customer_id, total_amount=Decimal("7876.00")))
    _expect_integrity_error(db)


def test_alembic_migration_matches_models(tmp_path: Path, monkeypatch):
    """The committed migration produces exactly the schema the models describe."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext

    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.chdir(backend)
    command.upgrade(Config(str(backend / "alembic.ini")), "head")

    eng = create_engine(url)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    eng.dispose()
    assert diff == []
