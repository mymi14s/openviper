# ─── Base image ───────────────────────────────────────────────────────────────
# Root-layout example - SQLite database, no background tasks.
FROM python:3.14-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install OpenViper from the prebuilt wheel in dist/.

RUN pip install --no-cache-dir "/tmp/openviper-0.1.1-py3-none-any.whl[postgres]" \
    && rm -f /tmp/openviper-0.1.1-py3-none-any.whl

COPY examples/fx/ /app/

ENV OPENVIPER_SETTINGS_MODULE=settings

EXPOSE 8000
