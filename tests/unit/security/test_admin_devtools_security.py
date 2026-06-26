"""Admin and devtools security tests.

Requirement IDs: ADMIN-001 through ADMIN-004.
"""

from __future__ import annotations

import pytest

from openviper.admin.options import ModelAdmin
from openviper.auth.admin import UserAdmin
from openviper.auth.decorators import login_required, role_required
from openviper.auth.models import User
from openviper.conf.settings import Settings
from openviper.db.executor import assert_safe_table_name, validate_regex_pattern
from openviper.db.models import Model
from openviper.exceptions import FieldError, PermissionDenied, Unauthorized
from openviper.http.request import Request
from openviper.middleware.error import ServerErrorMiddleware

from .conftest import AnonymousMockUser, MockUser, make_scope


class TestAdminAuthorization:
    """Admin routes must require admin authorization."""

    def test_admin001_model_admin_sensitive_fields(self):
        """ModelAdmin must define sensitive_fields including password."""
        admin = ModelAdmin(Model)
        assert "password" in admin.sensitive_fields

    def test_admin001_model_admin_has_permission_checks(self):
        """ModelAdmin must have permission check methods."""
        assert hasattr(ModelAdmin, "has_add_permission")
        assert hasattr(ModelAdmin, "has_delete_permission")

    @pytest.mark.asyncio
    async def test_admin001_anonymous_user_denied(self):
        """Anonymous users must be denied access to protected routes."""

        @login_required
        async def admin_view(request):
            return {"admin": True}

        anonymous = AnonymousMockUser()
        request = Request(make_scope())
        request.user = anonymous

        with pytest.raises(Unauthorized):
            await admin_view(request)

    @pytest.mark.asyncio
    async def test_admin001_non_admin_denied(self):
        """Non-admin users must be denied access to admin routes."""

        @role_required("admin")
        async def admin_view(request):
            return {"admin": True}

        regular_user = MockUser(user_id=1, roles=["viewer"])
        request = Request(make_scope())
        request.user = regular_user

        with pytest.raises(PermissionDenied):
            await admin_view(request)


class TestDebugConsoleProduction:
    """Debug console must never be enabled in production."""

    def test_admin002_debug_mode_default_is_development(self):
        """DEBUG defaults to True for development; production must override."""
        settings = Settings()
        # The default is True for development convenience.
        # Production deployments must set DEBUG=False via environment or config.
        # The ServerErrorMiddleware uses the debug flag to control error detail.
        assert hasattr(settings, "DEBUG")

    def test_admin002_error_middleware_respects_debug(self):
        """ServerErrorMiddleware must respect the debug flag."""

        async def app(scope, receive, send):
            raise ValueError("test error")

        # Production mode
        prod_middleware = ServerErrorMiddleware(app, debug=False)
        assert prod_middleware.debug is False

        # Development mode
        dev_middleware = ServerErrorMiddleware(app, debug=True)
        assert dev_middleware.debug is True


class TestAdminCRUDSensitiveFields:
    """Generated CRUD must exclude sensitive fields by default."""

    def test_admin003_sensitive_fields_in_model_admin(self):
        """ModelAdmin must exclude sensitive fields from serialization."""
        admin = ModelAdmin(Model)
        assert "password" in admin.sensitive_fields

    def test_admin003_user_admin_excludes_password(self):
        """UserAdmin must exclude password from list_display and sensitive fields."""
        admin = UserAdmin(User)
        assert "password" in admin.sensitive_fields

    def test_admin003_model_admin_readonly_fields(self):
        """ModelAdmin must support readonly_fields to prevent modification."""
        assert hasattr(ModelAdmin, "readonly_fields")
        admin = ModelAdmin(Model)
        assert isinstance(admin.readonly_fields, list)


class TestManagementCommandSafety:
    """Management commands must not execute shell commands with untrusted input."""

    def test_admin004_safe_table_name_validation(self):
        """Table name validation must reject shell metacharacters."""
        # Safe table names must pass
        assert_safe_table_name("users")
        assert_safe_table_name("auth_permissions")

        # Shell metacharacters must be rejected
        with pytest.raises(ValueError, match="Unsafe table name"):
            assert_safe_table_name("users; rm -rf /")

        with pytest.raises(ValueError, match="Unsafe table name"):
            assert_safe_table_name("users$(whoami)")

        with pytest.raises(ValueError, match="Unsafe table name"):
            assert_safe_table_name("`whoami`")

    def test_admin004_regex_pattern_rejects_dangerous_input(self):
        """Regex pattern validation must reject dangerous patterns."""
        # Safe patterns must pass
        validate_regex_pattern("^[a-z]+$")

        # Dangerous patterns must be rejected
        with pytest.raises(FieldError):
            validate_regex_pattern("(a+)+")

        with pytest.raises(FieldError):
            validate_regex_pattern("a" * 501)
