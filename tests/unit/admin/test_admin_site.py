from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from openviper.admin.site import get_admin_site
from openviper.exceptions import NotFound
from openviper.http.response import FileResponse, HTMLResponse
from openviper.routing.router import Router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request() -> MagicMock:
    return MagicMock(name="request")


def _find_handler(router: Router, handler_name: str):
    """Search all routes (including sub-router routes) for the named handler."""
    for route in router.routes:
        if route.handler.__name__ == handler_name:
            return route.handler
    return None


def _get_all_route_paths(router: Router) -> set[str]:
    return {route.path for route in router.routes}


def _call_get_admin_site(debug: bool = True):
    """Call get_admin_site() with core dependencies mocked.

    Returns the Router (router) alongside the mock_admin_router stub.
    """
    mock_admin_router = Router()

    with (
        patch("openviper.admin.site.autodiscover"),
        patch("openviper.admin.site.get_admin_router", return_value=mock_admin_router),
        patch("openviper.admin.site.settings") as mock_settings,
    ):
        mock_settings.DEBUG = debug
        mock_settings.STATIC_ROOT = "static"  # default-ish value
        router = get_admin_site()

    return router, mock_admin_router


# ---------------------------------------------------------------------------
# get_admin_site — structure and route registration
# ---------------------------------------------------------------------------


class TestGetAdminSiteStructure:
    def test_returns_router_instance(self):
        router, _ = _call_get_admin_site()
        assert isinstance(router, Router)

    def test_autodiscover_is_called(self):
        mock_admin_router = Router()
        with (
            patch("openviper.admin.site.autodiscover") as mock_discover,
            patch("openviper.admin.site.get_admin_router", return_value=mock_admin_router),
            patch("openviper.admin.site.settings") as mock_settings,
        ):
            mock_settings.DEBUG = True
            mock_settings.STATIC_ROOT = "static"
            from openviper.admin.site import get_admin_site

            get_admin_site()
        mock_discover.assert_called_once()

    def test_get_admin_router_is_called(self):
        mock_admin_router = Router()
        with (
            patch("openviper.admin.site.autodiscover"),
            patch(
                "openviper.admin.site.get_admin_router", return_value=mock_admin_router
            ) as mock_gar,
            patch("openviper.admin.site.settings") as mock_settings,
        ):
            mock_settings.DEBUG = True
            mock_settings.STATIC_ROOT = "static"
            from openviper.admin.site import get_admin_site

            get_admin_site()
        mock_gar.assert_called_once()

    def test_extensions_manifest_route_always_present(self):
        """The /api/extensions/ route is always registered."""
        router, _ = _call_get_admin_site(debug=True)
        paths = _get_all_route_paths(router)
        assert "/api/extensions/" in paths

    def test_spa_index_route_always_present(self):
        router, _ = _call_get_admin_site(debug=True)
        paths = _get_all_route_paths(router)
        assert "/" in paths

    def test_spa_catch_all_route_always_present(self):
        router, _ = _call_get_admin_site(debug=True)
        paths = _get_all_route_paths(router)
        assert "/{path:path}" in paths

    def test_debug_true_registers_asset_route(self):
        router, _ = _call_get_admin_site(debug=True)
        paths = _get_all_route_paths(router)
        assert "/assets/{path:path}" in paths

    def test_debug_true_registers_extension_file_route(self):
        router, _ = _call_get_admin_site(debug=True)
        paths = _get_all_route_paths(router)
        assert "/extensions/{app_name}/{path:path}" in paths

    def test_debug_false_registers_silent_404_for_assets(self):
        router, _ = _call_get_admin_site(debug=False)
        paths = _get_all_route_paths(router)
        assert "/assets/{path:path}" in paths

    def test_debug_false_registers_silent_404_for_extensions(self):
        router, _ = _call_get_admin_site(debug=False)
        paths = _get_all_route_paths(router)
        assert "/extensions/{path:path}" in paths

    @pytest.mark.asyncio
    async def test_debug_false_silent_404_returns_404(self):
        """In production the extension/asset handlers return plain 404 responses."""
        router, _ = _call_get_admin_site(debug=False)
        # Find the silent_404 handler on the /extensions/{path:path} route (exact match)
        for route in router.routes:
            if route.path == "/extensions/{path:path}":
                handler = route.handler
                break
        else:
            pytest.fail("/extensions/{path:path} route not found in production mode")

        response = await handler(_mock_request(), path="some/path")
        assert response.status_code == 404

    def test_debug_true_asset_route_uses_serve_handler(self):
        """In debug mode, the asset route uses serve_admin_asset (not silent_404)."""
        router, _ = _call_get_admin_site(debug=True)
        for route in router.routes:
            if route.path == "/assets/{path:path}":
                assert route.handler.__name__ == "serve_admin_asset"
                break
        else:
            pytest.fail("/assets/{path:path} route not found in debug mode")


