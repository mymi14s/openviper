# Flexible Single-File Application

A minimal, decorator-based routing application showcasing OpenViper's core functionality in a single script. It uses standard Python dictionaries and in-memory lists as a simple database, making it fully stateless and ideal for lightweight use cases.

## Features

- **Single-File Setup:** Configures and runs routes directly within `app.py`.
- **Stateless/In-Memory:** Stores user and task data in memory, requiring no database setup.
- **Decorator Routing:** Demonstrates basic routing decorators (`@app.get`, `@app.post`, etc.).
- **Response Types:** Showcases returning dynamic responses like `JSONResponse` and standard JSON dictionary objects.

## Project Structure

```
flexible/
├── app.py              # Main single-file application containing routes and config
├── Dockerfile          # Application Docker image configuration
└── docker-compose.yml  # Docker Compose file
```

## Running with Docker Compose

This project runs completely self-contained in a single container. Since there is no database or other dependencies, no additional configuration is required.

### 1. Start the Service

Start the web server using Docker Compose:

```bash
docker compose up --build
```

### 2. Access the Application

Once the service is running, you can interact with it at:
- **Base Endpoint:** `http://localhost:8000/`
- **Swagger API Docs:** `http://localhost:8000/open-api/docs`
- **ReDoc API Docs:** `http://localhost:8080/open-api/redoc`
