# ─── Base image ───────────────────────────────────────────────────────────────
FROM python:3.14-slim AS base

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies

RUN pip install --no-cache-dir "openviper[postgres,mariadb]==0.0.9"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENVIPER_SETTINGS_MODULE=tp.settings


# ─── Development stage ────────────────────────────────────────────────────────
FROM base AS development

EXPOSE 8000

CMD ["python", "viperctl.py", "start-server", "--host", "0.0.0.0", "--port", "8000"]


# ─── Production stage ─────────────────────────────────────────────────────────
FROM base AS production

# Production entrypoint: collectstatic + uvicorn bound to 0.0.0.0
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
