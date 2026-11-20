"""PostgreSQL-only tests: real concurrency, the ledger's append-only trigger, and migrations.

Skipped on SQLite. Run with, e.g.:
    $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:5432/ota_test"
    .venv\\Scripts\\python -m pytest tests/test_postgres.py

Concurrency tests need committed data visible to several connections, so they use their own
scratch database (<test db>_concurrency), rebuilt from the migrations for every test.
"""
import threading
import time
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models import Invoice, Item, SalesOrder, StockMovement, User
from app.models.enums import MovementType, OrderStatus
from app.services import inventory, invoicing, sales
from tests import benchmark_steps as bs
from tests.conftest import IS_POSTGRES, TEST_DATABASE_URL, migrate_postgres, postgres_only, reset_postgres_schema

pytestmark = postgres_only
D = Decimal


# --------------------------------------------------------------------------- schema / trigger

def test_ledger_rows_cannot_be_updated_or_deleted(db: Session):
    b = bs.setup(db)
    mv = db.scalars(select(StockMovement).where(StockMovement.item_id == b.ids["RM-FLOUR"])).first()
    for stmt in (text("UPDATE stock_movements SET quantity = 999 WHERE id = :id"),
                 text("DELETE FROM stock_movements WHERE id = :id")):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(stmt, {"id": mv.id})
        nested.rollback()


def test_database_refuses_negative_balance_even_without_the_service(db: Session):
    b = bs.setup(db)
    mv = db.scalars(select(StockMovement).where(StockMovement.item_id == b.ids["RM-FLOUR"])).first()
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="balance_non_negative"):
        db.execute(text("""
            INSERT INTO stock_movements (item_id, movement_type, movement_date, quantity, unit_id, entered_quantity,
                entered_unit_id, unit_cost, value, balance_after, value_after, source_document_type, reference_no,
                posting_key, created_by)
            SELECT item_id, movement_type, movement_date, quantity, unit_id, entered_quantity, entered_unit_id,
                unit_cost, value, -1, value_after, 'TEST', 'X', 'neg-test', created_by
            FROM stock_movements WHERE id = :id"""), {"id": mv.id})
    nested.rollback()


def test_migrations_downgrade_and_upgrade_cleanly():
    from alembic import command
    from alembic.config import Config

    from tests.conftest import BACKEND_DIR
    url = _scratch_url("migrations")
    _ensure_database(url)
    eng = create_engine(url)
    try:
        reset_postgres_schema(eng)
        migrate_postgres(url)
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        import os
        os.environ["DATABASE_URL"] = url
        try:
            command.downgrade(cfg, "base")
            with eng.connect() as c:
                left = c.execute(text("SELECT count(*) FROM information_schema.tables "
                                      "WHERE table_schema = 'public' AND table_name <> 'alembic_version'")).scalar()
            assert left == 0
            command.upgrade(cfg, "head")
        finally:
            os.environ.pop("DATABASE_URL", None)
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- concurrency helpers

def _scratch_url(suffix: str) -> str:
    url = make_url(TEST_DATABASE_URL)
    return url.set(database=f"{url.database}_{suffix}").render_as_string(hide_password=False)


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}).scalar():
                c.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin.dispose()


@pytest.fixture
def live() -> Iterator[Engine]:
    """A committed database (fresh schema per test) with the benchmark through step 3."""
    if not IS_POSTGRES:
        pytest.skip("needs PostgreSQL")
    url = _scratch_url("concurrency")
    _ensure_database(url)
    eng = create_engine(url, pool_size=10)
    reset_postgres_schema(eng)
    migrate_postgres(url)
    from app.seed.reference_data import seed_reference
    with Session(eng, expire_on_commit=False) as s:
        seed_reference(s)
        bs.through_step3(s)  # FG on hand: 238 packets
        s.commit()
    yield eng
    eng.dispose()


