# Order-to-Audit System

Integrated order-to-audit management system for a small South Indian
packaged-snacks manufacturer:
**Sales → Order Verification → GST Invoice → Dispatch → Inventory → Production → Costing → Monthly Audit Reports.**

> Status: **complete prototype (Phase 10)**. All 15 reports, every role's screens and the full
> mandatory benchmark work end to end. **287 tests pass on PostgreSQL 16** (275 on SQLite, plus 12
> that need PostgreSQL), including the whole benchmark over HTTP and real concurrency tests.
> See [what is done and what is not](docs/PROJECT.md#moscow).

## Run it (Docker)

```powershell
copy .env.example .env     # set POSTGRES_PASSWORD and JWT_SECRET_KEY (see the file)
docker compose up --build -d
```

Open <http://localhost:8000> and sign in with a [demo account](#demo-credentials). By default the
benchmark is pre-run through production (steps 1–3), ready for the
[demo script](docs/DEMO_SCRIPT.md). Details, options and backups:
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The stack has been built and run end to end, and the
benchmark checked against the running containers ([details](docs/DEPLOYMENT.md#what-has-been-verified)).
On Windows it also runs on Docker Engine inside WSL2, with no Docker Desktop needed
([how](docs/DEPLOYMENT.md#docker-on-windows-without-docker-desktop)).

## Stack

React + Vite + TypeScript + Tailwind (frontend) · FastAPI + SQLAlchemy 2 +
Pydantic 2 + Alembic (backend) · PostgreSQL · PyJWT + bcrypt ·
ReportLab / openpyxl · Pytest · Docker Compose. [Why this stack](docs/PROJECT.md#stack-justification).

## Documentation

**Start here**
* [Design note](docs/DESIGN_NOTE.md) (2 pages): architecture, key decisions, trade-offs
* [Benchmark: expected results and workings](docs/BENCHMARK.md)
* [Project overview](docs/PROJECT.md): stack justification, MoSCoW, assumptions, limitations
* [Deployment](docs/DEPLOYMENT.md) · [Demo script (8 min)](docs/DEMO_SCRIPT.md) · [Testing](docs/TESTING.md)

**Reference**
* [Architecture & implementation plan](docs/ARCHITECTURE.md)
* [Database schema & ER diagram](docs/DATABASE.md)
* [API & permissions](docs/API.md)
* [Inventory engine](docs/INVENTORY.md)
* [BOM & production engine](docs/PRODUCTION.md)
* [Sales, GST billing, dispatch & receivables](docs/BILLING.md)
* [Reports, exports & costing](docs/REPORTS.md)

## Development

### Backend quick start

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

### Frontend quick start

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to the backend on
`:8000`, so start the API first. `npm run build` type-checks and builds
the production bundle.

## Demo credentials

Created by `python -m app.seed`, and by the Docker start-up unless `SEED` is `none` or
`reference`. The password for every account is
`Demo@1234`, which you can override with the `SEED_DEMO_PASSWORD`
environment variable before seeding. These accounts are **for demonstration
only**.

| Username | Role | Use it to… |
|---|---|---|
| `owner` | Owner | dashboard, users (incl. owners), settings |
| `admin` | Admin | approve orders, invoices, dispatch, payments, master data (customers, products, users…) |
| `production` | Production Supervisor | receipts, BOMs, production runs |
| `auditor` | Accountant / Auditor | read-only reports and audit log |
| `salesman_a` | Salesman | orders for Retailer A (Tamil Nadu) |
| `salesman_b` | Salesman | orders for Distributor B (Karnataka) |
