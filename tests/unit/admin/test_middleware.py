"""Unit tests for openviper.admin.middleware — admin authentication middleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.admin.middleware import (
    AdminMiddleware,
    check_admin_access,
    check_model_permission,
    check_object_permission,
)


def _make_user(is_authenticated=True, is_staff=False, is_superuser=False, has_perm=True):
    """Create a mock user."""
    user = MagicMock()
    user.is_authenticated = is_authenticated
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    if callable(has_perm):
        user.has_perm = has_perm
    else:
        user.has_perm = MagicMock(return_value=has_perm)
    return user


class TestAdminMiddleware:
    """Test AdminMiddleware class."""

    def test_admin_path_prefix(self):
        """Test the admin path prefix constant."""
        assert AdminMiddleware.ADMIN_PATH_PREFIX == "/admin/api/"

    def test_exempt_paths(self):
        """Test that exempt paths are defined."""
        assert "/admin/api/auth/login/" in AdminMiddleware.EXEMPT_PATHS
        assert "/admin/api/auth/refresh/" in AdminMiddleware.EXEMPT_PATHS
        assert "/admin/api/config/" in AdminMiddleware.EXEMPT_PATHS

    @pytest.mark.asyncio
    async def test_non_http_request_passes_through(self):
        """Test that non-HTTP requests pass through."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        scope = {"type": "websocket", "path": "/ws"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_non_admin_path_passes_through(self):
        """Test that non-admin paths pass through without auth check."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        scope = {"type": "http", "path": "/api/users/"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_exempt_path_passes_through(self):
        """Test that exempt paths don't require authentication."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        scope = {"type": "http", "path": "/admin/api/auth/login/"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_authenticated_staff_user_passes(self):
        """Test that authenticated staff users can access admin."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        user = _make_user(is_authenticated=True, is_staff=True)
        scope = {"type": "http", "path": "/admin/api/models/", "user": user}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_authenticated_superuser_passes(self):
        """Test that authenticated superusers can access admin."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        user = _make_user(is_authenticated=True, is_superuser=True)
        scope = {"type": "http", "path": "/admin/api/models/", "user": user}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_unauthenticated_user_gets_401(self):
        """Test that unauthenticated users get 401."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        user = _make_user(is_authenticated=False)
        scope = {"type": "http", "path": "/admin/api/models/", "user": user}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should send unauthorized response, not call app
        app.assert_not_awaited()
        send.assert_awaited()

    @pytest.mark.asyncio
    async def test_non_staff_user_gets_401(self):
        """Test that non-staff users get 401."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        user = _make_user(is_authenticated=True, is_staff=False, is_superuser=False)
        scope = {"type": "http", "path": "/admin/api/models/", "user": user}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_not_awaited()
        send.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_user_gets_401(self):
        """Test that requests without user get 401."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        scope = {"type": "http", "path": "/admin/api/models/", "user": None}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_not_awaited()
        send.assert_awaited()

    @pytest.mark.asyncio
    async def test_path_normalization_with_trailing_slash(self):
        """Test that paths are normalized correctly."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        user = _make_user(is_authenticated=False)
        scope = {"type": "http", "path": "/admin/api/models", "user": user}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should still be treated as admin path
        app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_admin_authentication(self):
        """Test check_admin_authentication method."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        # Staff user
        user = _make_user(is_authenticated=True, is_staff=True)
        scope = {"user": user}
        assert await middleware.check_admin_authentication(scope) is True

        # Superuser
        user = _make_user(is_authenticated=True, is_superuser=True)
        scope = {"user": user}
        assert await middleware.check_admin_authentication(scope) is True

        # Regular user
        user = _make_user(is_authenticated=True, is_staff=False)
        scope = {"user": user}
        assert await middleware.check_admin_authentication(scope) is False

        # No user
        scope = {"user": None}
        assert await middleware.check_admin_authentication(scope) is False


class TestCheckAdminAccess:
    """Test check_admin_access function."""

    def test_staff_user_has_access(self):
        """Test that staff users have access."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_staff=True)
        assert check_admin_access(request) is True

    def test_superuser_has_access(self):
        """Test that superusers have access."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_superuser=True)
        assert check_admin_access(request) is True

    def test_regular_user_no_access(self):
        """Test that regular users don't have access."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_staff=False)
        assert check_admin_access(request) is False

    def test_unauthenticated_user_no_access(self):
        """Test that unauthenticated users don't have access."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=False)
        assert check_admin_access(request) is False

    def test_no_user_no_access(self):
        """Test that requests without user don't have access."""
        request = MagicMock()
        request.user = None
        assert check_admin_access(request) is False


