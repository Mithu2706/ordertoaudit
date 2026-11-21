# Deployment

## Option A: Docker Compose (recommended)

You need Docker Desktop (Windows/macOS) or Docker Engine with the Compose plugin (Linux).

```powershell
git clone <repo-url> order-to-audit-system
cd order-to-audit-system
copy .env.example .env
```

Edit `.env` and set two secrets. Compose refuses to start without them, and the app refuses a
weak JWT secret.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"   # use the output as JWT_SECRET_KEY
```

```ini
POSTGRES_PASSWORD=<a strong database password>
JWT_SECRET_KEY=<the 64-character value printed above>
```

Start it:

```powershell
docker compose up --build -d
docker compose logs -f app        # watch the first start: migrations, then seeding
```

Open <http://localhost:8000> and sign in with a [demo account](../README.md#demo-credentials).

### What happens on start

```
db  (postgres:16-alpine) ── healthy ──►  app
                                          1. python -m app.prepare
                                             · wait for the database
                                             · alembic upgrade head
                                             · seed according to SEED
                                          2. uvicorn (2 workers) serving
                                             /api/*  → FastAPI
                                             /*      → the built React app
```

Every start step is idempotent, so `docker compose restart app` and upgrades are safe.

### Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_PASSWORD` | *(required)* | Database password |
| `JWT_SECRET_KEY` | *(required)* | Token signing key. At least 32 random characters |
| `SEED` | `scenario` | `none`, `reference`, `demo` (+ demo users), `benchmark` (+ masters, BOM, opening stock), or `scenario` (+ the benchmark run through `SCENARIO_UNTIL`) |
| `SCENARIO_UNTIL` | `3` | Last benchmark step pre-run. `3` = production posted, steps 4–7 left to demo live; `7` = everything |
| `SEED_DEMO_PASSWORD` | `Demo@1234` | Password for the demo accounts (applied only when they are first created) |
| `APP_PORT` | `8000` | Host port |
| `WEB_CONCURRENCY` | `2` | Uvicorn worker processes |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Session length |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Reverse proxy addresses trusted for `X-Forwarded-For` (audit-log IPs) |

For a **real business** (not a demo), use `SEED=reference`. Then create users through the API
(`POST /api/users` as the owner) and enter master data. Don't create demo accounts.

### Operations

```powershell
docker compose ps                                       # health status
docker compose exec db pg_dump -U ota order_to_audit > backup.sql
docker compose exec -T db psql -U ota order_to_audit < backup.sql
docker compose down        # stop (data kept in the pgdata volume)
docker compose down -v     # stop AND delete all data
```

To reset the demo, run `docker compose down -v` and then `docker compose up -d`.

### Putting it on the internet

* Put it behind a TLS-terminating reverse proxy (Caddy, nginx, a cloud load balancer). Set
  `FORWARDED_ALLOW_IPS` to the proxy's IP address, so the audit log records the real client IP
  from `X-Forwarded-For`. By default only `127.0.0.1` is trusted, so nobody can spoof the header.
* Keep the database port unpublished (it is by default) and back up the `pgdata` volume.
* Use `SEED=reference` and change every default password.

## Option B: without Docker

You need Python 3.11, Node 20+ and PostgreSQL 14+. If you have no PostgreSQL, run
`backend\scripts\dev_postgres.py`, which starts one locally.

```powershell
cd frontend
npm ci
npm run build                        # → frontend\dist

cd ..\backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql+psycopg://user:pass@localhost:5432/order_to_audit"
$env:JWT_SECRET_KEY = "<64 random characters>"
$env:APP_ENV = "production"
$env:STATIC_DIR = "..\frontend\dist"
$env:SEED = "scenario"
.venv\Scripts\python -m app.prepare
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

For development, with hot reload on two ports, see the [README](../README.md#backend-quick-start).

## What has been verified

`docker compose up --build` has been run end to end: Docker Engine 29.1 with Compose 2.40,
inside WSL2 Ubuntu 24.04 on Windows 11, `SEED=scenario`, `APP_PORT=8080`.

| Check | Result |
|---|---|
| Image build (Node 20 Alpine `npm ci` + Vite build, Python 3.11 slim runtime) | ✅ builds first time, no warnings from the project |
| `db` health check, then `app` waits for it (`depends_on: service_healthy`) | ✅ |
| First start: migrations 0001–0004, then benchmark steps 1–3 | ✅ |
| `app` health check (`/api/health`) | ✅ healthy |
| Benchmark steps 4–7 driven over HTTP from the Windows host against the container | ✅ 17 of 17 checks match: stock, invoice ₹7,875, PDF, FG 88, shortage 32, refused full approval, outstanding ₹3,875, dashboard, GST summary CSV/Excel/PDF |
| SPA deep link `/sales/new`, JSON 404 for an unknown API path, 401 without a token | ✅ |
| Dashboard in a browser from the container | ✅ no console errors; the charts chunk loads only on that page |
| Data survives a container restart and a full VM restart (the `pgdata` volume) | ✅ restarts log "Scenario skipped" |
| App runs as a non-root user | ✅ `app`, UID 10001 |
| Database port not published to the host | ✅ |

The start-up steps were also checked outside Docker: an unreachable database gives one clear
error line and exit code 1, an invalid `SEED` gives exit code 2, and the example JWT secret
makes the app refuse to start. `tests/test_deployment.py` covers the SPA serving rules and the
production guard.

### Docker on Windows without Docker Desktop

That check used Docker Engine installed inside WSL2 Ubuntu, which needs no Docker Desktop
licence and no Windows changes:

```powershell
wsl -u root -- apt-get update
wsl -u root -- apt-get install -y docker.io docker-compose-v2
wsl -u root -- systemctl enable --now docker
```

Then run Compose from the repository folder inside WSL:

```powershell
wsl -u root -- docker compose -f /mnt/c/path/to/order-to-audit-system/docker-compose.yml up -d --build
```

The app is then at `http://localhost:<APP_PORT>` from Windows.

**Keep WSL running.** WSL stops its VM a few seconds after the last WSL process exits, and Docker
stops with it. The containers come back (`restart: unless-stopped`) the next time WSL starts.
To keep the app up, either leave a WSL terminal open or run this in a separate window:

```powershell
wsl -u root -- sleep infinity
```
