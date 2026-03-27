"""Integration tests for OpenAPI exclusion via OPENAPI_EXCLUDE setting."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from openviper.app import OpenViper
from openviper.conf import settings
from openviper.openapi.schema import reset_openapi_cache


def _make_app_with_routes(exclude: list[str] | str) -> OpenViper:
    """Build a minimal OpenViper app with blog, admin, and user routes."""
    with (
        patch.object(type(settings), "OPENAPI_EXCLUDE", new=exclude, create=True),
        patch.object(type(settings), "OPENAPI_ENABLED", new=True, create=True),
    ):
        app = OpenViper()

    @app.get("/users")
    async def list_users() -> dict:
        return {"users": []}

    @app.get("/admin/dashboard")
    async def admin_dashboard() -> dict:
        return {"status": "ok"}

    @app.get("/blogs/posts")
    async def list_blogs() -> dict:
        return {"posts": []}

    return app


class TestOpenApiNotAccessible:
    """When OPENAPI_EXCLUDE == '__ALL__' the docs routes are not registered."""

    def setup_method(self) -> None:
        reset_openapi_cache()

    @pytest.mark.asyncio
    async def test_openapi_not_accessible(self) -> None:
        with (
            patch.object(type(settings), "OPENAPI_EXCLUDE", new="__ALL__", create=True),
            patch.object(type(settings), "OPENAPI_ENABLED", new=True, create=True),
        ):
            app = OpenViper()

        @app.get("/users")
        async def list_users() -> dict:
            return {"users": []}

        async with app.test_client() as client:
            response = await client.get("/open-api/openapi.json")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_docs_not_accessible_when_all_excluded(self) -> None:
        with (
            patch.object(type(settings), "OPENAPI_EXCLUDE", new="__ALL__", create=True),
            patch.object(type(settings), "OPENAPI_ENABLED", new=True, create=True),
        ):
            app = OpenViper()

        async with app.test_client() as client:
            docs_response = await client.get("/open-api/docs")
            redoc_response = await client.get("/open-api/redoc")

        assert docs_response.status_code == 404
        assert redoc_response.status_code == 404

    @pytest.mark.asyncio
    async def test_regular_routes_still_work_when_openapi_disabled(self) -> None:
        with (
            patch.object(type(settings), "OPENAPI_EXCLUDE", new="__ALL__", create=True),
            patch.object(type(settings), "OPENAPI_ENABLED", new=True, create=True),
        ):
            app = OpenViper()

        @app.get("/users")
        async def list_users() -> dict:
            return {"users": []}

        async with app.test_client() as client:
            response = await client.get("/users")
        assert response.status_code in (200, 403)


class TestAdminNotInSchema:
    """Admin routes are absent from the schema when excluded."""

    def setup_method(self) -> None:
        reset_openapi_cache()

    @pytest.mark.asyncio
    async def test_admin_not_in_schema(self) -> None:
        with (
            patch.object(type(settings), "OPENAPI_EXCLUDE", new=["admin"], create=True),
            patch.object(type(settings), "OPENAPI_ENABLED", new=True, create=True),
        ):
            app = OpenViper()

        @app.get("/users")
        async def list_users() -> dict:
            return {"users": []}

        @app.get("/admin/dashboard")
        async def admin_dashboard() -> dict:
            return {"status": "ok"}

        app.invalidate_openapi_schema()

        with patch.object(type(settings), "OPENAPI_EXCLUDE", new=["admin"], create=True):
            async with app.test_client() as client:
                response = await client.get("/open-api/openapi.json")

        assert response.status_code == 200
        schema = json.loads(response.content)
        paths = schema.get("paths", {})
        assert "/users" in paths
        assert not any(p.startswith("/admin") for p in paths)


class TestBlogNotInSchema:
    """Blog routes are absent from the schema when the blogs prefix is excluded."""

    def setup_method(self) -> None:
        reset_openapi_cache()

    @pytest.mark.asyncio
    async def test_blog_not_in_schema(self) -> None:
        with (
            patch.object(type(settings), "OPENAPI_EXCLUDE", new=["blogs"], create=True),
            patch.object(type(settings), "OPENAPI_ENABLED", new=True, create=True),
        ):
            app = OpenViper()

        @app.get("/users")
        async def list_users() -> dict:
            return {"users": []}

        @app.get("/blogs/posts")
        async def list_blogs() -> dict:
            return {"posts": []}

        app.invalidate_openapi_schema()

        with patch.object(type(settings), "OPENAPI_EXCLUDE", new=["blogs"], create=True):
            async with app.test_client() as client:
                response = await client.get("/open-api/openapi.json")

        assert response.status_code == 200
        schema = json.loads(response.content)
        paths = schema.get("paths", {})
        assert "/users" in paths
        assert not any(p.startswith("/blogs") for p in paths)


class TestOtherRoutesPresent:
    """Non-excluded routes always appear in the schema."""

    def setup_method(self) -> None:
        reset_openapi_cache()

    @pytest.mark.asyncio
    async def test_other_routes_present(self) -> None:
        with (
            patch.object(
                type(settings),
                "OPENAPI_EXCLUDE",
                new=["admin", "blogs"],
                create=True,
            ),
            patch.object(type(settings), "OPENAPI_ENABLED", new=True, create=True),
        ):
            app = OpenViper()

        @app.get("/users")
        async def list_users() -> dict:
            return {"users": []}

        @app.get("/products")
        async def list_products() -> dict:
            return {"products": []}

        @app.get("/admin/settings")
        async def admin_settings() -> dict:
            return {}

        @app.get("/blogs/articles")
        async def list_articles() -> dict:
            return {}

        app.invalidate_openapi_schema()

        with patch.object(
            type(settings),
            "OPENAPI_EXCLUDE",
            new=["admin", "blogs"],
            create=True,
        ):
            async with app.test_client() as client:
                response = await client.get("/open-api/openapi.json")

        assert response.status_code == 200
        schema = json.loads(response.content)
        paths = schema.get("paths", {})
        assert "/users" in paths
        assert "/products" in paths
        assert not any(p.startswith("/admin") for p in paths)
        assert not any(p.startswith("/blogs") for p in paths)
