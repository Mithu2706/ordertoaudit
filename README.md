# Order-to-Audit System

Integrated order-to-audit management system for a small South Indian
packaged-snacks manufacturer:
**Sales → Order Verification → GST Invoice → Dispatch → Inventory → Production → Costing → Monthly Audit Reports.**

> Status: **Phase 2 complete**: architecture, schema, authentication, roles,
> master data and audit trail. The application is being built phase by phase;
> see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#6-implementation-plan-phases).

## Stack

React + Vite + TypeScript + Tailwind (frontend) · FastAPI + SQLAlchemy 2 +
Pydantic 2 + Alembic (backend) · PostgreSQL · PyJWT + bcrypt ·
ReportLab / openpyxl · Pytest · Docker Compose.

## Documentation

* [Architecture & implementation plan](docs/ARCHITECTURE.md)
* [Database schema & ER diagram](docs/DATABASE.md)
* [API & permissions](docs/API.md)

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
.venv\Scripts\python -m app.seed
.venv\Scripts\uvicorn app.main:app --reload
```

Interactive API docs: <http://localhost:8000/api/docs>. Use **Authorize**
with a demo account.

Tests use in-memory SQLite by default. To run the same suite against
PostgreSQL, set `TEST_DATABASE_URL`.

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
