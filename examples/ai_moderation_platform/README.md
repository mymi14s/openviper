# AI Moderation Platform

An AI-powered content moderation platform built with the OpenViper framework. This example demonstrates how to use OpenViper's ORM model lifecycle hooks and background task worker to automatically moderate user-generated posts using a generative AI backend.

## Features

- **Post Moderation:** Auto-moderates user posts using Gemini (or other AI providers via the OpenViper AI Registry).
- **Background Tasks:** Enqueues moderation checks asynchronously using Dramatiq and Redis.
- **Model Lifecycle Hooks:** Uses ORM hooks like `after_insert` to trigger moderation immediately after post creation.
- **Admin UI Integration:** Track post status, moderation logs, and configure moderation thresholds from the Admin panel.
- **Database Support:** Includes configurations for PostgreSQL, MariaDB, SQLite, MS SQL, and Oracle.

## Project Structure

```
ai_moderation_platform/
├── ai_moderation_platform/  # Project settings and configurations
├── moderation/              # Moderation logic, models, and AI integration
├── posts/                   # Post models, views, and forms
├── users/                   # User and profile models
├── templates/               # HTML templates
├── static/                  # Static assets
├── viperctl.py              # OpenViper CLI management entrypoint
└── Dockerfile               # Application Docker image configuration
```

## Running with Docker Compose

This project supports multiple database engines via Docker Compose. The default environment uses MariaDB, but configurations for PostgreSQL, SQLite, MS SQL, and Oracle are also provided.

### 1. Set your AI API Key

Create a `.env` file in the root of the project (`examples/ai_moderation_platform/.env`) and add your Gemini API key (or relevant AI provider credentials):

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 2. Start the Services

Choose one of the commands below depending on your preferred database backend:

#### MariaDB
```bash
docker compose up -f docker-compose.mariadb.yml --build
```

#### PostgreSQL
```bash
docker compose -f docker-compose.postgres.yml up --build
```

#### SQLite
```bash
docker compose -f docker-compose.sqlite.yml up --build
```

#### MS SQL Server
```bash
docker compose -f docker-compose.mssql.yml up --build
```

#### Oracle
```bash
docker compose -f docker-compose.oracle.yml up --build
```

### 3. Access the Application

Once the services are healthy:
- **Web App / Admin Panel:** `http://localhost:8080` (proxying through Nginx to the ASGI application)
- **Admin:** `http://localhost:8080/admin`
- **Swagger API Docs:** `http://localhost:8080/open-api/docs`