# ---------------------------------------------------------------------------
# list_extensions handler
# ---------------------------------------------------------------------------


class TestListExtensions:
    @pytest.mark.asyncio
    async def test_returns_json_with_extensions_key(self):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "list_extensions")
        assert handler is not None, "list_extensions handler not found"

        mock_exts = [
            {
                "app": "myapp",
                "file": "plugin.js",
                "url": "/admin/ext/myapp/plugin.js",
                "type": "script",
            },
        ]
        with patch("openviper.admin.site.discover_extensions", return_value=mock_exts):
            response = await handler(_mock_request())

        body = json.loads(response.body)
        assert "extensions" in body
        assert len(body["extensions"]) == 1
        ext = body["extensions"][0]
        assert ext["app"] == "myapp"
        assert ext["file"] == "plugin.js"
        assert ext["url"] == "/admin/ext/myapp/plugin.js"
        assert ext["type"] == "script"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_extensions(self):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "list_extensions")

        with patch("openviper.admin.site.discover_extensions", return_value=[]):
            response = await handler(_mock_request())

        body = json.loads(response.body)
        assert body["extensions"] == []

    @pytest.mark.asyncio
    async def test_extensions_fields_filtered_to_four_keys(self):
        """Only app, file, url, type are returned — not path."""
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "list_extensions")

        mock_exts = [
            {
                "app": "myapp",
                "file": "widget.vue",
                "url": "/admin/extensions/myapp/widget.vue",
                "type": "module",
                "path": "/absolute/path/widget.vue",  # should NOT appear in response
            }
        ]
        with patch("openviper.admin.site.discover_extensions", return_value=mock_exts):
            response = await handler(_mock_request())

        # In some versions of JSONResponse, body is accessed via .body or ._body
        # We'll try to find the correct way to access it in this project.
        # Based on the error, it's not ._body. Let's try .body
        try:
            raw_body = response.body
        except AttributeError:
            raw_body = response._body

        import json

        body = json.loads(raw_body.decode())
        ext = body["extensions"][0]
        assert "path" not in ext
        assert set(ext.keys()) == {"app", "file", "url", "type"}


# ---------------------------------------------------------------------------
# serve_extension_file handler (DEBUG=True only)
# ---------------------------------------------------------------------------


