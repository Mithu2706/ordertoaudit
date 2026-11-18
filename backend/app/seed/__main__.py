"""Usage:
    python -m app.seed                 reference data + demo users
    python -m app.seed --benchmark     ... + benchmark masters, BOM and opening stock
    python -m app.seed --no-users      reference data only
Run `alembic upgrade head` first. Every step is idempotent."""
import sys

from app.core.database import SessionLocal
from app.seed.benchmark import seed_benchmark
from app.seed.reference_data import seed_demo_users, seed_reference


def main(argv: list[str]) -> None:
    with SessionLocal.begin() as db:
        seed_reference(db)
        created = [] if "--no-users" in argv else seed_demo_users(db)
        if "--benchmark" in argv:
            seed_benchmark(db)
    print("Reference data seeded.")
    if created:
        print("Demo users created:", ", ".join(created))
    if "--benchmark" in argv:
        print("Benchmark masters, BOM and opening stock loaded.")


if __name__ == "__main__":
    main(sys.argv[1:])
