"""Unit tests for openviper.auth.decorators module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.auth.decorators import (
    login_required,
    permission_required,
    role_required,
    staff_required,
    superuser_required,
)
from openviper.exceptions import PermissionDenied, Unauthorized
from openviper.http.request import Request


class TestLoginRequired:
    """Tests for @login_required decorator."""

    @pytest.mark.asyncio
    async def test_allows_authenticated_user(self):
        """Should allow authenticated users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True

        @login_required
        async def my_view(request):
            return {"success": True}

        result = await my_view(mock_request)
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_anonymous_user(self):
        """Should raise Unauthorized for anonymous users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = False

        @login_required
        async def my_view(request):
            return {"success": True}

        with pytest.raises(Unauthorized):
            await my_view(mock_request)

    @pytest.mark.asyncio
    async def test_raises_unauthorized_when_no_request(self):
        """Should raise Unauthorized when request is None."""

        @login_required
        async def my_view():
            return {"success": True}

        with pytest.raises(Unauthorized):
            await my_view()

    @pytest.mark.asyncio
    async def test_works_with_sync_functions(self):
        """Should work with synchronous view functions."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True

        @login_required
        def my_sync_view(request):
            return {"success": True}

        result = await my_sync_view(mock_request)
        assert result == {"success": True}


class TestPermissionRequired:
    """Tests for @permission_required decorator."""

    @pytest.mark.asyncio
    async def test_allows_user_with_permission(self):
        """Should allow users with required permission."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.has_perm = AsyncMock(return_value=True)

        @permission_required("post.create")
        async def my_view(request):
            return {"success": True}

        result = await my_view(mock_request)
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_anonymous_user(self):
        """Should raise Unauthorized for anonymous users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = False

        @permission_required("post.create")
        async def my_view(request):
            return {"success": True}

        with pytest.raises(Unauthorized):
            await my_view(mock_request)

    @pytest.mark.asyncio
    async def test_raises_permission_denied_without_permission(self):
        """Should raise PermissionDenied when user lacks permission."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.has_perm = AsyncMock(return_value=False)

        @permission_required("post.delete")
        async def my_view(request):
            return {"success": True}

        with pytest.raises(PermissionDenied, match="Permission 'post.delete' required"):
            await my_view(mock_request)

    @pytest.mark.asyncio
    async def test_checks_correct_permission(self):
        """Should check the specified permission."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.has_perm = AsyncMock(return_value=True)

        @permission_required("custom.permission")
        async def my_view(request):
            return {"success": True}

        await my_view(mock_request)
        mock_request.user.has_perm.assert_called_once_with("custom.permission")


class TestRoleRequired:
    """Tests for @role_required decorator."""

    @pytest.mark.asyncio
    async def test_allows_user_with_role(self):
        """Should allow users with required role."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.has_role = AsyncMock(return_value=True)

        @role_required("admin")
        async def my_view(request):
            return {"success": True}

        result = await my_view(mock_request)
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_anonymous_user(self):
        """Should raise Unauthorized for anonymous users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = False

        @role_required("admin")
        async def my_view(request):
            return {"success": True}

        with pytest.raises(Unauthorized):
            await my_view(mock_request)

    @pytest.mark.asyncio
    async def test_raises_permission_denied_without_role(self):
        """Should raise PermissionDenied when user lacks role."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.has_role = AsyncMock(return_value=False)

        @role_required("admin")
        async def my_view(request):
            return {"success": True}

        with pytest.raises(PermissionDenied, match="Role 'admin' required"):
            await my_view(mock_request)

    @pytest.mark.asyncio
    async def test_checks_correct_role(self):
        """Should check the specified role."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.has_role = AsyncMock(return_value=True)

        @role_required("manager")
        async def my_view(request):
            return {"success": True}

        await my_view(mock_request)
        mock_request.user.has_role.assert_called_once_with("manager")


class TestSuperuserRequired:
    """Tests for @superuser_required decorator."""

    @pytest.mark.asyncio
    async def test_allows_superuser(self):
        """Should allow superusers."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.is_superuser = True

        @superuser_required
        async def my_view(request):
            return {"success": True}

        result = await my_view(mock_request)
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_anonymous_user(self):
        """Should raise Unauthorized for anonymous users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = False

        @superuser_required
        async def my_view(request):
            return {"success": True}

        with pytest.raises(Unauthorized):
            await my_view(mock_request)

    @pytest.mark.asyncio
    async def test_raises_permission_denied_for_regular_user(self):
        """Should raise PermissionDenied for non-superusers."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.is_superuser = False

        @superuser_required
        async def my_view(request):
            return {"success": True}

        with pytest.raises(PermissionDenied, match="Superuser access required"):
            await my_view(mock_request)


class TestStaffRequired:
    """Tests for @staff_required decorator."""

    @pytest.mark.asyncio
    async def test_allows_staff_user(self):
        """Should allow staff users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.is_staff = True

        @staff_required
        async def my_view(request):
            return {"success": True}

        result = await my_view(mock_request)
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_anonymous_user(self):
        """Should raise Unauthorized for anonymous users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = False

        @staff_required
        async def my_view(request):
            return {"success": True}

        with pytest.raises(Unauthorized):
            await my_view(mock_request)

    @pytest.mark.asyncio
    async def test_raises_permission_denied_for_non_staff(self):
        """Should raise PermissionDenied for non-staff users."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True
        mock_request.user.is_staff = False

        @staff_required
        async def my_view(request):
            return {"success": True}

        with pytest.raises(PermissionDenied, match="Staff access required"):
            await my_view(mock_request)


class TestDecoratorHelpers:
    """Tests for decorator helper functions."""

    @pytest.mark.asyncio
    async def test_finds_request_in_positional_args(self):
        """Should find Request object in positional args."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True

        @login_required
        async def my_view(request, other_arg):
            return {"success": True}

        result = await my_view(mock_request, "other")
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_finds_request_in_keyword_args(self):
        """Should find Request object in keyword args."""
        mock_request = MagicMock(spec=Request)
        mock_request.user = MagicMock()
        mock_request.user.is_authenticated = True

        @login_required
        async def my_view(*, request):
            return {"success": True}

        result = await my_view(request=mock_request)
        assert result == {"success": True}
