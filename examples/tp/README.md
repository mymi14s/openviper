# TP (Test Project Scaffold)

A test project scaffold showcasing OpenViper's standard modular directory layout. It includes a custom app (`blog`), database configurations, unit tests under `pytest`, and static/media asset structures with PostgreSQL persistence.

## Features

- **Standard Project Layout:** Uses the default structure scaffolded by `openviper create-project` and `openviper create-app`.
- **Modular Apps:** Demonstrates a distinct `blog` app packaging models and views separately.
- **PostgreSQL Database:** Integrated with PostgreSQL via asyncpg driver support.
- **Static and Media Assets:** Fully configured paths for media uploads and collectstatic assets.
- **Testing Setup:** Configured `test_settings.py` for testing databases independently.

## Project Structure

```
tp/
├── blog/               # Custom blog application module
├── tp/                 # Main settings, configurations, and ASGI setup
├── tests/              # Test cases for the application
├── test_settings.py    # Test-specific settings configuration
├── viperctl.py         # Management command CLI script
├── Dockerfile          # Application Docker image configuration
└── docker-compose.yml  # Docker Compose file
```

## Running with Docker Compose

This project contains a Docker Compose environment that provisions the OpenViper web application, a PostgreSQL database server, and an Nginx reverse proxy.

### 1. Start the Services

Build and run all services with:

```bash
docker compose up --build
```

On start, the container will run migrations automatically to build the tables in PostgreSQL.

### 2. Access the Application

- **Web Frontend:** `http://localhost:8080` (served through Nginx)
- **Admin:** `http://localhost:8080/admin`
- **Swagger API Docs:** `http://localhost:8080/open-api/docs`
