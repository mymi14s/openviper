#!/bin/sh
# Production entrypoint
# Runs collectstatic then starts uvicorn bound to all interfaces (0.0.0.0)

set -e

echo "→ Collecting static files..."
python viperctl.py collectstatic --no-input

echo "→ Migrating database..."
python viperctl.py migrate

echo "→ Starting uvicorn on 0.0.0.0:8000..."
exec python -m uvicorn tp.asgi:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --no-access-log