class TestServeExtensionFile:
    @pytest.mark.asyncio
    async def test_serves_js_file(self, tmp_path):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_extension_file")
        assert handler is not None, "serve_extension_file handler not found (expected DEBUG=True)"

        ext_dir = tmp_path / "admin_extensions"
        ext_dir.mkdir()
        js_file = ext_dir / "plugin.js"
        js_file.write_text("console.log('ok');")

        mock_spec = MagicMock()
        mock_spec.origin = str(tmp_path / "__init__.py")

        with patch("openviper.admin.site.importlib.util.find_spec", return_value=mock_spec):
            response = await handler(_mock_request(), app_name="myapp", path="plugin.js")

        assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_serves_vue_file(self, tmp_path):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_extension_file")

        ext_dir = tmp_path / "admin_extensions"
        ext_dir.mkdir()
        vue_file = ext_dir / "Widget.vue"
        vue_file.write_text("<template></template>")

        mock_spec = MagicMock()
        mock_spec.origin = str(tmp_path / "__init__.py")

        with patch("openviper.admin.site.importlib.util.find_spec", return_value=mock_spec):
            response = await handler(_mock_request(), app_name="myapp", path="Widget.vue")

        assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_app_spec_is_none(self):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_extension_file")

        with patch("openviper.admin.site.importlib.util.find_spec", return_value=None):
            with pytest.raises(NotFound):
                await handler(_mock_request(), app_name="missing_app", path="plugin.js")

    @pytest.mark.asyncio
    async def test_raises_not_found_when_spec_origin_is_none(self):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_extension_file")

        mock_spec = MagicMock()
        mock_spec.origin = None

        with patch("openviper.admin.site.importlib.util.find_spec", return_value=mock_spec):
            with pytest.raises(NotFound):
                await handler(_mock_request(), app_name="myapp", path="plugin.js")

    @pytest.mark.asyncio
    async def test_raises_not_found_when_file_missing(self, tmp_path):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_extension_file")

        mock_spec = MagicMock()
        mock_spec.origin = str(tmp_path / "__init__.py")  # admin_extensions dir not created

        with patch("openviper.admin.site.importlib.util.find_spec", return_value=mock_spec):
            with pytest.raises(NotFound):
                await handler(_mock_request(), app_name="myapp", path="nonexistent.js")

    @pytest.mark.asyncio
    async def test_raises_not_found_for_disallowed_extension(self, tmp_path):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_extension_file")

        ext_dir = tmp_path / "admin_extensions"
        ext_dir.mkdir()
        bad_file = ext_dir / "secrets.env"
        bad_file.write_text("SECRET=abc")

        mock_spec = MagicMock()
        mock_spec.origin = str(tmp_path / "__init__.py")

        with patch("openviper.admin.site.importlib.util.find_spec", return_value=mock_spec):
            with pytest.raises(NotFound, match="Only .js and .vue"):
                await handler(_mock_request(), app_name="myapp", path="secrets.env")

    @pytest.mark.asyncio
    async def test_raises_not_found_on_unexpected_error(self):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_extension_file")

        with patch(
            "openviper.admin.site.importlib.util.find_spec",
            side_effect=RuntimeError("unexpected"),
        ):
            with pytest.raises(NotFound):
                await handler(_mock_request(), app_name="myapp", path="plugin.js")


# ---------------------------------------------------------------------------
# serve_admin_index handler
# ---------------------------------------------------------------------------


class TestServeAdminIndex:
    @pytest.mark.asyncio
    async def test_returns_project_index_when_it_exists(self, tmp_path):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_index")

        project_index = tmp_path / "admin" / "index.html"
        project_index.parent.mkdir(parents=True)
        project_index.write_text("<html></html>")

        with patch("openviper.admin.site.settings") as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)
            mock_settings.DEBUG = True
            response = await handler(_mock_request())

        from openviper.http.response import FileResponse

        assert isinstance(response, FileResponse)
        assert str(project_index) in response.file_path

    @pytest.mark.asyncio
    async def test_falls_back_to_framework_index(self, tmp_path):
        """If no project index is found, fall back to the built-in one."""
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_index")

        # Create a framework-level index
        framework_index = tmp_path / "index.html"
        framework_index.write_text("<html>framework</html>")

        with (
            patch("openviper.admin.site.settings") as mock_settings,
            patch("openviper.admin.site.ADMIN_STATIC_DIR", tmp_path),
        ):
            mock_settings.STATIC_ROOT = str(tmp_path / "no_such_static")
            mock_settings.DEBUG = True
            response = await handler(_mock_request())

        from openviper.http.response import FileResponse

        assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_returns_html_response_when_no_index_and_debug_true(self, tmp_path):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_index")

        nonexistent_dir = tmp_path / "no_admin_static"

        with (
            patch("openviper.admin.site.settings") as mock_settings,
            patch("openviper.admin.site.ADMIN_STATIC_DIR", nonexistent_dir),
        ):
            mock_settings.STATIC_ROOT = str(tmp_path / "no_project_static")
            mock_settings.DEBUG = True
            response = await handler(_mock_request())

        assert isinstance(response, HTMLResponse)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_returns_404_response_when_no_index_and_debug_false(self, tmp_path):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_index")

        nonexistent_dir = tmp_path / "no_admin_static"

        with (
            patch("openviper.admin.site.settings") as mock_settings,
            patch("openviper.admin.site.ADMIN_STATIC_DIR", nonexistent_dir),
        ):
            mock_settings.STATIC_ROOT = str(tmp_path / "no_project_static")
            mock_settings.DEBUG = False
            response = await handler(_mock_request())

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# serve_admin_spa handler
# ---------------------------------------------------------------------------


