"""OpenViper CLI — global ``openviper`` command.

Provides project scaffolding commands separate from the per-project
``viperctl.py`` interface.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

try:
    from rich.console import Console
    from rich.panel import Panel

    _console = Console()
    _has_rich = True
except ImportError:
    _console = None  # type: ignore[assignment]
    _has_rich = False

import openviper
from openviper.conf.settings import generate_secret_key
from openviper.core.management.base import BaseCommand
from openviper.core.management.utils import get_banner
from openviper.viperctl import viperctl as _viperctl_cmd


def _print(msg: str, style: str = "") -> None:
    if _has_rich and _console:
        _console.print(msg, style=style or None)
    else:
        print(msg)


@click.group()
@click.version_option(package_name="openviper", prog_name="openviper")
def cli() -> None:
    """OpenViper web framework CLI."""


_VERPERCTL_PY_TEMPLATE = '''\
#!/usr/bin/env python
"""OpenViper viperctl.py for {project_name}."""

import sys
from openviper.core.management import execute_from_command_line

def main() -> None:
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()

'''

_SETTINGS_TEMPLATE = '''\
"""Settings for {project_name}."""
from __future__ import annotations

import dataclasses
import os
from datetime import timedelta
from typing import Any

from openviper.conf.settings import Settings

@dataclasses.dataclass(frozen=True)
class ProjectSettings(Settings):
    PROJECT_NAME: str = "{project_name}"
    DEBUG: bool = bool(os.environ.get("DEBUG", "1"))
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///db.sqlite3")
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "{secret_key}")
    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
    )
    MIDDLEWARE: tuple[str, ...] = (
        "openviper.middleware.security.SecurityMiddleware",
        "openviper.middleware.cors.CORSMiddleware",
        "openviper.auth.session.middleware.SessionMiddleware",
        "openviper.middleware.auth.AuthenticationMiddleware",
        "openviper.admin.middleware.AdminMiddleware",
    )
    ALLOWED_HOSTS: tuple[str, ...] = ("*",)
    STATIC_ROOT: str = os.environ.get("STATIC_ROOT", "static")
    STATIC_URL: str = os.environ.get("STATIC_URL", "/static/")
    MEDIA_ROOT: str = os.environ.get("MEDIA_ROOT", "media")
    MEDIA_URL: str = os.environ.get("MEDIA_URL", "/media/")

    # # Background Tasks
    # TASKS: dict[str, Any] = dataclasses.field(
    #     default_factory=lambda: {{
    #         "enabled": 0,
    #         "scheduler_enabled": 0,
    #         "tracking_enabled": 1,
    #         "log_to_file": 1,
    #         "log_level": "DEBUG",
    #         "log_format": "json",
    #         "log_dir": "logs",
    #         "broker": "redis",
    #         "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    #         "backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
    #     }}
    # )

    # # Model events configuration: maps "app.model" to event hooks to lists of
    # # "app.events.func" paths.
    # MODEL_EVENTS: dict = dataclasses.field(
    #     default_factory=lambda: {{
    #         "posts.models.Post": {{
    #             "after_insert": ["posts.events.create_likes"],
    #             "after_delete": ["posts.events.cleanup_comments"],
    #             "on_update": ["posts.events.handle_post_update"],
    #         }},
    #     }}
    # )
'''

_ASGI_TEMPLATE = '''\

"""ASGI application for {project_name}."""

from __future__ import annotations

import os
import sys

import openviper
from openviper.app import OpenViper

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "{project_name}.settings")


# Create application
app = OpenViper()

'''

_ROUTES_TEMPLATE = '''\
"""Top-level routes for {project_name}."""

from openviper.conf import settings
from openviper.admin import get_admin_site
from openviper.staticfiles import media, static

from {project_name}.views import router as root_router

route_paths = [
    ("/admin", get_admin_site()),
    ("/root", root_router)
]

# to force static files serving in production, not recommended
if not settings.DEBUG:
    route_paths += static() + media()
'''

_VIEWS_TEMPLATE = '''
"""Views for {project_name}."""

from openviper.http.response import HTMLResponse, JSONResponse
from openviper.routing import Router

async def home(request):
    """Home page view."""
    context = {{
        "title": "Welcome to {project_name}",
        "project_name": "{project_name}",
        "message": "Your OpenViper project is running successfully."
    }}
    return HTMLResponse(template="home.html", context=context)

async def api_index(request):
    """API endpoint view that handles both GET and POST."""
    if request.method == "GET":
        return JSONResponse({{
            "message": "Welcome to {project_name} API!",
            "status": "success"
        }})
    elif request.method == "POST":
        return JSONResponse({{
            "message": "Data received",
            "status": "success",
            "method": "POST"
        }})
    else:
        return JSONResponse({{
            "error": "Method not allowed",
            "status": "error"
        }}, status_code=405)

# Routes for apps should be in each app's routes.py file
router = Router()

# Default routes for {project_name}
router.add("/home", home, namespace="home-view")
router.add("/api", api_index, namespace="api-view", methods=["GET", "POST"])
'''

_HOME_TEMPLATE_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ title }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1 { color: #333; }
        ul { list-style-type: none; padding: 0; }
        li { margin: 10px 0; }
        a { color: #007bff; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h1>Welcome to {{ project_name }}!</h1>
    <p>{{ message }}</p>
    <ul>
        <li><a href="/api">API Endpoint</a></li>
        <li><a href="/admin">Admin Panel</a></li>
    </ul>
</body>
</html>
"""

