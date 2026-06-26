"""Admin site serving - mount admin SPA and API at /admin.

DEBUG=True mounts SPA frontend routes; DEBUG=False delegates to reverse proxy.
API routes (/api/*) are always mounted.
"""

from __future__ import annotations

import importlib.util
import typing as t
from pathlib import Path
from typing import TYPE_CHECKING

from openviper.admin.api import get_admin_router
from openviper.admin.discovery import autodiscover, discover_extensions
from openviper.conf import settings
from openviper.exceptions import NotFound
from openviper.http.response import FileResponse, HTMLResponse, JSONResponse, Response
from openviper.routing.router import Router, include

if TYPE_CHECKING:
    from openviper.http.request import Request

ADMIN_STATIC_DIR = Path(__file__).parent / "static/admin"


def get_admin_site() -> Router:
    """Create and return the complete admin site router.

    Returns:
        Router with all admin site endpoints.
    """

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
            base_dir = (Path(spec.origin).parent / "admin_extensions").resolve()
            ext_file = (base_dir / path).resolve()
            # Prevent path traversal - resolved path must stay inside base_dir
            if not str(ext_file).startswith(str(base_dir) + "/") and ext_file != base_dir:
                raise NotFound("Invalid extension path")
            if not ext_file.exists() or not ext_file.is_file():
                raise NotFound(f"Extension file not found: {app_name}/{path}")
            if ext_file.suffix not in {".js", ".vue"}:
                raise NotFound("Only .js and .vue extension files are allowed")
        except NotFound:
            raise
        except Exception:
            raise NotFound(f"Extension not found: {app_name}/{path}") from None
        return FileResponse(str(ext_file))

    async def serve_admin_index(request: Request) -> FileResponse | HTMLResponse:
        """Serve the admin SPA index.html for the root."""
        project_index_path = Path(getattr(settings, "STATIC_ROOT", "static")) / "admin/index.html"
        if project_index_path.exists() and project_index_path.is_file():
            return FileResponse(str(project_index_path))

        index_path = ADMIN_STATIC_DIR / "index.html"
        if not index_path.exists():
            if not getattr(settings, "DEBUG", False):
                return Response(status_code=404)
            return HTMLResponse(
                "<h1>Admin Not Built</h1>"
                "<p>Run <code>cd admin_frontend && npm run build</code>"
                " to build the admin panel.</p>",
                status_code=500,
            )
        return FileResponse(str(index_path))

    async def serve_admin_spa(request: Request, path: str = "") -> FileResponse | HTMLResponse:
        """Serve the admin SPA index.html for all routes (client-side routing)."""
        project_index_path = Path(getattr(settings, "STATIC_ROOT", "static")) / "admin/index.html"
        if project_index_path.exists() and project_index_path.is_file():
            return FileResponse(str(project_index_path))

        index_path = ADMIN_STATIC_DIR / "index.html"
        if not index_path.exists():
            if not getattr(settings, "DEBUG", False):
                return Response(status_code=404)
            return HTMLResponse(
                "<h1>Admin Not Built</h1>"
                "<p>Run <code>cd admin_frontend && npm run build</code>"
                " to build the admin panel.</p>",
                status_code=500,
            )
        return FileResponse(str(index_path))

    async def serve_admin_asset(request: Request, path: str) -> FileResponse:
        """Serve a static asset from the admin's static/admin/assets dir."""
        base_dir = (ADMIN_STATIC_DIR / "assets").resolve()
        asset_file = (base_dir / path).resolve()
        # Prevent path traversal - resolved path must stay inside base_dir
        if not str(asset_file).startswith(str(base_dir) + "/") and asset_file != base_dir:
            raise NotFound("Asset not found")
        if not asset_file.exists() or not asset_file.is_file():
            raise NotFound("Asset not found")
        return FileResponse(str(asset_file))

    api_router = get_admin_router()
    router.include_router(include(api_router, prefix="/api"))

    router.add("/api/extensions/", list_extensions, methods=["GET"])

    if getattr(settings, "DEBUG", False):
        router.add(
            "/extensions/{app_name}/{path:path}",
            serve_extension_file,
            methods=["GET", "HEAD"],
        )
        router.add("/assets/{path:path}", serve_admin_asset, methods=["GET", "HEAD"])
    else:

        async def silent_404(request: Request, **kwargs: t.Any) -> Response:
            return Response(status_code=404)

        router.add(
            "/extensions/{path:path}",
            silent_404,
            methods=["GET", "HEAD"],
            namespace="admin_silent_404_extensions",
        )
        router.add(
            "/assets/{path:path}",
            silent_404,
            methods=["GET", "HEAD"],
            namespace="admin_silent_404_assets",
        )

    spa_router = Router()
    spa_router.add("/", serve_admin_index, methods=["GET", "HEAD"])
    spa_router.add("/{path:path}", serve_admin_spa, methods=["GET", "HEAD"])
    router.include_router(spa_router)

    return router
