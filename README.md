# Order-to-Audit System

Integrated order-to-audit management system for a small South Indian
packaged-snacks manufacturer:
**Sales → Order Verification → GST Invoice → Dispatch → Inventory → Production → Costing → Monthly Audit Reports.**

> Status: **Phase 1 complete** (architecture, database schema, ER diagram).
> The application is being built phase by phase; see the plan in
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#6-implementation-plan-phases).

## Stack

React + Vite + TypeScript + Tailwind (frontend) · FastAPI + SQLAlchemy 2 +
Pydantic 2 + Alembic (backend) · PostgreSQL · ReportLab / openpyxl ·
Pytest · Docker Compose.

## Documentation

* [Architecture & implementation plan](docs/ARCHITECTURE.md)
* [Database schema & ER diagram](docs/DATABASE.md)

## Backend quick start (development)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Apply migrations to PostgreSQL (copy `.env.example` to `.env` first):

```powershell
cd backend
$env:DATABASE_URL = "postgresql+psycopg://ota:ota_password@localhost:5432/order_to_audit"
.venv\Scripts\alembic upgrade head
```

Tests use in-memory SQLite by default. To run the same suite against
PostgreSQL, set `TEST_DATABASE_URL`.
