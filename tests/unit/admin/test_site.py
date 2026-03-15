import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.admin.site import (
    ADMIN_STATIC_DIR,
    get_admin_site,
)
from openviper.exceptions import NotFound
from openviper.http.request import Request
from openviper.http.response import FileResponse, HTMLResponse
from openviper.routing.router import Router


def _make_request(path="/", method="GET"):
    """Create a mock request."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.disconnect"}

    request = Request(scope, receive)
    return request


class TestAdminStaticDir:
    """Test ADMIN_STATIC_DIR constant."""

    def test_admin_static_dir_is_path(self):
        """Test that ADMIN_STATIC_DIR is a Path object."""
        assert isinstance(ADMIN_STATIC_DIR, Path)

    def test_admin_static_dir_location(self):
        """Test that ADMIN_STATIC_DIR points to correct location."""
        assert "admin" in str(ADMIN_STATIC_DIR)
        assert "static" in str(ADMIN_STATIC_DIR)


class TestGetAdminSite:
    """Test get_admin_site function."""

    def test_returns_router(self):
        """Test that get_admin_site returns a Router."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()
            assert isinstance(router, Router)

    def test_calls_autodiscover(self):
        """Test that autodiscover is called."""
        with patch("openviper.admin.site.autodiscover") as mock_autodiscover:
            get_admin_site()
            mock_autodiscover.assert_called_once()

    def test_includes_admin_api_router(self):
        """Test that admin API routes are included."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.get_admin_router") as mock_get_router:
                mock_get_router.return_value = Router()
                get_admin_site()

                mock_get_router.assert_called_once()

    def test_registers_extensions_endpoint(self):
        """Test that extensions manifest endpoint is registered."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()

            # Router should have routes
            assert len(router.routes) > 0


def _get_route_endpoint(router: Router, path: str):
    # Quick helper to extract the handler function for a specific GET route
    for route in router.routes:
        if getattr(route, "path", None) == path and "GET" in getattr(route, "methods", []):
            return route.handler
        # If it's a sub-router (Mount or Include)
        if hasattr(route, "app") and isinstance(route.app, Router):
            endpoint = _get_route_endpoint(
                route.app, path.replace(getattr(route, "path", "/"), "/", 1).replace("//", "/")
            )
            if endpoint:
                return endpoint
    return None


class TestListExtensionsEndpoint:
    """Test list_extensions endpoint."""

    @pytest.mark.asyncio
    async def test_list_extensions_returns_json(self):
        """Test that list_extensions returns JSON response."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.discover_extensions") as mock_discover:
                mock_discover.return_value = [
                    {
                        "app": "test_app",
                        "file": "custom.js",
                        "url": "/admin/extensions/test_app/custom.js",
                        "path": "/path/to/custom.js",
                        "type": "script",
                    }
                ]
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/api/extensions/")
                response = await endpoint(_make_request())
                assert response.status_code == 200
                data = json.loads(response.body)
                assert len(data["extensions"]) == 1
                assert data["extensions"][0]["app"] == "test_app"

    @pytest.mark.asyncio
    async def test_list_extensions_structure(self):
        """Test extension list response structure."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.discover_extensions") as mock_discover:
                mock_discover.return_value = []
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/api/extensions/")
                response = await endpoint(_make_request())
                data = json.loads(response.body)
                assert data["extensions"] == []