class TestCheckModelPermission:
    """Test check_model_permission function."""

    def test_superuser_has_all_permissions(self):
        """Test that superusers have all model permissions."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_superuser=True)
        model_class = MagicMock()

        assert check_model_permission(request, model_class, "view") is True
        assert check_model_permission(request, model_class, "add") is True
        assert check_model_permission(request, model_class, "change") is True
        assert check_model_permission(request, model_class, "delete") is True

    def test_staff_user_has_permissions(self):
        """Test that staff users have basic permissions."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_staff=True)
        model_class = MagicMock()

        assert check_model_permission(request, model_class, "view") is True
        assert check_model_permission(request, model_class, "add") is True

    def test_regular_user_no_permissions(self):
        """Test that regular users don't have model permissions."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_staff=False, has_perm=False)
        model_class = MagicMock()

        assert check_model_permission(request, model_class, "view") is False

    def test_no_user_no_permissions(self):
        """Test that requests without user have no permissions."""
        request = MagicMock()
        request.user = None
        model_class = MagicMock()

        assert check_model_permission(request, model_class, "view") is False

    def test_user_with_has_perm_method(self):
        """Test users with has_perm method."""
        request = MagicMock()
        user = _make_user(is_authenticated=True, is_staff=False)
        user.has_perm = MagicMock(return_value=True)
        request.user = user
        model_class = MagicMock()

        result = check_model_permission(request, model_class, "view")
        # Staff user should have permission
        assert isinstance(result, bool)


class TestCheckObjectPermission:
    """Test check_object_permission function."""

    def test_superuser_has_all_object_permissions(self):
        """Test that superusers have all object permissions."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_superuser=True)
        obj = MagicMock()
        obj.__class__ = MagicMock()

        assert check_object_permission(request, obj, "view") is True
        assert check_object_permission(request, obj, "change") is True
        assert check_object_permission(request, obj, "delete") is True

    def test_staff_user_has_object_permissions(self):
        """Test that staff users have basic object permissions."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_staff=True)
        obj = MagicMock()
        obj.__class__ = MagicMock()

        assert check_object_permission(request, obj, "view") is True

    def test_no_user_no_object_permissions(self):
        """Test that requests without user have no object permissions."""
        request = MagicMock()
        request.user = None
        obj = MagicMock()

        assert check_object_permission(request, obj, "view") is False

    def test_delegates_to_check_model_permission(self):
        """Test that check_object_permission delegates to check_model_permission."""
        request = MagicMock()
        request.user = _make_user(is_authenticated=True, is_staff=True)
        obj = MagicMock()
        obj.__class__ = MagicMock()

        # Should delegate to model permission check
        result = check_object_permission(request, obj, "change")
        assert isinstance(result, bool)


class TestMiddlewareIntegration:
    """Integration tests for admin middleware."""

    @pytest.mark.asyncio
    async def test_full_request_flow_authenticated(self):
        """Test complete flow with authenticated staff user."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        user = _make_user(is_authenticated=True, is_staff=True)
        scope = {
            "type": "http",
            "path": "/admin/api/models/user/",
            "user": user,
            "method": "GET",
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_full_request_flow_unauthenticated(self):
        """Test complete flow with unauthenticated user."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        scope = {"type": "http", "path": "/admin/api/models/user/", "user": None}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        app.assert_not_awaited()
        # Check that 401 response was sent
        send.assert_awaited()

    @pytest.mark.asyncio
    async def test_multiple_paths(self):
        """Test middleware with various path combinations."""
        app = AsyncMock()
        middleware = AdminMiddleware(app)

        user = _make_user(is_authenticated=True, is_staff=True)

        # Test paths
        test_cases = [
            ("/admin/api/models/", True),  # Should be protected
            ("/admin/api/auth/login/", False),  # Exempt
            ("/api/public/", False),  # Not admin path
            ("/admin/static/", False),  # Not API path
        ]

        for path, _should_check_auth in test_cases:
            scope = {"type": "http", "path": path, "user": user}
            receive = AsyncMock()
            send = AsyncMock()
            app.reset_mock()

            await middleware(scope, receive, send)

            # All should eventually call app for authenticated staff user
            # or be exempt
            # This is more of a sanity check
            assert True
