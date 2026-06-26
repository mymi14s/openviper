# FX Tracker

A Foreign Exchange (FX) tracker application built with the OpenViper framework. This example demonstrates database integration, model definition, and the auto-generated migration system using a PostgreSQL database.

## Features

- **Database Persistence:** Uses a PostgreSQL backend with models for currency exchange rates and historical tracks.
- **Auto-Migrations:** Runs `openviper viperctl migrate` on startup to synchronize JSON database schemas automatically.
- **Exchange Tracking:** Models exchange rates and logs currency fluctuations.

## Project Structure

```
fx/
├── schemas/            # Auto-generated database JSON schema definitions
├── app.py              # Application setup and routes
├── models.py           # Currency exchange rate database models
├── settings.py         # App configurations (database connections, etc.)
├── Dockerfile          # Application Docker image configuration
└── docker-compose.yml  # Docker Compose file
```

## Running with Docker Compose

This project runs OpenViper with a persistent PostgreSQL database.

### 1. Start the Services

Build and run the application and database containers:

```bash
docker compose up --build
```

On startup, the container will automatically run the migrations to create the database tables.

### 2. Access the Application

- **Base Endpoint:** `http://localhost:8000/`
- **Swagger API Docs:** `http://localhost:8000/open-api/docs`
