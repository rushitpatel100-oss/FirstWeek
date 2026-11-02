#!/bin/sh
# Start the API in production: migrate the database, make sure the demo project is there (its
# files live on this container's disk, so they are restored after a restart), then serve.
# Set SEED_DEMO_ROLE (for example "GenAI Engineer") to seed; leave it unset to skip.
set -eu
alembic -c packages/core/alembic.ini upgrade head
if [ -n "${SEED_DEMO_ROLE:-}" ]; then
  python -m firstweek_simulation ensure-demo --role "${SEED_DEMO_ROLE}"
fi
exec uvicorn firstweek_api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
