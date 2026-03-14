"""Unit tests for openviper/admin/decorators.py, middleware.py, and discovery.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.admin.decorators import register
from openviper.admin.discovery import (
    autodiscover,
    discover_admin_modules,
    discover_extensions,
    import_admin_module,
)
from openviper.admin.middleware import (
    AdminMiddleware,
    check_admin_access,
    check_model_permission,
    check_object_permission,
)

# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


class TestDecorators:
    def test_register_decorator(self):
        with patch("openviper.admin.decorators.admin") as mock_admin:
            model = MagicMock()

            @register(model)
            class MockAdmin:
                pass

            mock_admin.register.assert_called_once_with(model, MockAdmin)

    def test_register_multiple_models(self):
        with patch("openviper.admin.decorators.admin") as mock_admin:
            m1, m2 = MagicMock(), MagicMock()

            @register(m1, m2)
            class MultiAdmin:
                pass

            assert mock_admin.register.call_count == 2
            mock_admin.register.assert_any_call(m1, MultiAdmin)
            mock_admin.register.assert_any_call(m2, MultiAdmin)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class TestAdminMiddleware:
    @pytest.mark.asyncio
    async def test_non_http_scope_skips(self):
        app = AsyncMock()
        mw = AdminMiddleware(app)
        scope = {"type": "websocket"}
        await mw(scope, None, None)
        app.assert_called_once_with(scope, None, None)

    @pytest.mark.asyncio
    async def test_non_admin_path_skips(self):
        app = AsyncMock()
        mw = AdminMiddleware(app)
        scope = {"type": "http", "path": "/not-admin/"}
        await mw(scope, None, None)
        app.assert_called_once_with(scope, None, None)

    @pytest.mark.asyncio
    async def test_exempt_path_skips(self):
        app = AsyncMock()
        mw = AdminMiddleware(app)
        for path in mw.EXEMPT_PATHS:
            app.reset_mock()
            scope = {"type": "http", "path": path}
            await mw(scope, None, None)
            app.assert_called_once_with(scope, None, None)

    @pytest.mark.asyncio
    async def test_unauthenticated_user_denied(self):
        app = AsyncMock()
        mw = AdminMiddleware(app)
        scope = {"type": "http", "path": "/admin/api/users/"}

        send = AsyncMock()
        await mw(scope, None, send)

        # Verify 401 response sent
        send.assert_called()
        args = send.call_args_list[0][0][0]
        assert args["type"] == "http.response.start"
        assert args["status"] == 401
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_staff_user_denied(self):
        app = AsyncMock()
        mw = AdminMiddleware(app)
        user = MagicMock()
        user.is_authenticated = True
        user.is_staff = False
        user.is_superuser = False
        scope = {"type": "http", "path": "/admin/api/users/", "user": user}

        send = AsyncMock()
        await mw(scope, None, send)

        send.assert_called()
        assert send.call_args_list[0][0][0]["status"] == 401

    @pytest.mark.asyncio
    async def test_staff_user_allowed(self):
        app = AsyncMock()
        mw = AdminMiddleware(app)
        user = MagicMock()
        user.is_authenticated = True
        user.is_staff = True
        scope = {"type": "http", "path": "/admin/api/users/", "user": user}

        await mw(scope, None, None)
        app.assert_called_once_with(scope, None, None)

    @pytest.mark.asyncio
    async def test_superuser_allowed(self):
        app = AsyncMock()
        mw = AdminMiddleware(app)
        user = MagicMock()
        user.is_authenticated = True
        user.is_superuser = True
        scope = {"type": "http", "path": "/admin/api/users/", "user": user}

        await mw(scope, None, None)
        app.assert_called_once_with(scope, None, None)


class TestPermissionHelpers:
    def test_check_admin_access(self):
        req = MagicMock()
        req.user = None
        assert check_admin_access(req) is False

        req.user = MagicMock(is_authenticated=False)
        assert check_admin_access(req) is False

        req.user = MagicMock(is_authenticated=True, is_staff=True)
        assert check_admin_access(req) is True

        req.user = MagicMock(is_authenticated=True, is_staff=False, is_superuser=True)
        assert check_admin_access(req) is True

    def test_check_model_permission(self):
        req = MagicMock()
        req.user = None
        assert check_model_permission(req, None, "view") is False

        req.user = MagicMock(is_superuser=True)
        assert check_model_permission(req, None, "view") is True

        req.user = MagicMock(is_superuser=False, is_staff=True)
        assert check_model_permission(req, None, "view") is True

        req.user = MagicMock(is_superuser=False, is_staff=False)
        assert check_model_permission(req, None, "view") is False

    def test_check_object_permission(self):
        req = MagicMock()
        req.user = None
        assert check_object_permission(req, None, "view") is False

        req.user = MagicMock(is_superuser=True)
        assert check_object_permission(req, None, "view") is True

        req.user = MagicMock(is_superuser=False, is_staff=True)
        assert check_object_permission(req, None, "view") is True


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_discover_admin_modules(self):
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["app1", "app2"]
            with patch("openviper.admin.discovery.import_admin_module") as mock_import:
                mock_import.side_effect = [True, False]
                result = discover_admin_modules()
                assert result == ["app1"]
                assert mock_import.call_count == 2

    def test_import_admin_module_already_loaded(self):
        with patch("sys.modules", {"myapp.admin": MagicMock()}):
            assert import_admin_module("myapp") is True

    def test_import_admin_module_not_found(self):
        with patch("importlib.util.find_spec", return_value=None):
            assert import_admin_module("myapp") is False

    def test_import_admin_module_error(self):
        with patch("importlib.util.find_spec") as mock_find:
            mock_find.side_effect = ModuleNotFoundError()
            assert import_admin_module("myapp") is False

    def test_import_admin_module_success(self):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            with patch("importlib.import_module") as mock_import:
                assert import_admin_module("myapp") is True
                mock_import.assert_called_once_with("myapp.admin")

    def test_import_admin_module_import_error(self):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            with patch("importlib.import_module", side_effect=ImportError()):
                assert import_admin_module("myapp") is False

    def test_import_admin_module_unexpected_exception(self):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            with patch("importlib.import_module", side_effect=Exception()):
                assert import_admin_module("myapp") is False

    def test_discover_extensions_no_apps(self):
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []
            assert discover_extensions() == []

    def test_discover_extensions_not_found(self):
        with patch("openviper.admin.discovery.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["missing"]
            with patch("importlib.util.find_spec", return_value=None):
                assert discover_extensions() == []

    def test_autodiscover(self):
        with patch("openviper.admin.discovery.admin") as mock_admin:
            with patch("openviper.admin.discovery.register_auth_models") as mock_auth:
                autodiscover()
                mock_admin.auto_discover_from_installed_apps.assert_called_once()
                mock_auth.assert_called_once()
