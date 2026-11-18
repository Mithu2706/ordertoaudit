"""Start a throwaway local PostgreSQL 16 server (no Docker, no system install) for development and tests.

    .venv\Scripts\python scripts\dev_postgres.py [data_dir]

Uses the `pgserver` package (bundled PostgreSQL binaries, in requirements-dev.txt). The server
keeps running after this script exits; it prints URLs for a dev and a test database.
Data lives in `data_dir` (default: .pgdata next to this backend, git-ignored).
"""
import sys
from pathlib import Path

import pgserver


def main() -> int:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / ".pgdata"
    srv = pgserver.get_server(data_dir, cleanup_mode=None)
    uri = srv.get_uri()  # postgresql://postgres:@127.0.0.1:<port>/postgres
    base = uri.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://").replace("postgres:@", "postgres@")
    for name in ("ota_dev", "ota_test"):
        if "(0 rows)" in srv.psql(f"SELECT 1 FROM pg_database WHERE datname = '{name}';"):
            srv.psql(f"CREATE DATABASE {name};")
    print(f"PostgreSQL running ({data_dir})")
    print(f"  DATABASE_URL      = {base}/ota_dev")
    print(f"  TEST_DATABASE_URL = {base}/ota_test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
