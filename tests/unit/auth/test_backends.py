"""Unit tests for openviper.auth.backends module."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.backends import (
    _get_client_ip,
    _update_last_login,
    authenticate,
    login,
    logout,
)
from openviper.auth.models import AnonymousUser


class TestAuthenticate:
    """Tests for authenticate function."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock user with async check_password."""
        user = MagicMock()
        user.pk = 42
        user.username = "testuser"
        user.email = "test@example.com"
        user.check_password = AsyncMock(return_value=True)
        return user

    @pytest.fixture
    def mock_queryset(self, mock_user):
        """Create a mock queryset that returns the user."""
        queryset = MagicMock()
        queryset.first = AsyncMock(return_value=mock_user)
        return queryset

    @pytest.mark.asyncio
    async def test_successful_authentication(self, mock_user, mock_queryset):

        with patch("openviper.auth.backends.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.filter.return_value = mock_queryset
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.backends.asyncio.create_task"):
                user = await authenticate("testuser", "password123")

        assert user is mock_user

    @pytest.mark.asyncio
    async def test_user_not_found_returns_none(self):

        queryset = MagicMock()
        queryset.first = AsyncMock(return_value=None)

        with patch("openviper.auth.backends.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.filter.return_value = queryset
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.backends.check_password", new=AsyncMock()):
                result = await authenticate("nonexistent", "password")

        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_password_returns_none(self, mock_queryset):

        # Make password check fail
        mock_queryset.first.return_value.check_password = AsyncMock(return_value=False)

        with patch("openviper.auth.backends.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.filter.return_value = mock_queryset
            mock_get_model.return_value = mock_model

            result = await authenticate("testuser", "wrongpass")

        assert result is None

    @pytest.mark.asyncio
    async def test_logs_authentication_events(self, mock_user, mock_queryset):

        mock_request = MagicMock()
        mock_request.client = MagicMock(host="192.168.1.1")
        mock_request.headers = {}

        with patch("openviper.auth.backends.get_user_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.objects.filter.return_value = mock_queryset
            mock_get_model.return_value = mock_model

            with patch("openviper.auth.backends.asyncio.create_task"):
                with patch("openviper.auth.backends.logger") as mock_logger:
                    await authenticate("testuser", "password123", request=mock_request)

                    # Successful auth is silent; only failures are logged
                    mock_logger.info.assert_not_called()


class TestLogin:
    """Tests for login function."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.pk = 42
        user.username = "testuser"
        return user

    @pytest.fixture
    def mock_request(self):
        request = MagicMock()
        request.cookies = {}
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {}
        return request

    @pytest.mark.asyncio
    async def test_creates_session(self, mock_user, mock_request):
        mock_session = MagicMock()
        mock_session.key = "test-session-key"
        mock_store = MagicMock()
        mock_store.create = AsyncMock(return_value=mock_session)
        mock_request._session = None

        with patch("openviper.auth.backends.get_session_store", return_value=mock_store):
            session_key = await login(mock_request, mock_user)

        assert session_key == "test-session-key"
        assert mock_request.user is mock_user

    @pytest.mark.asyncio
    async def test_sets_cookie_on_response(self, mock_user, mock_request):
        mock_response = MagicMock()
        mock_response.set_cookie = MagicMock()

        mock_session = MagicMock()
        mock_session.key = "test-key"
        mock_store = MagicMock()
        mock_store.create = AsyncMock(return_value=mock_session)
        mock_request._session = None

        with patch("openviper.auth.backends.get_session_store", return_value=mock_store):
            with patch("openviper.auth.backends.settings") as mock_settings:
                mock_settings.SESSION_COOKIE_NAME = "sessionid"
                mock_settings.SESSION_COOKIE_DOMAIN = None
                mock_settings.SESSION_TIMEOUT = datetime.timedelta(hours=1)
                mock_settings.SESSION_COOKIE_HTTPONLY = True
                mock_settings.SESSION_COOKIE_SECURE = False
                mock_settings.SESSION_COOKIE_SAMESITE = "lax"
                mock_settings.SESSION_COOKIE_PATH = "/"

                await login(mock_request, mock_user, mock_response)

        mock_response.set_cookie.assert_called_once()
        call_kwargs = mock_response.set_cookie.call_args
        assert call_kwargs.kwargs["key"] == "sessionid"
        assert call_kwargs.kwargs["value"] == "test-key"


class TestLogout:
    """Tests for logout function."""

    @pytest.fixture
    def mock_request(self):
        request = MagicMock()
        request.cookies = {"sessionid": "test-session-key"}
        request.user = MagicMock(pk=42, username="testuser")
        request.client = MagicMock(host="127.0.0.1")
        request.headers = {}
        return request

    @pytest.mark.asyncio
    async def test_deletes_session(self, mock_request):

        with patch("openviper.auth.backends.delete_session", new=AsyncMock()) as mock_delete:
            with patch("openviper.auth.backends.settings") as mock_settings:
                mock_settings.SESSION_COOKIE_NAME = "sessionid"
                await logout(mock_request)

        mock_delete.assert_called_once_with("test-session-key")
        assert isinstance(mock_request.user, AnonymousUser)

    @pytest.mark.asyncio
    async def test_deletes_cookie_on_response(self, mock_request):

        mock_response = MagicMock()
        mock_response.delete_cookie = MagicMock()

        with patch("openviper.auth.backends.delete_session", new=AsyncMock()):
            with patch("openviper.auth.backends.settings") as mock_settings:
                mock_settings.SESSION_COOKIE_NAME = "sessionid"
                mock_settings.SESSION_COOKIE_DOMAIN = None
                await logout(mock_request, mock_response)

        mock_response.delete_cookie.assert_called_once_with("sessionid", domain=None)

    @pytest.mark.asyncio
    async def test_handles_no_session_gracefully(self):

        request = MagicMock()
        request.cookies = {}
        request.user = MagicMock()
        request.headers = {}

        with patch("openviper.auth.backends.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            await logout(request)

        assert isinstance(request.user, AnonymousUser)


class TestGetClientIp:
    """Tests for _get_client_ip helper function."""

    def test_returns_unknown_for_none_request(self):

        assert _get_client_ip(None) == "unknown"

    def test_extracts_from_x_forwarded_for(self):
        # Headers are only trusted when the direct connection comes from a
        # configured TRUSTED_PROXIES address.
        request = MagicMock()
        request.client.host = "10.10.0.1"
        request.headers = {"x-forwarded-for": "203.0.113.5, 10.10.0.1"}

        with patch("openviper.auth.backends.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = ["10.10.0.1"]
            assert _get_client_ip(request) == "203.0.113.5"

    def test_x_forwarded_for_ignored_without_trusted_proxies(self):
        # Without TRUSTED_PROXIES, proxy headers must not override the real IP.
        request = MagicMock()
        request.client.host = "1.2.3.4"
        request.headers = {"x-forwarded-for": "5.6.7.8"}

        with patch("openviper.auth.backends.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = []
            assert _get_client_ip(request) == "1.2.3.4"

    def test_extracts_from_x_real_ip(self):
        request = MagicMock()
        request.client.host = "10.10.0.2"
        request.headers = {"x-forwarded-for": None, "x-real-ip": "172.16.0.1"}

        mock_headers = MagicMock()
        mock_headers.get.side_effect = lambda k, d=None: {
            "x-forwarded-for": None,
            "x-real-ip": "172.16.0.1",
        }.get(k, d)
        request.headers = mock_headers

        with patch("openviper.auth.backends.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = ["10.10.0.2"]
            assert _get_client_ip(request) == "172.16.0.1"

    def test_x_real_ip_ignored_without_trusted_proxies(self):
        request = MagicMock()
        request.client.host = "1.2.3.4"
        mock_headers = MagicMock()
        mock_headers.get.side_effect = lambda k, d=None: {
            "x-real-ip": "9.9.9.9",
        }.get(k, d)
        request.headers = mock_headers

        with patch("openviper.auth.backends.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = []
            assert _get_client_ip(request) == "1.2.3.4"

    def test_falls_back_to_client_host(self):

        # Create a mock with headers that return None for get()
        mock_headers = MagicMock()
        mock_headers.get.return_value = None

        request = MagicMock()
        request.headers = mock_headers
        request.client = MagicMock()
        request.client.host = "192.168.1.100"

        assert _get_client_ip(request) == "192.168.1.100"

    def test_returns_unknown_when_no_client(self):

        request = MagicMock()
        request.headers = {}
        request.client = None

        assert _get_client_ip(request) == "unknown"


class TestUpdateLastLogin:
    """Tests for _update_last_login function."""

    @pytest.mark.asyncio
    async def test_updates_last_login_field(self):

        user = MagicMock()
        user.save = AsyncMock()

        await _update_last_login(user)

        assert user.last_login is not None
        user.save.assert_called_once_with(ignore_permissions=True)

    @pytest.mark.asyncio
    async def test_handles_save_error_gracefully(self):

        user = MagicMock()
        user.pk = 1
        user.save = AsyncMock(side_effect=Exception("DB error"))

        # Should not raise
        await _update_last_login(user)
