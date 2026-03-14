# ─── Base image ───────────────────────────────────────────────────────────────
FROM python:3.14-slim AS base

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies

COPY openviper-0.0.1-py3-none-any.whl ./
RUN pip install --no-cache-dir openviper-0.0.1-py3-none-any.whl

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

CMD ["python", "viperctl.py", "runserver", "--host", "0.0.0.0", "--port", "8000"]


# ─── Production stage ─────────────────────────────────────────────────────────
FROM base AS production

# Production entrypoint: collectstatic + uvicorn bound to 0.0.0.0
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
