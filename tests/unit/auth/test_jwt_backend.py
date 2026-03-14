"""Unit tests for openviper.auth.backends.jwt_backend module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.backends.jwt_backend import JWTBackend
from openviper.exceptions import TokenExpired


class TestJWTBackendAuthenticate:
    """Tests for JWTBackend.authenticate method."""

    @pytest.fixture
    def jwt_backend(self):
        return JWTBackend()

    @pytest.fixture
    def mock_scope_with_bearer(self):
        return {
            "headers": [(b"authorization", b"Bearer validtoken123")],
            "path": "/api/test",
        }

    @pytest.fixture
    def mock_scope_no_auth(self):
        return {
            "headers": [],
            "path": "/api/test",
        }

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.pk = 42
        user.is_active = True
        return user

    @pytest.mark.asyncio
    async def test_returns_none_when_no_auth_header(self, jwt_backend, mock_scope_no_auth):
        result = await jwt_backend.authenticate(mock_scope_no_auth)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_bearer_token(self, jwt_backend):
        scope = {"headers": [(b"authorization", b"Basic dXNlcjpwYXNz")]}
        result = await jwt_backend.authenticate(scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_on_valid_token(
        self, jwt_backend, mock_scope_with_bearer, mock_user
    ):
        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.return_value = {"sub": "42", "jti": "unique-id"}

            with patch(
                "openviper.auth.backends.jwt_backend.is_token_revoked",
                new=AsyncMock(return_value=False),
            ):
                with patch(
                    "openviper.auth.backends.jwt_backend.get_user_by_id",
                    new=AsyncMock(return_value=mock_user),
                ):
                    result = await jwt_backend.authenticate(mock_scope_with_bearer)

        assert result is not None
        user, auth_info = result
        assert user is mock_user
        assert auth_info["type"] == "jwt"
        assert auth_info["token"] == "validtoken123"

    @pytest.mark.asyncio
    async def test_returns_none_when_token_revoked(self, jwt_backend, mock_scope_with_bearer):
        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.return_value = {"sub": "42", "jti": "revoked-id"}

            with patch(
                "openviper.auth.backends.jwt_backend.is_token_revoked",
                new=AsyncMock(return_value=True),
            ):
                result = await jwt_backend.authenticate(mock_scope_with_bearer)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_subject(self, jwt_backend, mock_scope_with_bearer):
        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.return_value = {"jti": "some-id"}  # No "sub" claim

            with patch(
                "openviper.auth.backends.jwt_backend.is_token_revoked",
                new=AsyncMock(return_value=False),
            ):
                result = await jwt_backend.authenticate(mock_scope_with_bearer)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_user_not_found(self, jwt_backend, mock_scope_with_bearer):
        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.return_value = {"sub": "42", "jti": "some-id"}

            with patch(
                "openviper.auth.backends.jwt_backend.is_token_revoked",
                new=AsyncMock(return_value=False),
            ):
                with patch(
                    "openviper.auth.backends.jwt_backend.get_user_by_id",
                    new=AsyncMock(return_value=None),
                ):
                    result = await jwt_backend.authenticate(mock_scope_with_bearer)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_user_inactive(self, jwt_backend, mock_scope_with_bearer):
        inactive_user = MagicMock()
        inactive_user.is_active = False

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.return_value = {"sub": "42", "jti": "some-id"}

            with patch(
                "openviper.auth.backends.jwt_backend.is_token_revoked",
                new=AsyncMock(return_value=False),
            ):
                with patch(
                    "openviper.auth.backends.jwt_backend.get_user_by_id",
                    new=AsyncMock(return_value=inactive_user),
                ):
                    result = await jwt_backend.authenticate(mock_scope_with_bearer)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_token_expired(self, jwt_backend, mock_scope_with_bearer):
        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.side_effect = TokenExpired()

            result = await jwt_backend.authenticate(mock_scope_with_bearer)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_general_exception(self, jwt_backend, mock_scope_with_bearer):
        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.side_effect = ValueError("Invalid token format")

            result = await jwt_backend.authenticate(mock_scope_with_bearer)

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_token_without_jti(self, jwt_backend, mock_scope_with_bearer, mock_user):
        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.return_value = {"sub": "42"}  # No jti claim

            with patch(
                "openviper.auth.backends.jwt_backend.get_user_by_id",
                new=AsyncMock(return_value=mock_user),
            ):
                result = await jwt_backend.authenticate(mock_scope_with_bearer)

        # Should still work without jti
        assert result is not None
