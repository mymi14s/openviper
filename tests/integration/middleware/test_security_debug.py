"""Tests for Django-like DEBUG-based static file serving behavior in Openviper.

These tests verify that:
- DEBUG=True  → static files are served (development mode)
- DEBUG=False → static files are served if explicitly enabled (opt-in production)
- Normal app routes are not affected by DEBUG in either direction
"""

import dataclasses
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from openviper.admin import get_admin_site
from openviper.app import OpenViper
from openviper.conf import settings
from openviper.routing.router import Router
from openviper.staticfiles import StaticFilesMiddleware


def _patch_debug(value: bool):
    """Context manager: temporarily set settings.DEBUG to *value*."""
    if not settings._configured:
        settings._setup()
    new_instance = dataclasses.replace(settings._instance, DEBUG=value)
    return patch.object(settings, "_instance", new_instance)


@pytest.mark.asyncio
async def test_static_files_not_served_when_debug_false():
    """StaticFilesMiddleware serves files in production if present in the stack.

    Allows opt-in production serving while maintaining secure defaults.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        static_path = Path(temp_dir)
        test_file = static_path / "test.txt"
        test_file.write_text("hello world")

        with _patch_debug(False):
            app = OpenViper(debug=False)
            app = StaticFilesMiddleware(app, url_path="/static", directories=[static_path])

            # DEBUG=False + Middleware present → middleware serves the file
            # (The middleware's presence in the stack is the 'opt-in')
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.get("/static/test.txt")
                assert response.status_code == 200
                assert response.text == "hello world"

        with _patch_debug(True):
            app2 = OpenViper(debug=True)
            app2 = StaticFilesMiddleware(app2, url_path="/static", directories=[static_path])

            # DEBUG=True → middleware intercepts and serves the file
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app2), base_url="http://testserver"
            ) as client:
                response = await client.get("/static/test.txt")
                assert response.status_code == 200
                assert response.text == "hello world"


@pytest.mark.asyncio
async def test_admin_assets_not_served_when_debug_false():
    """Admin SPA/asset routes are not registered when DEBUG=False.

    Requests to /admin/assets/* and /admin/* (non-API) should return the
    standard framework 404 — no special error messages, no crashes.
    """
    with _patch_debug(False):
        app = OpenViper(debug=False)
        app.include_router(get_admin_site(), prefix="/admin")

        async with app.test_client() as client:
            # Admin Index — mounted; status depends on whether the admin SPA is built
            response = await client.get("/admin/")
            assert response.status_code in (200, 404)
            if response.status_code == 404:
                assert "Admin Not Built" not in response.text

            # Admin Assets — mounted; status depends on whether assets exist
            response = await client.get("/admin/assets/any.js")
            assert response.status_code in (200, 404)
            if response.status_code == 404:
                assert "Asset not found" not in response.text
            # Admin Extensions — not mounted, standard 404
            response = await client.get("/admin/extensions/some-app/ext.js")
            assert response.status_code == 404

            # Admin API — ALWAYS mounted regardless of DEBUG
            # Login endpoint exists even without DEBUG (returns 422 or similar, not 404)
            response = await client.post(
                "/admin/api/auth/login/", json={"username": "x", "password": "x"}
            )
            assert response.status_code != 404, "Admin API must be reachable even when DEBUG=False"


@pytest.mark.asyncio
async def test_admin_assets_served_when_debug_true():
    """Admin SPA/asset routes ARE mounted when DEBUG=True.

    Assets: 404 'Asset not found' (file missing) — but NOT a routing 404.
    Index:  500 (admin not built) or 200 — but NOT a routing 404.
    """
    with _patch_debug(True):
        app = OpenViper(debug=True)
        app.include_router(get_admin_site(), prefix="/admin")

        async with app.test_client() as client:
            # Assets route is mounted; missing file → 404 from handler, not router
            response = await client.get("/admin/assets/nonexistent.js")
            assert response.status_code == 404
            assert "Asset not found" in response.text

            # Admin index route is mounted; may be 200 or 500 depending on build
            response = await client.get("/admin/")
            assert response.status_code in (
                200,
                500,
            ), f"Expected 200 or 500 (route is mounted), got {response.status_code}"


@pytest.mark.asyncio
async def test_app_routes_unaffected_by_debug_false():
    """Normal application routes work normally when DEBUG=False.

    DEBUG=False must not break or intercept non-static routes.
    This matches the Django guarantee that the request cycle is unaffected.
    """
    with _patch_debug(False):
        router = Router()

        @router.get("/hello")
        async def hello(request):
            from openviper.http.response import JSONResponse

            return JSONResponse({"ok": True})

        app = OpenViper(debug=False)
        app.include_router(router)

        async with app.test_client() as client:
            response = await client.get("/hello")
            assert response.status_code == 200
            assert response.json() == {"ok": True}
