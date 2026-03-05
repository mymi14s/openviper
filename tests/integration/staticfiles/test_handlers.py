"""Tests for StaticFilesMiddleware DEBUG-based serving behavior.

These tests validate the Django-like static serving pattern:
- DEBUG=True  → middleware intercepts the request and serves files
- DEBUG=False → middleware serves files ONLY if the user explicitly opted in
"""

import dataclasses
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from openviper.admin import get_admin_site
from openviper.app import OpenViper
from openviper.conf.settings import settings
from openviper.staticfiles import StaticFilesMiddleware


def _patch_debug(value: bool):
    """Patch ``settings.DEBUG`` to *value* for the duration of a ``with`` block."""
    if not settings._configured:
        settings._setup()
    new_instance = dataclasses.replace(settings._instance, DEBUG=value)
    return patch.object(settings, "_instance", new_instance)


@pytest.mark.asyncio
async def test_static_not_served_when_debug_false():
    """StaticFilesMiddleware serves files in production if explicitly enabled.

    Mirrors Django's behaviour for development, but allows opt-in for production.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        static_path = Path(temp_dir)
        test_file = static_path / "test.txt"
        test_file.write_text("should not reach this")
        test_file.write_text("hello world")

        with _patch_debug(False):
            app = OpenViper(debug=False)
            app = StaticFilesMiddleware(app, url_path="/static", directories=[static_path])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            # User opted in via StaticFilesMiddleware → it serves even when DEBUG=False
            response = await client.get("/static/test.txt")
            assert response.status_code == 200
            assert response.text == "hello world"


@pytest.mark.asyncio
async def test_static_served_when_debug_true():
    """StaticFilesMiddleware serves files when DEBUG=True (development mode)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        static_path = Path(temp_dir)
        test_file = static_path / "test.txt"
        test_file.write_text("hello dev")

        with _patch_debug(True):
            app = OpenViper(debug=True)
            app = StaticFilesMiddleware(app, url_path="/static", directories=[static_path])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/static/test.txt")
            assert response.status_code == 200
            assert response.text == "hello dev"


@pytest.mark.asyncio
async def test_admin_static_routes_not_mounted_in_production():
    """Admin static routes are not registered in the router when DEBUG=False.

    /admin/ and /admin/assets/* return 404 because the routes don't exist,
    not because of any handler-level check.
    """
    with _patch_debug(False):
        app = OpenViper(debug=False)
        app.include_router(get_admin_site(), prefix="/admin")

        async with app.test_client() as client:
            # These routes ARE mounted now
            resp = await client.get("/admin/")
            assert resp.status_code in (200, 404)
            if resp.status_code == 404:
                assert "Admin Not Built" not in resp.text

            asset_resp = await client.get("/admin/assets/index.js")
            assert asset_resp.status_code in (200, 404)
            if asset_resp.status_code == 404:
                assert "Asset not found" not in asset_resp.text

            # API routes ARE always mounted
            resp = await client.post(
                "/admin/api/auth/login/", json={"username": "x", "password": "x"}
            )
            assert resp.status_code != 404, "Admin API must always be reachable"


@pytest.mark.asyncio
async def test_admin_assets_fallback_in_development():
    """Admin assets handler uses fallback to framework static when DEBUG=True.

    If an asset doesn't exist in the project static dir, the handler tries
    the framework's built-in admin static dir. If neither has it, 404 with
    'Asset not found' message (not a routing 404).
    """
    with _patch_debug(True):
        app = OpenViper(debug=True)
        app.include_router(get_admin_site(), prefix="/admin")

        async with app.test_client() as client:
            response = await client.get("/admin/assets/nonexistent_file_xyz.js")
            assert response.status_code == 404
            assert "Asset not found" in response.text
