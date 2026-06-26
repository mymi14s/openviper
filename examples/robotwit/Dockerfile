FROM node:24-slim AS frontend-builder

WORKDIR /frontend

COPY examples/robotwit/frontend/package.json examples/robotwit/frontend/package-lock.json* ./
RUN npm install

COPY examples/robotwit/frontend/ ./
RUN npm run build


FROM python:3.14-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*


ARG OPENVIPER_EXTRAS="postgres,tasks-redis,ai"
RUN pip install --no-cache-dir openviper[${OPENVIPER_EXTRAS}]"

COPY examples/robotwit/ /app/

COPY --from=frontend-builder /frontend/build/index.html /app/templates/index.html
COPY --from=frontend-builder /frontend/build/assets /app/static/assets

ENV OPENVIPER_SETTINGS_MODULE=robotwit.settings

EXPOSE 8000

CMD ["uvicorn", "robotwit.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