def race(eng: Engine, *jobs: Callable[[Session], object], hold: float = 0.5) -> list[object]:
    """Run each job in its own thread + session at the same moment; commit each.

    Each transaction stays open for `hold` seconds after its work, before committing, so the
    jobs genuinely overlap: without row locks a second job would read the stale balance
    (verified by removing the lock: these tests then fail).
    Returns the job's result, or the exception it raised."""
    barrier = threading.Barrier(len(jobs))
    results: list[object] = [None] * len(jobs)

    def worker(i: int, job: Callable[[Session], object]) -> None:
        with Session(eng, expire_on_commit=False) as s:
            try:
                barrier.wait(timeout=10)
                results[i] = job(s)
                time.sleep(hold)
                s.commit()
            except Exception as exc:  # noqa: BLE001  (recorded for the assertion)
                s.rollback()
                results[i] = exc

    threads = [threading.Thread(target=worker, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "deadlock or hang"
    return results


def _ids(eng: Engine) -> tuple[dict[str, int], dict[str, int]]:
    with Session(eng) as s:
        items = {i.code: i.id for i in s.scalars(select(Item))}
        users = {u.username: u.id for u in s.scalars(select(User))}
    return items, users


def _fg_balance(eng: Engine, fg: int) -> Decimal:
    with Session(eng) as s:
        return inventory.current_balance(s, fg).quantity


# --------------------------------------------------------------------------- concurrency tests

def test_two_simultaneous_issues_cannot_overdraw_stock(live: Engine):
    items, users = _ids(live)
    fg = items["FG-MUR200"]

    def issue(key: str):
        def job(s: Session):
            return inventory.post_movement(
                s, item_id=fg, movement_type=MovementType.DAMAGE, quantity=D("150"), unit="PKT",
                actor_id=users["admin"], source_document_type="TEST", reference_no=key, posting_key=key,
                movement_date=date.today())
        return job

    results = race(live, issue("race-1"), issue("race-2"))
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], inventory.InsufficientStockError), results
    assert _fg_balance(live, fg) == D("88")  # 238 - 150, never negative


def test_same_posting_key_twice_concurrently_posts_once(live: Engine):
    items, users = _ids(live)
    fg = items["FG-MUR200"]

    def job(s: Session):
        return inventory.post_movement(
            s, item_id=fg, movement_type=MovementType.DAMAGE, quantity=D("10"), unit="PKT", actor_id=users["admin"],
            source_document_type="TEST", reference_no="dup", posting_key="dup-key", movement_date=date.today())

    results = race(live, job, job)
    assert sum(isinstance(r, Exception) for r in results) == 1, results
    assert _fg_balance(live, fg) == D("228")
    with Session(live) as s:
        assert s.scalar(select(func.count()).where(StockMovement.posting_key == "dup-key")) == 1


def _submitted_order(eng: Engine, salesman: str, customer: str, qty: str) -> int:
    with Session(eng, expire_on_commit=False) as s:
        b = bs.Bench(ids={i.code: i.id for i in s.scalars(select(Item))},
                     users={u.username: u for u in s.scalars(select(User))},
                     customers={c.code: c for c in s.scalars(select(bs.Customer))})
        order = bs.place_order(s, b, salesman, customer, qty)
        s.commit()
        return order.id


def _approve_job(order_id: int):
    from app.schemas.sales import ApproveIn

    def job(s: Session):
        admin = s.scalars(select(User).where(User.username == "admin")).one()
        order = s.get(SalesOrder, order_id)
        return sales.approve_order(s, order_id, ApproveIn(version=order.version), admin).status
    return job


def test_competing_approvals_cannot_promise_the_same_stock_twice(live: Engine):
    """238 on hand; two orders of 150 and 120 approved at the same instant: only one may succeed."""
    a = _submitted_order(live, "salesman_a", "RET-A", "150")
    b = _submitted_order(live, "salesman_b", "DIST-B", "120")
    results = race(live, _approve_job(a), _approve_job(b))
    ok = [r for r in results if r == OrderStatus.APPROVED]
    errors = [r for r in results if isinstance(r, DomainError)]
    assert len(ok) == 1 and len(errors) == 1, results
    with Session(live) as s:
        statuses = sorted(s.get(SalesOrder, i).status.value for i in (a, b))
    assert statuses == ["APPROVED", "SUBMITTED"]


def test_double_click_approval_by_two_admins_applies_once(live: Engine):
    a = _submitted_order(live, "salesman_a", "RET-A", "100")
    results = race(live, _approve_job(a), _approve_job(a))
    assert results.count(OrderStatus.APPROVED) == 1, results
    assert sum(isinstance(r, DomainError) for r in results) == 1, results


