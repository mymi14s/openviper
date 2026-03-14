"""Unit tests for openviper.auth.user module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.user import get_user_by_id


class TestGetUserById:
    """Tests for get_user_by_id function."""

    @pytest.mark.asyncio
    async def test_returns_user_when_found(self):
        """Should return user when found."""
        mock_user = MagicMock()
        mock_user.id = 42

        with patch("openviper.auth.user.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.get_or_none = AsyncMock(return_value=mock_user)
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.user.cast_to_pk_type", return_value=42):
                user = await get_user_by_id(42)

        assert user is mock_user

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """Should return None when user not found."""
        with patch("openviper.auth.user.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.get_or_none = AsyncMock(return_value=None)
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.user.cast_to_pk_type", return_value=999):
                user = await get_user_by_id(999)

        assert user is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_user_id(self):
        """Should return None for empty user_id."""
        user = await get_user_by_id(None)
        assert user is None

        user = await get_user_by_id("")
        assert user is None

    @pytest.mark.asyncio
    async def test_handles_value_error(self):
        """Should return None on ValueError (invalid ID format)."""
        with patch("openviper.auth.user.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.user.cast_to_pk_type", side_effect=ValueError("invalid")):
                user = await get_user_by_id("invalid-id")

        assert user is None

    @pytest.mark.asyncio
    async def test_handles_type_error(self):
        """Should return None on TypeError."""
        with patch("openviper.auth.user.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.user.cast_to_pk_type", side_effect=TypeError("invalid")):
                user = await get_user_by_id(object())

        assert user is None

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self):
        """Should return None on unexpected exceptions."""
        with patch("openviper.auth.user.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.get_or_none = AsyncMock(side_effect=Exception("DB error"))
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.user.cast_to_pk_type", return_value=42):
                user = await get_user_by_id(42)

        assert user is None

    @pytest.mark.asyncio
    async def test_casts_pk_type_correctly(self):
        """Should cast user_id to correct PK type."""
        mock_user = MagicMock()

        with patch("openviper.auth.user.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.get_or_none = AsyncMock(return_value=mock_user)
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.user.cast_to_pk_type") as mock_cast:
                mock_cast.return_value = 42
                await get_user_by_id("42")
                mock_cast.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_ignore_permissions(self):
        """Should query with ignore_permissions=True."""
        mock_user = MagicMock()

        with patch("openviper.auth.user.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_get_or_none = AsyncMock(return_value=mock_user)
            mock_model.objects.get_or_none = mock_get_or_none
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.user.cast_to_pk_type", return_value=42):
                await get_user_by_id(42)

        # Verify called with ignore_permissions=True
        call_kwargs = mock_get_or_none.call_args[1]
        assert call_kwargs.get("ignore_permissions") is True
