#!/bin/sh
# Wait for PostgreSQL, apply migrations, seed (per $SEED), then run the API + frontend.
# X-Forwarded-For is trusted only from FORWARDED_ALLOW_IPS (set it to your reverse proxy's
# address), so clients cannot spoof the IP recorded in the audit log.
set -e
python -m app.prepare
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --workers "${WEB_CONCURRENCY:-2}" \
    --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