_PROJECT_INIT_TEMPLATE = '"""{project_name} project."""\n'

_GITIGNORE_TEMPLATE = """\
__pycache__/
*.py[cod]
*.egg-info/
.env
.venv/
venv/
db.sqlite3
*.log
.DS_Store
"""


@cli.command("create-project")
@click.argument("name")
@click.option("--directory", "-d", default=None, help="Parent directory (default: CWD)")
def create_project(name: str, directory: str | None) -> None:
    """Scaffold a new OpenViper project called NAME."""
    if not name.isidentifier():
        click.echo(f"Error: '{name}' is not a valid Python identifier.", err=True)
        sys.exit(1)

    base = Path(directory) if directory else Path.cwd()
    project_root = base / name

    if project_root.exists():
        click.echo(f"Error: '{project_root}' already exists.", err=True)
        sys.exit(1)

    secret_key = generate_secret_key()
    ctx = {"project_name": name, "secret_key": secret_key}

    # Create directory structure
    (project_root / name).mkdir(parents=True)

    def write(path: Path, content: str) -> None:
        path.write_text(content.format(**ctx))

    write(project_root / "viperctl.py", _VERPERCTL_PY_TEMPLATE)
    os.chmod(project_root / "viperctl.py", 0o755)
    write(project_root / name / "__init__.py", _PROJECT_INIT_TEMPLATE)
    write(project_root / name / "settings.py", _SETTINGS_TEMPLATE)
    write(project_root / name / "asgi.py", _ASGI_TEMPLATE)
    write(project_root / name / "routes.py", _ROUTES_TEMPLATE)
    write(project_root / name / "views.py", _VIEWS_TEMPLATE)
    write(project_root / ".gitignore", _GITIGNORE_TEMPLATE)
    (project_root / "static").mkdir()
    (project_root / "templates").mkdir()
    (project_root / "templates" / "home.html").write_text(_HOME_TEMPLATE_HTML)
    (project_root / "tests").mkdir()
    (project_root / "tests" / "__init__.py").write_text("# Test package\n\n")

    if _has_rich:
        _console.print(
            Panel.fit(
                f"[bold green]Project '{name}' created![/bold green]\n\n"
                f"  [cyan]cd {name}[/cyan]\n"
                f"  [cyan]python viperctl.py runserver[/cyan]",
                title="OpenViper",
            )
        )
    else:
        click.echo(f"Project '{name}' created at {project_root}")
        click.echo(f"  cd {name}")
        click.echo("  python viperctl.py runserver")


@cli.command("create-app")
@click.argument("name")
@click.option("--directory", "-d", default=None, help="Target directory (default: CWD)")
def create_app(name: str, directory: str | None) -> None:
    """Scaffold a new app inside an existing OpenViper project."""
    # Delegate to the management command so it works both ways

    args = [sys.executable, "viperctl.py", "create-app", name]
    if directory:
        args += ["--directory", directory]
    subprocess.run(args, check=False)


@cli.command("run")
@click.argument("target")
@click.option("--host", "-h", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", "-p", default=8000, show_default=True, type=int, help="Bind port.")
@click.option(
    "--reload/--no-reload",
    default=True,
    help="Enable/disable auto-reload on file changes (default: --reload).",
)
@click.option(
    "--workers",
    "-w",
    default=1,
    show_default=True,
    type=int,
    help="Number of worker processes (ignored when --reload is set).",
)
def run_cmd(target: str, host: str, port: int, reload: bool, workers: int) -> None:
    """Run an OpenViper application with uvicorn.

    TARGET is the module (or module:attr) that contains the application:

    \b
      openviper run app
      openviper run app.py
      openviper run myproject.asgi:app
    """
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "Error: uvicorn is required.  Install it with: pip install uvicorn",
            err=True,
        )
        sys.exit(1)

    # Accept "app.py" as well as "app"
    if target.endswith(".py"):
        target = target[:-3]

    # Support "module:attr"; default attr is "app"
    if ":" in target:
        module_str, attr_str = target.split(":", 1)
    else:
        module_str, attr_str = target, "app"

    # Make sure the current directory is on sys.path so bare module names resolve
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    get_banner(BaseCommand(), host, port)
    uvicorn.run(
        f"{module_str}:{attr_str}",
        host=host,
        port=port,
        reload=reload,
        # uvicorn rejects workers > 1 when reload is enabled
        workers=1 if reload else workers,
    )


@cli.command("version")
def version_cmd() -> None:
    """Print OpenViper version."""

    click.echo(f"OpenViper {openviper.__version__}")


cli.add_command(_viperctl_cmd)

if __name__ == "__main__":
    cli()
