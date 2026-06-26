# TodoApp

A classic, simple TODO application built using OpenViper. It showcases SQLite database persistence (default locally) and MariaDB database persistence (when run in Docker), along with Jinja2 HTML templates and the auto-discovered ModelAdmin interface.

## Features

- **Task Management:** Create, toggle, edit, and delete tasks.
- **Admin UI:** Uses OpenViper's core model registry to register and manage task objects inside the Admin Panel.
- **Relational Backend:** Includes setup and migrations configuration for MariaDB.
- **Static Assets:** Utilizes CSS/JS assets served via OpenViper static routes.

## Project Structure

```
todoapp/
├── admin.py            # Registers task models to the OpenViper admin
├── app.py              # Application initialization and routes
├── create_admin.py     # Script to bootstrap administrative users
├── models.py           # Task database models
├── settings.py         # Configs (such as databases and admin credentials)
├── templates/          # Jinja2 templates (index.html, base.html)
├── static/             # Static files (CSS style sheets)
├── Dockerfile          # Application Docker image configuration
└── docker-compose.yml  # Docker Compose file
```

## Running with Docker Compose

This project contains a Docker Compose setup that provisions the OpenViper ASGI application, a MariaDB database server, and an Nginx reverse proxy.

### 1. Start the Services

Build and run all services with:

```bash
docker compose up --build
```

On start, the container will run migrations automatically to build the tables in MariaDB.

### 2. Create a Superuser (Optional)

To access the Admin UI, you will need to create a superuser. Run the following command in a new terminal window inside the `examples/todoapp` directory:

```bash
docker compose exec web python create_admin.py
```

Follow the prompts to enter your username, email, and password.

### 3. Access the Application

- **Web Frontend:** `http://localhost:8080` (served through Nginx)
- **OpenViper Admin Panel:** `http://localhost:8080/admin`
- **Admin:** `http://localhost:8080/admin`
- **Swagger API Docs:** `http://localhost:8080/open-api/docs`
