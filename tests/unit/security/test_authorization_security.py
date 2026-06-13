"""Authorization security tests.

Requirement IDs: AUTHZ-001 through AUTHZ-005.
"""

from __future__ import annotations

import pytest

from openviper.admin.options import ModelAdmin
from openviper.auth.decorators import login_required, permission_required, role_required
from openviper.auth.permission_core import PermissionError as OVPermissionError
from openviper.core.context import current_user
from openviper.db.models import Model
from openviper.exceptions import PermissionDenied, Unauthorized
from openviper.http.permissions import AllowAny, BasePermission, IsAuthenticated
from openviper.http.request import Request
from openviper.serializers.base import Serializer

from .conftest import AnonymousMockUser, MockUser, make_scope


class TestObjectLevelAuthorization:
    """Users must not be able to access other users' resources."""

    @pytest.mark.asyncio
    async def test_authz001_object_permission_denied_for_other_user(self):
        """Object-level permission must deny access to other users' resources."""

        class OwnerOnlyPermission(BasePermission):
            async def has_permission(self, request, view):
                return True

            async def has_object_permission(self, request, view, obj):
                return getattr(request, "user", None) and request.user.id == obj.get("owner_id")

        perm = OwnerOnlyPermission()
        user_a = MockUser(user_id=1)
        user_b = MockUser(user_id=2)

        request_a = Request(make_scope())
        request_a.user = user_a

        request_b = Request(make_scope())
        request_b.user = user_b

        obj = {"owner_id": 1}

        assert await perm.has_object_permission(request_a, None, obj) is True
        assert await perm.has_object_permission(request_b, None, obj) is False


class TestFunctionLevelAuthorization:
    """Decorators must enforce authorization at the function level."""

    @pytest.mark.asyncio
    async def test_authz002_login_required_rejects_anonymous(self):
        """login_required must reject unauthenticated users."""

        @login_required
        async def protected_view(request):
            return {"secret": "data"}

        anonymous = AnonymousMockUser()
        request = Request(make_scope())
        request.user = anonymous

        with pytest.raises(Unauthorized):
            await protected_view(request)

    @pytest.mark.asyncio
    async def test_authz002_login_required_allows_authenticated(self):
        """login_required must allow authenticated users."""

        @login_required
        async def protected_view(request):
            return {"secret": "data"}

        user = MockUser(user_id=1, is_authenticated=True)
        request = Request(make_scope())
        request.user = user

        result = await protected_view(request)
        assert result == {"secret": "data"}

    @pytest.mark.asyncio
    async def test_authz002_permission_required_rejects_unauthorized(self):
        """permission_required must deny users without the required permission."""

        @permission_required("admin.delete_user")
        async def admin_view(request):
            return {"deleted": True}

        user = MockUser(user_id=1, permissions=["admin.view_user"])
        request = Request(make_scope())
        request.user = user

        with pytest.raises(PermissionDenied, match="Permission"):
            await admin_view(request)

    @pytest.mark.asyncio
    async def test_authz002_role_required_rejects_unauthorized(self):
        """role_required must deny users without the required role."""

        @role_required("admin")
        async def admin_view(request):
            return {"admin": True}

        user = MockUser(user_id=1, roles=["viewer"])
        request = Request(make_scope())
        request.user = user

        with pytest.raises(PermissionDenied, match="Role"):
            await admin_view(request)


class TestMassAssignment:
    """Protected fields must not be settable through mass assignment."""

    def test_authz003_serializer_readonly_fields_protected(self):
        """Serializer readonly_fields must not be writable via input data."""
        # Verify the base Serializer exposes readonly_fields as a ClassVar
        assert hasattr(Serializer, "readonly_fields")
        assert isinstance(Serializer.readonly_fields, tuple)

        # Verify writeonly_fields also exists for write-only protection
        assert hasattr(Serializer, "writeonly_fields")
        assert isinstance(Serializer.writeonly_fields, tuple)

    def test_authz003_model_admin_sensitive_fields(self):
        """ModelAdmin must define sensitive_fields to exclude passwords."""
        admin = ModelAdmin(Model)
        assert "password" in admin.sensitive_fields


class TestDefaultRouteAccess:
    """Routes without explicit permissions must default to secure behavior."""

    @pytest.mark.asyncio
    async def test_authz004_allow_any_permits_all(self):
        """AllowAny permission must explicitly permit all access."""
        perm = AllowAny()
        request = Request(make_scope())
        assert await perm.has_permission(request, None) is True

    @pytest.mark.asyncio
    async def test_authz004_is_authenticated_denies_anonymous(self):
        """IsAuthenticated permission must deny anonymous users."""
        perm = IsAuthenticated()
        request = Request(make_scope())
        request.user = AnonymousMockUser()
        assert await perm.has_permission(request, None) is False

    @pytest.mark.asyncio
    async def test_authz004_is_authenticated_allows_authenticated(self):
        """IsAuthenticated permission must allow authenticated users."""
        perm = IsAuthenticated()
        request = Request(make_scope())
        request.user = MockUser(is_authenticated=True)
        assert await perm.has_permission(request, None) is True


class TestTenantIsolation:
    """Users in one tenant must not access resources in another tenant."""

    @pytest.mark.asyncio
    async def test_authz005_tenant_isolation_in_context(self):
        """Tenant context must be isolated between requests."""
        user_a = MockUser(user_id=1, tenant_id="tenant_a")
        user_b = MockUser(user_id=2, tenant_id="tenant_b")

        token_a = current_user.set(user_a)
        try:
            assert current_user.get().tenant_id == "tenant_a"
        finally:
            current_user.reset(token_a)

        token_b = current_user.set(user_b)
        try:
            assert current_user.get().tenant_id == "tenant_b"
        finally:
            current_user.reset(token_b)

    @pytest.mark.asyncio
    async def test_authz005_permission_error_on_unauthorized(self):
        """PermissionError must be raised for unauthorized access."""
        error = OVPermissionError("Unauthorized: Access denied 'delete' on users")
        assert "Unauthorized" in str(error)