def test_simultaneous_invoices_get_distinct_gap_free_numbers(live: Engine):
    orders = [_submitted_order(live, "salesman_a", "RET-A", "50") for _ in range(4)]
    for o in orders:  # approve sequentially (4 x 50 = 200 <= 238)
        race(live, _approve_job(o), hold=0)

    def invoice(order_id: int):
        def job(s: Session):
            admin = s.scalars(select(User).where(User.username == "admin")).one()
            return invoicing.create_invoice(s, order_id, None, admin).invoice_no
        return job

    results = race(live, *(invoice(o) for o in orders))
    assert all(isinstance(r, str) for r in results), results
    serials = sorted(int(n.rsplit("/", 1)[1]) for n in results)
    assert serials == [1, 2, 3, 4]
    with Session(live) as s:
        assert s.scalar(select(func.count()).select_from(Invoice)) == 4


def test_simultaneous_payments_never_over_allocate_an_invoice(live: Engine):
    """Retailer A owes 7,875; two receipts of 5,000 arrive at once. FIFO allocation must give
    5,000 + 2,875 to the invoice and keep 2,125 as an advance, never 10,000 against 7,875."""
    from app.models import Customer, Payment
    from app.models.enums import PaymentMode
    from app.services import payments

    order_id = _submitted_order(live, "salesman_a", "RET-A", "150")
    race(live, _approve_job(order_id), hold=0)
    with Session(live) as s:
        admin = s.scalars(select(User).where(User.username == "admin")).one()
        inv = invoicing.create_invoice(s, order_id, None, admin)
        s.commit()
        inv_id, cust_id = inv.id, s.scalars(select(Customer).where(Customer.code == "RET-A")).one().id

    def pay(ref: str):
        def job(s: Session):
            admin = s.scalars(select(User).where(User.username == "admin")).one()
            p = payments.record_payment(s, customer_id=cust_id, payment_date=date.today(), amount=D("5000"),
                                        mode=PaymentMode.UPI, reference_no=ref, remarks=None, allocations=None,
                                        actor=admin)
            return sum((a.amount for a in p.allocations), D(0))
        return job

    results = race(live, pay("UTR-1"), pay("UTR-2"))
    assert sorted(results) == [D("2875.00"), D("5000.00")], results
    with Session(live) as s:
        assert invoicing.invoice_balance(s, s.get(Invoice, inv_id)) == D("0.00")
        assert s.scalar(select(func.count()).select_from(Payment)) == 2


def test_simultaneous_approvals_cannot_both_fit_under_one_credit_limit(live: Engine):
    """Retailer A limit 10,000: two orders of 100 packets (5,250 each) fit alone, not together."""
    from app.models import Customer
    from app.services.credit import CreditLimitError
    with Session(live) as s:
        cust = s.scalars(select(Customer).where(Customer.code == "RET-A")).one()
        cust.credit_limit = D("10000.00")
        s.commit()
    a = _submitted_order(live, "salesman_a", "RET-A", "100")
    b = _submitted_order(live, "salesman_a", "RET-A", "100")
    results = race(live, _approve_job(a), _approve_job(b))
    assert results.count(OrderStatus.APPROVED) == 1, results
    assert sum(isinstance(r, CreditLimitError) for r in results) == 1, results


def test_simultaneous_reversals_of_one_receipt_apply_once(live: Engine):
    from app.models import Customer
    from app.models.enums import PaymentMode
    from app.services import payments

    order_id = _submitted_order(live, "salesman_a", "RET-A", "150")
    race(live, _approve_job(order_id), hold=0)
    with Session(live) as s:
        admin = s.scalars(select(User).where(User.username == "admin")).one()
        inv = invoicing.create_invoice(s, order_id, None, admin)
        cust = s.scalars(select(Customer).where(Customer.code == "RET-A")).one()
        p = payments.record_payment(s, customer_id=cust.id, payment_date=date.today(), amount=D("4000"),
                                    mode=PaymentMode.CHEQUE, reference_no="CHQ-1", remarks=None, allocations=None,
                                    actor=admin)
        s.commit()
        inv_id, pay_id = inv.id, p.id

    def job(s: Session):
        admin = s.scalars(select(User).where(User.username == "admin")).one()
        return payments.reverse_payment(s, pay_id, reason="Cheque bounced", reversal_date=None, actor=admin).id

    results = race(live, job, job)
    assert results.count(pay_id) == 1 and sum(isinstance(r, DomainError) for r in results) == 1, results
    with Session(live) as s:
        assert invoicing.invoice_balance(s, s.get(Invoice, inv_id)) == D("7875.00")
