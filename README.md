# Order-to-Audit System

Integrated order-to-audit management system for a small South Indian
packaged-snacks manufacturer:
**Sales → Order Verification → GST Invoice → Dispatch → Inventory → Production → Costing → Monthly Audit Reports.**

> Status: **Phase 9 complete**. The backend covers the whole order-to-audit flow:
> authentication and roles, master data, audit trail, stock ledger, purchases,
> BOMs and production (variance, costing), sales orders with stock
> reservation, GST invoices (PDF), dispatch, credit notes, payments and
> receivables, plus 15 reports with CSV/Excel/PDF export and product costing.
> Benchmark steps 1–9 are verified. Phase 8 added the React frontend with
> role-specific screens for every role. Phase 9 added an end-to-end HTTP benchmark test and
> PostgreSQL concurrency tests, and fixed the bugs they found. All 247 tests pass on PostgreSQL
> ([docs/TESTING.md](docs/TESTING.md)). See
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#6-implementation-plan-phases).

## Stack

React + Vite + TypeScript + Tailwind (frontend) · FastAPI + SQLAlchemy 2 +
Pydantic 2 + Alembic (backend) · PostgreSQL · PyJWT + bcrypt ·
ReportLab / openpyxl · Pytest · Docker Compose.

## Documentation

* [Architecture & implementation plan](docs/ARCHITECTURE.md)
* [Database schema & ER diagram](docs/DATABASE.md)
* [API & permissions](docs/API.md)
* [Inventory engine](docs/INVENTORY.md)
* [BOM & production engine](docs/PRODUCTION.md) (includes benchmark steps 1–3 and costing)
* [Sales, GST billing, dispatch & receivables](docs/BILLING.md) (benchmark steps 4–7)
* [Reports, exports & costing](docs/REPORTS.md) (benchmark steps 8–9)
* [Testing: end-to-end, concurrency, PostgreSQL](docs/TESTING.md)

## Backend quick start (development)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Run the API against PostgreSQL (copy `.env.example` to `backend\.env` and
set a real `JWT_SECRET_KEY` first):

```powershell
cd backend
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m app.seed --benchmark
.venv\Scripts\uvicorn app.main:app --reload
```

`--benchmark` also loads the benchmark master data, BOM and opening stock.
Without it, only reference data and demo users are seeded.

Interactive API docs: <http://localhost:8000/api/docs>. Use **Authorize**
with a demo account.

Tests use in-memory SQLite by default. To run the same suite against
PostgreSQL, set `TEST_DATABASE_URL`. That also runs the concurrency tests, which
need PostgreSQL. If you have no PostgreSQL, `python scripts\dev_postgres.py` starts a
throwaway local server (no Docker needed) and prints both URLs. See
[docs/TESTING.md](docs/TESTING.md).

### Re-run the benchmark scenario

On a fresh database (after `alembic upgrade head`), with no seeding needed:

```powershell
cd backend
.venv\Scripts\python -m app.seed.scenario
```

This runs all benchmark steps through the real services and prints expected
vs actual figures. Add `--until 3` to stop after production, which leaves
steps 4–7 to demonstrate live in the UI.

## Frontend quick start

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to the backend on
`:8000`, so start the API first. `npm run build` type-checks and builds
the production bundle.

## Demo credentials

Created by `python -m app.seed`. The password for every account is
`Demo@1234`, which you can override with the `SEED_DEMO_PASSWORD`
environment variable before seeding. These accounts are **for demonstration
only**.

| Username | Role | Use it to… |
|---|---|---|
| `owner` | Owner | dashboard, users (incl. owners), settings |
| `admin` | Admin | approve orders, invoices, dispatch, payments, masters |
| `production` | Production Supervisor | receipts, BOMs, production runs |
| `auditor` | Accountant / Auditor | read-only reports and audit log |
| `salesman_a` | Salesman | orders for Retailer A (Tamil Nadu) |
| `salesman_b` | Salesman | orders for Distributor B (Karnataka) |