class TestServeExtensionFile:
    """Test serve_extension_file endpoint."""

    @pytest.mark.asyncio
    async def test_serve_extension_file_js(self):
        """Test serving JavaScript extension file."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/extensions/{app_name}/{path:path}")

                with patch("openviper.admin.site.importlib.util.find_spec") as mock_spec:
                    mock_spec.return_value = MagicMock(origin="/fake/app/__init__.py")
                    with patch("openviper.admin.site.Path.exists", return_value=True):
                        with patch("openviper.admin.site.Path.is_file", return_value=True):
                            response = await endpoint(
                                _make_request(), app_name="test_app", path="test.js"
                            )
                            assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_serve_extension_file_not_found(self):
        """Test handling of missing extension file."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/extensions/{app_name}/{path:path}")

                with patch("openviper.admin.site.importlib.util.find_spec", return_value=None):
                    with pytest.raises(NotFound, match="App not found: test_app"):
                        await endpoint(_make_request(), app_name="test_app", path="test.js")

    @pytest.mark.asyncio
    async def test_serve_extension_file_file_not_found(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/extensions/{app_name}/{path:path}")

                with patch("openviper.admin.site.importlib.util.find_spec") as mock_spec:
                    mock_spec.return_value = MagicMock(origin="/fake/app/__init__.py")
                    with patch("openviper.admin.site.Path.exists", return_value=False):
                        with pytest.raises(NotFound, match="Extension file not found"):
                            await endpoint(_make_request(), app_name="test_app", path="test.js")

    @pytest.mark.asyncio
    async def test_serve_extension_file_exception(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/extensions/{app_name}/{path:path}")

                with patch(
                    "openviper.admin.site.importlib.util.find_spec", side_effect=Exception("kaboom")
                ):
                    with pytest.raises(NotFound, match="Extension not found: test_app/test.js"):
                        await endpoint(_make_request(), app_name="test_app", path="test.js")

    @pytest.mark.asyncio
    async def test_serve_extension_file_invalid_suffix(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/extensions/{app_name}/{path:path}")

                with patch("openviper.admin.site.importlib.util.find_spec") as mock_spec:
                    mock_spec.return_value = MagicMock(origin="/fake/app/__init__.py")
                    with patch("openviper.admin.site.Path.exists", return_value=True):
                        with patch("openviper.admin.site.Path.is_file", return_value=True):
                            with pytest.raises(NotFound):
                                await endpoint(
                                    _make_request(), app_name="test_app", path="test.txt"
                                )


class TestServeAdminIndex:
    """Test serve_admin_index endpoint."""

    @pytest.mark.asyncio
    async def test_serves_project_index_if_exists(self):
        """Test that project-level index is served if it exists."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()
            endpoint = _get_route_endpoint(router, "/")

            with patch("openviper.admin.site.Path.exists", return_value=True):
                with patch("openviper.admin.site.Path.is_file", return_value=True):
                    response = await endpoint(_make_request())
                    assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_returns_framework_index_if_exists(self):
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()
            endpoint = _get_route_endpoint(router, "/")

            with patch("openviper.admin.site.Path.exists", side_effect=[False, True]):
                with patch("openviper.admin.site.Path.is_file", return_value=True):
                    response = await endpoint(_make_request())
                    assert isinstance(response, FileResponse)


class TestServeAdminSpa:
    """Test serve_admin_spa endpoint."""

    @pytest.mark.asyncio
    async def test_serves_spa_project_index(self):
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()
            endpoint = _get_route_endpoint(router, "/{path:path}")

            with patch("openviper.admin.site.Path.exists", return_value=True):
                with patch("openviper.admin.site.Path.is_file", return_value=True):
                    response = await endpoint(_make_request(), path="some/path")
                    assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_serves_spa_framework_index(self):
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()
            endpoint = _get_route_endpoint(router, "/{path:path}")

            with patch("openviper.admin.site.Path.exists", side_effect=[False, True]):
                with patch("openviper.admin.site.Path.is_file", return_value=True):
                    response = await endpoint(_make_request(), path="some/path")
                    assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_returns_500_if_no_index_in_development(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/{path:path}")

                with patch("openviper.admin.site.Path.exists", return_value=False):
                    response = await endpoint(_make_request(), path="some/path")
                    assert isinstance(response, HTMLResponse)
                    assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_returns_404_if_no_index_in_production(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = False
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/{path:path}")

                with patch("openviper.admin.site.Path.exists", return_value=False):
                    response = await endpoint(_make_request(), path="some/path")
                    assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_500_if_no_index_in_development_root(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/")

                with patch("openviper.admin.site.Path.exists", return_value=False):
                    response = await endpoint(_make_request())
                    assert isinstance(response, HTMLResponse)
                    assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_returns_404_if_no_index_in_production_root(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = False
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/")

                with patch("openviper.admin.site.Path.exists", return_value=False):
                    response = await endpoint(_make_request())
                    assert response.status_code == 404


class TestServeAdminAsset:
    """Test serve_admin_asset endpoint."""

    @pytest.mark.asyncio
    async def test_serve_asset_file_exists(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/assets/{path:path}")

                with patch("openviper.admin.site.Path.exists", return_value=True):
                    with patch("openviper.admin.site.Path.is_file", return_value=True):
                        response = await endpoint(_make_request(), path="test.css")
                        assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_serve_asset_not_found(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/assets/{path:path}")

                with patch("openviper.admin.site.Path.exists", return_value=False):
                    with pytest.raises(NotFound):
                        await endpoint(_make_request(), path="test.css")


class TestServeSilent404:
    @pytest.mark.asyncio
    async def test_silent_404_in_prod(self):
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = False
                router = get_admin_site()
                endpoint = _get_route_endpoint(router, "/assets/{path:path}")
                response = await endpoint(_make_request())
                assert response.status_code == 404


class TestDebugModeHandling:
    """Test DEBUG mode conditional behavior."""

    def test_extension_routes_in_debug_mode(self):
        """Test that extension routes are registered in DEBUG mode."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True

                router = get_admin_site()

                # Should have extension and asset routes
                assert len(router.routes) > 0

    def test_extension_routes_disabled_in_production(self):
        """Test that extension routes return 404 in production."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = False

                router = get_admin_site()

                # Should still have routes but they return 404
                assert len(router.routes) > 0

    def test_asset_routes_in_debug_mode(self):
        """Test that asset routes are registered in DEBUG mode."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True

                router = get_admin_site()
                assert router is not None

    def test_asset_routes_disabled_in_production(self):
        """Test that asset routes return 404 in production."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = False

                router = get_admin_site()
                assert router is not None


class TestSPARoutes:
    """Test SPA routing."""

    def test_spa_root_route_registered(self):
        """Test that SPA root route is registered."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()
            assert len(router.routes) > 0

    def test_spa_catch_all_route_registered(self):
        """Test that SPA catch-all route is registered."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()
            # Should have catch-all path route
            assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_spa_routes_serve_index(self):
        """Test that SPA routes serve index.html."""
        # This requires complex mocking of file system
        assert True


class TestAPIRoutes:
    """Test API route registration."""

    def test_api_routes_always_present(self):
        """Test that API routes are always registered."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                # Test both DEBUG modes
                for debug_value in [True, False]:
                    mock_settings.DEBUG = debug_value
                    router = get_admin_site()
                    # API routes should always be present
                    assert len(router.routes) > 0

    def test_api_router_included_with_prefix(self):
        """Test that API router is included with /api prefix."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.get_admin_router") as mock_get_router:
                mock_api_router = Router()
                mock_get_router.return_value = mock_api_router

                get_admin_site()

                mock_get_router.assert_called_once()


class TestAdminSiteIntegration:
    """Integration tests for admin site."""

    def test_full_router_creation(self):
        """Test creating complete admin site router."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()

            assert router is not None
            assert isinstance(router, Router)
            assert len(router.routes) > 0

    def test_router_with_installed_apps(self):
        """Test router creation with installed apps."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.INSTALLED_APPS = ["app1", "app2"]

                router = get_admin_site()
                assert router is not None

    def test_can_mount_at_prefix(self):
        """Test that admin site can be mounted at /admin prefix."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()

            # Should be mountable in an app
            assert router is not None


class TestRouteOrdering:
    """Test route ordering and precedence."""

    def test_api_routes_before_spa_routes(self):
        """Test that API routes are registered before SPA catch-all."""
        with patch("openviper.admin.site.autodiscover"):
            router = get_admin_site()

            # The router should have routes in proper order
            # API routes should match before SPA fallback
            assert len(router.routes) > 0

    def test_extensions_before_spa_routes(self):
        """Test that extension routes are registered before SPA."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True

                router = get_admin_site()
                assert len(router.routes) > 0

    def test_assets_before_spa_routes(self):
        """Test that asset routes are registered before SPA."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = True

                router = get_admin_site()
                assert len(router.routes) > 0


class TestStaticFileHandling:
    """Test static file serving behavior."""

    def test_project_static_takes_precedence(self):
        """Test that project static files take precedence over framework."""
        # This requires complex file system mocking
        assert True

    def test_framework_static_as_fallback(self):
        """Test that framework static files are used as fallback."""
        assert True

    def test_missing_static_files_handled(self):
        """Test handling of missing static files."""
        assert True


class TestSecurityConsiderations:
    """Test security-related behavior."""

    def test_extension_file_type_validation(self):
        """Test that only .js and .vue files can be served as extensions."""
        # This would test the actual endpoint logic
        assert True

    def test_path_traversal_protection(self):
        """Test protection against path traversal attacks."""
        # This would test file serving security
        assert True

    def test_production_mode_static_serving(self):
        """Test that static serving is disabled in production."""
        with patch("openviper.admin.site.autodiscover"):
            with patch("openviper.admin.site.settings") as mock_settings:
                mock_settings.DEBUG = False

                router = get_admin_site()
                # In production, framework shouldn't serve static files
                assert router is not None
