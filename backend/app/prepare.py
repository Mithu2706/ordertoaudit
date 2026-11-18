"""Container start-up: wait for the database, apply migrations, seed as configured.

    python -m app.prepare

Environment:
    SEED            none | reference | demo | benchmark | scenario   (default: demo)
                      reference : roles, states, units, company profile, settings
                      demo      : + demo user accounts (password SEED_DEMO_PASSWORD)
                      benchmark : + benchmark masters, BOM and opening stock
                      scenario  : + run the benchmark scenario through step SCENARIO_UNTIL
    SCENARIO_UNTIL  1-9 (default 3: production done, sales steps left to demonstrate live)
    DB_WAIT_SECONDS how long to wait for the database (default 60)

Every step is idempotent, so restarting the container is safe: migrations are a no-op when
current, seeding skips existing rows, and the scenario is never re-run on a database that
already has activity.
"""
import os
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEED_MODES = ("none", "reference", "demo", "benchmark", "scenario")


class StartupError(RuntimeError):
    pass


def wait_for_database(url: str, timeout: float) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    deadline = time.monotonic() + timeout
    last_reason = None
    try:
        while True:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return
            except OperationalError as exc:
                reason = str(exc.orig).strip().splitlines()[-1] if exc.orig else str(exc)
                if time.monotonic() > deadline:
                    raise StartupError(f"Database not reachable after {timeout:.0f}s: {reason}") from None
                if reason != last_reason:  # say why once, not every retry
                    print(f"Waiting for the database ({reason})...", flush=True)
                    last_reason = reason
                time.sleep(2)
    finally:
        engine.dispose()


def migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    os.environ["DATABASE_URL"] = url
    command.upgrade(cfg, "head")


def seed(mode: str, until: int) -> None:
    from app.core.database import SessionLocal
    from app.models import ProductionRun, Purchase
    from app.seed.benchmark import seed_benchmark
    from app.seed.reference_data import seed_demo_users, seed_reference

    if mode == "none":
        return
    if mode == "scenario":
        with SessionLocal() as db:
            started = db.scalars(select(Purchase.id)).first() or db.scalars(select(ProductionRun.id)).first()
        if started:
            print("Scenario skipped: the database already has activity.")
            return
        from app.seed import scenario
        with SessionLocal.begin() as db:
            scenario.run(db, until)
        print(f"Benchmark scenario run through step {until}.")
        return
    with SessionLocal.begin() as db:
        seed_reference(db)
        if mode in ("demo", "benchmark"):
            created = seed_demo_users(db)
            if created:
                print("Demo users created:", ", ".join(created))
        if mode == "benchmark":
            seed_benchmark(db)
    print(f"Seed '{mode}' applied.")


def main() -> int:
    mode = os.environ.get("SEED", "demo").strip().lower()
    if mode not in SEED_MODES:
        print(f"SEED must be one of {', '.join(SEED_MODES)} (got {mode!r})", file=sys.stderr)
        return 2
    until = int(os.environ.get("SCENARIO_UNTIL", "3"))
    if not 1 <= until <= 9:
        print("SCENARIO_UNTIL must be between 1 and 9", file=sys.stderr)
        return 2
    url = get_settings().database_url
    try:
        wait_for_database(url, float(os.environ.get("DB_WAIT_SECONDS", "60")))
    except StartupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    migrate(url)
    seed(mode, until)
    return 0


if __name__ == "__main__":
    sys.exit(main())
