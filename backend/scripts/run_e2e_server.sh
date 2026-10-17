#!/bin/bash
set -e
cd "$(dirname "$0")/.."

export DATABASE_URL=sqlite:///./e2e.db
export CORS_ORIGINS=http://localhost:5174
export MIN_LEAD_MINUTES=1

rm -f e2e.db
. .venv/bin/activate
alembic upgrade head
python scripts/seed_e2e.py
exec uvicorn app.main:app --port 8001