class TestServeAdminSpa:
    @pytest.mark.asyncio
    async def test_returns_project_index_when_it_exists(self, tmp_path):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_spa")

        project_index = tmp_path / "admin" / "index.html"
        project_index.parent.mkdir(parents=True)
        project_index.write_text("<html></html>")

        with patch("openviper.admin.site.settings") as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)
            mock_settings.DEBUG = True
            response = await handler(_mock_request(), path="dashboard/users")

        assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_returns_html_response_when_no_index_and_debug_true(self, tmp_path):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_spa")

        nonexistent_dir = tmp_path / "no_admin"

        with (
            patch("openviper.admin.site.settings") as mock_settings,
            patch("openviper.admin.site.ADMIN_STATIC_DIR", nonexistent_dir),
        ):
            mock_settings.STATIC_ROOT = str(tmp_path / "no_project")
            mock_settings.DEBUG = True
            response = await handler(_mock_request(), path="some/path")

        assert isinstance(response, HTMLResponse)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_returns_404_when_no_index_and_debug_false(self, tmp_path):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_spa")

        nonexistent_dir = tmp_path / "no_admin"

        with (
            patch("openviper.admin.site.settings") as mock_settings,
            patch("openviper.admin.site.ADMIN_STATIC_DIR", nonexistent_dir),
        ):
            mock_settings.STATIC_ROOT = str(tmp_path / "no_project")
            mock_settings.DEBUG = False
            response = await handler(_mock_request(), path="some/deep/path")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_falls_back_to_framework_index(self, tmp_path):
        router, _ = _call_get_admin_site()
        handler = _find_handler(router, "serve_admin_spa")

        framework_index = tmp_path / "index.html"
        framework_index.write_text("<html>framework</html>")

        with (
            patch("openviper.admin.site.settings") as mock_settings,
            patch("openviper.admin.site.ADMIN_STATIC_DIR", tmp_path),
        ):
            mock_settings.STATIC_ROOT = str(tmp_path / "no_project")
            mock_settings.DEBUG = True
            response = await handler(_mock_request(), path="settings")

        assert isinstance(response, FileResponse)


# ---------------------------------------------------------------------------
# serve_admin_asset handler (DEBUG=True only)
# ---------------------------------------------------------------------------


class TestServeAdminAsset:
    @pytest.mark.asyncio
    async def test_serves_existing_asset(self, tmp_path):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_admin_asset")
        assert handler is not None, "serve_admin_asset not found (expected DEBUG=True)"

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        css_file = assets_dir / "main.css"
        css_file.write_text("body { margin: 0; }")

        with patch("openviper.admin.site.ADMIN_STATIC_DIR", tmp_path):
            response = await handler(_mock_request(), path="main.css")

        assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_asset(self, tmp_path):
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_admin_asset")

        with patch("openviper.admin.site.ADMIN_STATIC_DIR", tmp_path):
            with pytest.raises(NotFound, match="Asset not found"):
                await handler(_mock_request(), path="does_not_exist.js")

    @pytest.mark.asyncio
    async def test_raises_not_found_for_directory_path(self, tmp_path):
        """A path that resolves to a directory, not a file, should raise NotFound."""
        router, _ = _call_get_admin_site(debug=True)
        handler = _find_handler(router, "serve_admin_asset")

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        subdir = assets_dir / "fonts"
        subdir.mkdir()  # this is a directory, not a file

        with patch("openviper.admin.site.ADMIN_STATIC_DIR", tmp_path):
            with pytest.raises(NotFound, match="Asset not found"):
                await handler(_mock_request(), path="fonts")
