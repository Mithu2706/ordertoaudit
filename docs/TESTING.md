# Testing

## What is tested

| Layer | Where | Runs on |
|---|---|---|
| Unit and service rules (units, GST, costing, variance, numbering, ledger) | `tests/test_*.py` | SQLite and PostgreSQL |
| API, validation and the 80-case permission matrix | `test_permissions.py`, `test_*.py` | SQLite and PostgreSQL |
| **End-to-end benchmark over HTTP** (real password logins, steps 1–9, reports, dashboard, audit trail) | `test_e2e_benchmark.py` | SQLite and PostgreSQL |
| Production configuration (SPA serving, start-up guard) | `test_deployment.py` | SQLite and PostgreSQL |
| **Concurrency** (row locks, idempotent postings, gap-free numbering) | `test_postgres.py` | PostgreSQL only |
| **Database guards** (append-only ledger trigger, CHECK constraints) and **migrations** (down to base and back up) | `test_postgres.py` | PostgreSQL only |

Latest results (Phase 10):

* SQLite: **246 passed, 9 skipped**. The skipped tests are PostgreSQL-only.
* PostgreSQL 16.2: **255 passed, 0 skipped**.

## Running

```powershell
cd backend
.venv\Scripts\python -m pytest                       # SQLite, in memory, about 20 s
```

To run against PostgreSQL without Docker, start a throwaway local server (`pgserver` is in `requirements-dev.txt`):

```powershell
.venv\Scripts\python scripts\dev_postgres.py
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:<port>/ota_test"
.venv\Scripts\python -m pytest                       # about 70 s
```

On PostgreSQL the suite builds its schema with the **real Alembic migrations**, not `create_all`. A
PostgreSQL run therefore also proves that the migrations match the models and that the ledger
trigger is installed. The concurrency tests use their own scratch database (`<test db>_concurrency`),
which they rebuild for every test.

## The concurrency tests

Each test starts two or more transactions on separate connections at the same moment. Each
transaction then stays open for 0.5 s before it commits, so the transactions really overlap.

| Race | Expected outcome |
|---|---|
| Two 150-packet issues against 238 on hand | One succeeds; the other gets `insufficient_stock`. The balance is 88, never negative. |
| The same posting key posted twice at once | Exactly one movement is posted. |
| Approving Retailer A (150) and Distributor B (120) at once, 238 on hand | One is approved; the other is refused for a shortage. |
| Two admins approving the same order at once | It is applied once; the second admin gets a clean "order changed" error. |
| Four invoices raised at once, the first of the financial year | Numbers 00001–00004, distinct and gap-free. |
| Two ₹5,000 receipts against a ₹7,875 invoice | ₹5,000 + ₹2,875 are allocated and ₹2,125 is kept as an advance. Never over-allocated. |

**The tests are verified to catch the bugs they target.** When the item row lock is removed from
`lock_item`, the overdraw and competing-approval tests fail. When the invoice lock is removed from
`record_payment`, the payment test fails. The duplicate-posting test still passes without the item
lock, because the unique `posting_key` constraint is a second, independent guard.

## Bugs found and fixed in Phase 9

1. **A locked read could return stale in-memory data.** `SELECT … FOR UPDATE` waits for the lock, but
   SQLAlchemy does not refresh an object that is already loaded in the session. A second admin
   approving the same order could therefore pass the version check on stale data. Only the ORM
   version column then stopped the double approval, and it raised a raw `StaleDataError`. Every
   locking read now uses `populate_existing=True`.
2. **The first document of a financial year could fail under load.** The year's numbering row was
   created on first use, so two simultaneous first invoices both tried to insert it and one failed
   with a duplicate-key error. The row is now created with `INSERT … ON CONFLICT DO NOTHING`, then
   locked.
3. **Invalid escape sequence in a docstring** (`services/sales.py`). This is a warning today and
   an error in future Python versions. Our own `DeprecationWarning`s and all `SyntaxWarning`s now fail the test run.

## Also verified on PostgreSQL

On a fresh database: `alembic upgrade head`, then `python -m app.seed.scenario`. All 17 benchmark
checks match, and a second run is refused. The live API was then smoke-tested over HTTP on that
database: login, dashboard figures, invoice PDF, CSV/Excel/PDF report exports, and 401 for a
missing token or wrong password.

## Not covered

* Browser end-to-end tests are not automated. The UI was checked by hand in Phase 8.
* Load and performance testing.
* `docker compose up` itself: Docker isn't installed here. See [DEPLOYMENT.md](DEPLOYMENT.md#what-has-been-verified) for what was verified instead.
