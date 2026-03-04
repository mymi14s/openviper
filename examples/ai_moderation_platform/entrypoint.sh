#!/bin/sh
# Production entrypoint
# Runs collectstatic then starts uvicorn bound to all interfaces (0.0.0.0)

set -e

echo "→ Collecting static files..."
python viperctl.py collectstatic --no-input

echo "→ Migrating database..."
python viperctl.py migrate

# If a custom command is passed, run it instead of uvicorn
if [ $# -gt 0 ]; then
    echo "→ Running custom command: $@"
    exec "$@"
fi

echo "→ Starting uvicorn on 0.0.0.0:8000..."
exec python -m uvicorn ai_moderation_platform.asgi:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --no-access-log
