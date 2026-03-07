#!/usr/bin/env bash
# scripts/create_projects.sh
# Scaffold isolated virtual environments and install dependencies for each
# benchmark framework. Run from benchmark_frameworks/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# ---------- OpenViper ----------
log "Setting up openviper_blog"
cd "$ROOT/openviper_blog"
python3.14 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
# Run migrations via viperctl
cd "$ROOT/openviper_blog"
openviper viperctl --settings settings makemigrations .
openviper viperctl --settings settings migrate .
deactivate

# ---------- FastAPI ----------
log "Setting up fastapi_blog"
cd "$ROOT/fastapi_blog"
python3.14 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
deactivate

# ---------- Flask ----------
log "Setting up flask_blog"
cd "$ROOT/flask_blog"
python3.14 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
deactivate

# ---------- Django ----------
log "Setting up django_blog"
cd "$ROOT/django_blog"
python3.14 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
python manage.py migrate --run-syncdb
deactivate

log "All environments ready."
