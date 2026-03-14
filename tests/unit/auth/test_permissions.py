"""Unit tests for openviper.auth.permissions module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.permission_checker import _CT_PERMISSION_CACHE
from openviper.auth.permissions import PermissionError, check_permission_for_model  # noqa: A004


class TestCheckPermissionForModel:
    """Tests for check_permission_for_model function."""

    @pytest.mark.asyncio
    async def test_allows_when_ignore_permissions_true(self):
        """Should bypass all checks when ignore_permissions=True."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "testapp"

        # Should not raise
        await check_permission_for_model(mock_model, "create", ignore_permissions=True)

    @pytest.mark.asyncio
    async def test_allows_auth_models_without_check(self):
        """Should allow auth models without permission check."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "auth"

        # Should not raise
        await check_permission_for_model(mock_model, "create")

    @pytest.mark.asyncio
    async def test_allows_public_models(self):
        """Should allow public models (no ContentTypePermissions exist)."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "blog"
        mock_model._model_name = "Post"

        mock_content_type = MagicMock()
        mock_content_type.pk = 1

        with patch("openviper.auth.permission_checker.ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first = AsyncMock(return_value=mock_content_type)

            with patch("openviper.auth.permission_checker.ContentTypePermission") as mock_ctp:
                mock_ctp.objects.filter.return_value.count = AsyncMock(return_value=0)

                # Should not raise - model is public
                await check_permission_for_model(mock_model, "read")

    @pytest.mark.asyncio
    async def test_allows_when_no_user_in_context(self):
        """Should allow access when no user is in context (CLI/management commands)."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "blog"
        mock_model._model_name = "Post"

        mock_content_type = MagicMock()
        mock_content_type.pk = 1

        with patch("openviper.auth.permission_checker.ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first = AsyncMock(return_value=mock_content_type)

            with patch("openviper.auth.permission_checker.ContentTypePermission") as mock_ctp:
                mock_ctp.objects.filter.return_value.count = AsyncMock(return_value=1)

                with patch("openviper.auth.permission_core.current_user") as mock_ctx:
                    mock_ctx.get.return_value = None

                    # Should not raise - no user context
                    await check_permission_for_model(mock_model, "create")

    @pytest.mark.asyncio
    async def test_allows_superuser(self):
        """Should allow superusers to access any model."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "blog"
        mock_model._model_name = "Post"

        mock_user = MagicMock()
        mock_user.is_superuser = True

        mock_content_type = MagicMock()
        mock_content_type.pk = 1

        with patch("openviper.auth.permission_checker.ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first = AsyncMock(return_value=mock_content_type)

            with patch("openviper.auth.permission_checker.ContentTypePermission") as mock_ctp:
                mock_ctp.objects.filter.return_value.count = AsyncMock(return_value=1)

                with patch("openviper.auth.permission_core.current_user") as mock_ctx:
                    mock_ctx.get.return_value = mock_user

                    # Should not raise - user is superuser
                    await check_permission_for_model(mock_model, "delete")

    @pytest.mark.asyncio
    async def test_raises_permission_error_when_unauthorized(self):
        """Should raise PermissionError when user lacks permission."""
        # Clear cache to avoid test isolation issues

        _CT_PERMISSION_CACHE.clear()

        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "blog"
        mock_model._model_name = "Post"

        mock_user = MagicMock()
        mock_user.is_superuser = False
        mock_user.has_model_perm = AsyncMock(return_value=False)

        mock_content_type = MagicMock()
        mock_content_type.pk = 1

        with patch("openviper.auth.permission_checker.ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first = AsyncMock(return_value=mock_content_type)

            with patch("openviper.auth.permission_checker.ContentTypePermission") as mock_ctp:
                mock_ctp.objects.filter.return_value.count = AsyncMock(return_value=1)

                with patch("openviper.auth.permission_core.current_user") as mock_ctx:
                    mock_ctx.get.return_value = mock_user

                    with pytest.raises(PermissionError, match="Unauthorized"):
                        await check_permission_for_model(mock_model, "delete")

    @pytest.mark.asyncio
    async def test_allows_authorized_user(self):
        """Should allow user with correct permission."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "blog"
        mock_model._model_name = "Post"

        mock_user = MagicMock()
        mock_user.is_superuser = False
        mock_user.has_model_perm = AsyncMock(return_value=True)

        mock_content_type = MagicMock()
        mock_content_type.pk = 1

        with patch("openviper.auth.permission_checker.ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first = AsyncMock(return_value=mock_content_type)

            with patch("openviper.auth.permission_checker.ContentTypePermission") as mock_ctp:
                mock_ctp.objects.filter.return_value.count = AsyncMock(return_value=1)

                with patch("openviper.auth.permission_core.current_user") as mock_ctx:
                    mock_ctx.get.return_value = mock_user

                    # Should not raise - user has permission
                    await check_permission_for_model(mock_model, "read")

    @pytest.mark.asyncio
    async def test_uses_cache_for_content_type_check(self):
        """Should cache ContentType permission check results."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "blog"
        mock_model._model_name = "Post"

        # Clear cache

        _CT_PERMISSION_CACHE.clear()

        mock_content_type = MagicMock()
        mock_content_type.pk = 1

        with patch("openviper.auth.permission_checker.ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first = AsyncMock(return_value=mock_content_type)

            with patch("openviper.auth.permission_checker.ContentTypePermission") as mock_ctp:
                mock_ctp.objects.filter.return_value.count = AsyncMock(return_value=0)

                # First call - should hit DB
                await check_permission_for_model(mock_model, "create")

                # Second call - should use cache
                await check_permission_for_model(mock_model, "create")

                # ContentType query should only be called once
                assert mock_ct.objects.filter.return_value.first.call_count == 1

    @pytest.mark.asyncio
    async def test_bypasses_check_with_ignore_permissions_context(self):
        """Should bypass checks when ignore_permissions_ctx is set."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "testapp"

        with patch("openviper.auth.permission_core.ignore_permissions_ctx") as mock_ctx:
            mock_ctx.get.return_value = True

            # Should not raise
            await check_permission_for_model(mock_model, "delete")

    @pytest.mark.asyncio
    async def test_handles_model_without_content_type(self):
        """Should treat models without ContentType as public."""
        mock_model = MagicMock(__name__="MockModel")
        mock_model._app_name = "blog"
        mock_model._model_name = "Post"

        # Clear cache

        _CT_PERMISSION_CACHE.clear()

        with patch("openviper.auth.permission_checker.ContentType") as mock_ct:
            mock_ct.objects.filter.return_value.first = AsyncMock(return_value=None)

            # Should not raise - no ContentType means public model
            await check_permission_for_model(mock_model, "read")


class TestPermissionErrorException:
    """Tests for PermissionError exception."""

    def test_is_exception(self):
        """Should be an exception."""
        assert issubclass(PermissionError, Exception)

    def test_can_be_raised_with_message(self):
        """Should be raisable with a message."""
        with pytest.raises(PermissionError, match="Access denied"):
            raise PermissionError("Access denied")
