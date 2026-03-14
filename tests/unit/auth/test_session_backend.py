"""Unit tests for openviper.auth.backends.session_backend module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.backends.session_backend import SessionBackend


class TestSessionBackendAuthenticate:
    """Tests for SessionBackend.authenticate method."""

    @pytest.fixture
    def session_backend(self):
        return SessionBackend()

    @pytest.fixture
    def mock_scope_with_cookie(self):
        return {
            "headers": [(b"cookie", b"sessionid=valid_session_key_1234")],
            "path": "/dashboard",
        }

    @pytest.fixture
    def mock_scope_no_cookie(self):
        return {
            "headers": [],
            "path": "/dashboard",
        }

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.pk = 42
        user.username = "testuser"
        user.is_active = True
        return user

    @pytest.mark.asyncio
    async def test_returns_none_when_no_cookie_header(self, session_backend, mock_scope_no_cookie):
        result = await session_backend.authenticate(mock_scope_no_cookie)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_empty_cookie(self, session_backend):
        scope = {"headers": [(b"cookie", b"")]}
        result = await session_backend.authenticate(scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_on_valid_session(
        self, session_backend, mock_scope_with_cookie, mock_user
    ):
        with patch(
            "openviper.auth.backends.session_backend.get_user_from_session",
            new=AsyncMock(return_value=mock_user),
        ):
            result = await session_backend.authenticate(mock_scope_with_cookie)

        assert result is not None
        user, auth_info = result
        assert user is mock_user
        assert auth_info["type"] == "session"

    @pytest.mark.asyncio
    async def test_returns_none_when_session_invalid(self, session_backend, mock_scope_with_cookie):
        with patch(
            "openviper.auth.backends.session_backend.get_user_from_session",
            new=AsyncMock(return_value=None),
        ):
            result = await session_backend.authenticate(mock_scope_with_cookie)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_user_inactive(self, session_backend, mock_scope_with_cookie):
        inactive_user = MagicMock()
        inactive_user.is_active = False

        with patch(
            "openviper.auth.backends.session_backend.get_user_from_session",
            new=AsyncMock(return_value=inactive_user),
        ):
            result = await session_backend.authenticate(mock_scope_with_cookie)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, session_backend, mock_scope_with_cookie):
        with patch(
            "openviper.auth.backends.session_backend.get_user_from_session",
            new=AsyncMock(side_effect=ValueError("DB error")),
        ):
            result = await session_backend.authenticate(mock_scope_with_cookie)

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_multiple_headers(self, session_backend, mock_user):
        scope = {
            "headers": [
                (b"content-type", b"application/json"),
                (b"cookie", b"sessionid=test_session_key123"),
                (b"accept", b"*/*"),
            ],
            "path": "/api/data",
        }

        with patch(
            "openviper.auth.backends.session_backend.get_user_from_session",
            new=AsyncMock(return_value=mock_user),
        ):
            result = await session_backend.authenticate(scope)

        assert result is not None
        user, auth_info = result
        assert user is mock_user

    @pytest.mark.asyncio
    async def test_handles_missing_is_active_attribute(
        self, session_backend, mock_scope_with_cookie
    ):
        # User without is_active attribute (defaults to True)
        user = MagicMock(spec=["pk", "username"])
        user.pk = 1

        with patch(
            "openviper.auth.backends.session_backend.get_user_from_session",
            new=AsyncMock(return_value=user),
        ):
            result = await session_backend.authenticate(mock_scope_with_cookie)

        # Should return user (is_active defaults to True via getattr)
        assert result is not None
