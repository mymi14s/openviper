"""Admin site serving — mount admin SPA and API at /admin.

This module implements Django-like DEBUG-based static serving:

- **DEBUG=True (development)**: Admin SPA frontend routes (/, /assets/*, /extensions/*)
  are mounted and served directly by the framework.

- **DEBUG=False (production)**: Static and SPA routes are NOT registered.
  Requests to those paths fall through the routing system and return the
  standard 404. The admin REST API routes (/api/*) are always mounted.
  In production, the admin frontend should be built and served by a
  reverse proxy (e.g. nginx), not by the framework itself.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openviper.admin.api import get_admin_router
from openviper.admin.discovery import autodiscover, discover_extensions
from openviper.conf import settings
from openviper.exceptions import NotFound
from openviper.http.response import FileResponse, HTMLResponse, JSONResponse, Response
from openviper.routing.router import Router, include

if TYPE_CHECKING:
    from openviper.http.request import Request

# Path to built admin static files
ADMIN_STATIC_DIR = Path(__file__).parent / "static/admin"


def get_admin_site() -> Router:
    """Create and return the complete admin site router.

    This includes:
    - The admin API routes at /api/
    - Static asset serving at /assets/
    - SPA fallback serving index.html for all other routes

    Returns:
        Router with all admin site endpoints.

    Example:
        .. code-block:: python

            from openviper import OpenViper
            from openviper.admin.site import get_admin_site

            app = OpenViper()
            app.include_router(get_admin_site(), prefix="/admin")
    """

    # Auto-discover admin modules from installed apps
    autodiscover()

    router = Router()

    async def list_extensions(request: Request) -> JSONResponse:
        """Return a JSON manifest of all discovered admin extensions."""

        exts = discover_extensions()
        return JSONResponse(
            {
                "extensions": [
                    {
                        "app": e["app"],
                        "file": e["file"],
                        "url": e["url"],
                        "type": e["type"],
                    }
                    for e in exts
                ]
            }
        )

    async def serve_extension_file(request: Request, app_name: str, path: str) -> FileResponse:
        """Serve a drop-in JS extension file from an app's admin_extensions/ dir."""
        try:
            spec = importlib.util.find_spec(app_name)
            if spec is None or spec.origin is None:
                raise NotFound(f"App not found: {app_name}")
            ext_file = Path(spec.origin).parent / "admin_extensions" / path
            if not ext_file.exists() or not ext_file.is_file():
                raise NotFound(f"Extension file not found: {app_name}/{path}")
            # Security: only allow .js and .vue files
            if ext_file.suffix not in {".js", ".vue"}:
                raise NotFound("Only .js and .vue extension files are allowed")
        except NotFound:
            raise
        except Exception:
            raise NotFound(f"Extension not found: {app_name}/{path}")
        return FileResponse(str(ext_file))

    async def serve_admin_index(request: Request) -> FileResponse | HTMLResponse:
        """Serve the admin SPA index.html for the root."""
        # 1. Try project-level index first
        project_index_path = Path(getattr(settings, "STATIC_ROOT", "static")) / "admin/index.html"
        if project_index_path.exists() and project_index_path.is_file():
            return FileResponse(str(project_index_path))

        # 2. Fallback to framework's built-in index
        index_path = ADMIN_STATIC_DIR / "index.html"
        if not index_path.exists():
            if not getattr(settings, "DEBUG", False):
                return Response(status_code=404)
            return HTMLResponse(
                "<h1>Admin Not Built</h1>"
                "<p>Run <code>cd admin_frontend && npm run build</code> to build the admin panel.</p>",
                status_code=500,
            )
        return FileResponse(str(index_path))

    async def serve_admin_spa(request: Request, path: str = "") -> FileResponse | HTMLResponse:
        """Serve the admin SPA index.html for all routes (client-side routing)."""
        # 1. Try project-level index first
        project_index_path = Path(getattr(settings, "STATIC_ROOT", "static")) / "admin/index.html"
        if project_index_path.exists() and project_index_path.is_file():
            return FileResponse(str(project_index_path))

        # 2. Fallback to framework's built-in index
        index_path = ADMIN_STATIC_DIR / "index.html"
        if not index_path.exists():
            if not getattr(settings, "DEBUG", False):
                return Response(status_code=404)
            return HTMLResponse(
                "<h1>Admin Not Built</h1>"
                "<p>Run <code>cd admin_frontend && npm run build</code> to build the admin panel.</p>",
                status_code=500,
            )
        return FileResponse(str(index_path))

    async def serve_admin_asset(request: Request, path: str) -> FileResponse:
        """Serve a static asset from the admin's static/admin/assets dir."""
        asset_file = ADMIN_STATIC_DIR / "assets" / path
        if not asset_file.exists() or not asset_file.is_file():
            raise NotFound("Asset not found")
        return FileResponse(str(asset_file))

    # API endpoints (Always present)
    api_router = get_admin_router()
    router.include_router(include(api_router, prefix="/api"))

    # Extension manifest is part of the API
    router.add("/api/extensions/", list_extensions, methods=["GET"])

    # Extension file serving is DEBUG-only (reads arbitrary app files from disk).
    if getattr(settings, "DEBUG", False):
        router.add(
            "/extensions/{app_name}/{path:path}",
            serve_extension_file,
            methods=["GET", "HEAD"],
        )
        # Admin assets are also DEBUG-only in the app (nginx serves them in prod)
        router.add("/assets/{path:path}", serve_admin_asset, methods=["GET", "HEAD"])
    else:
        # In production, ensure these prefixes don't fall through to the SPA catch-all.
        # This allows Nginx to handle them or returns a clean 404 if they reach the app.
        async def silent_404(request: Request, **kwargs: Any) -> Response:
            return Response(status_code=404)

        router.add("/extensions/{path:path}", silent_404, methods=["GET", "HEAD"])
        router.add("/assets/{path:path}", silent_404, methods=["GET", "HEAD"])

    # SPA HTML routes — always mounted so the admin is reachable.
    # We mount these in a sub-router so they are evaluated AFTER everything else.
    spa_router = Router()
    spa_router.add("/", serve_admin_index, methods=["GET", "HEAD"])
    spa_router.add("/{path:path}", serve_admin_spa, methods=["GET", "HEAD"])
    router.include_router(spa_router)

    return router
