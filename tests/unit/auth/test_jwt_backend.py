"""Tests for openviper.auth.backends.jwt_backend module.

Tests JWT authentication backend including:
- Bearer token extraction from headers
- Token verification and validation
- Token revocation checking
- User retrieval from token payload
- Error handling for expired/invalid tokens
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.backends.jwt_backend import JWTBackend
from openviper.exceptions import TokenExpired


class TestJWTBackend:
    """Test JWT authentication backend."""

    @pytest.mark.asyncio
    async def test_authenticate_success_with_valid_token(self):
        """Should authenticate user with valid JWT token."""
        mock_user = MagicMock()
        mock_user.is_active = True

        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            with patch("openviper.auth.backends.jwt_backend.is_token_revoked") as mock_revoked:
                with patch("openviper.auth.backends.jwt_backend.get_user_by_id") as mock_get_user:
                    mock_decode.return_value = {
                        "sub": "42",
                        "jti": "token-id-123",
                        "type": "access",
                    }
                    mock_revoked.side_effect = AsyncMock(return_value=False)
                    mock_get_user.side_effect = AsyncMock(return_value=mock_user)

                    result = await backend.authenticate(scope)

                    assert result is not None
                    user, auth_info = result
                    assert user == mock_user
                    assert auth_info["type"] == "jwt"
                    assert auth_info["token"] == "test-token-123"

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_without_authorization_header(self):
        """Should return None when Authorization header is missing."""
        backend = JWTBackend()
        scope = {"type": "http", "headers": []}

        result = await backend.authenticate(scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_without_bearer_prefix(self):
        """Should return None when Authorization header doesn't use Bearer scheme."""
        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Basic dXNlcjpwYXNz")],
        }

        result = await backend.authenticate(scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_for_revoked_token(self):
        """Should return None when token has been revoked."""
        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            with patch("openviper.auth.backends.jwt_backend.is_token_revoked") as mock_revoked:
                mock_decode.return_value = {
                    "sub": "42",
                    "jti": "token-id-123",
                    "type": "access",
                }
                mock_revoked.return_value = True

                result = await backend.authenticate(scope)
                assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_for_expired_token(self):
        """Should return None when token has expired."""
        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.side_effect = TokenExpired()

            result = await backend.authenticate(scope)
            assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_for_invalid_token(self):
        """Should return None when token is invalid."""
        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer invalid-token")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.side_effect = Exception("Invalid token")

            result = await backend.authenticate(scope)
            assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_when_sub_missing(self):
        """Should return None when token payload is missing sub claim."""
        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            with patch("openviper.auth.backends.jwt_backend.is_token_revoked") as mock_revoked:
                mock_decode.return_value = {
                    "jti": "token-id-123",
                    "type": "access",
                }
                mock_revoked.return_value = False

                result = await backend.authenticate(scope)
                assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_when_user_not_found(self):
        """Should return None when user ID from token doesn't exist."""
        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            with patch("openviper.auth.backends.jwt_backend.is_token_revoked") as mock_revoked:
                with patch("openviper.auth.backends.jwt_backend.get_user_by_id") as mock_get_user:
                    mock_decode.return_value = {
                        "sub": "999",
                        "jti": "token-id-123",
                        "type": "access",
                    }
                    mock_revoked.return_value = False
                    mock_get_user.return_value = None

                    result = await backend.authenticate(scope)
                    assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none_for_inactive_user(self):
        """Should return None when user is inactive."""
        mock_user = MagicMock()
        mock_user.is_active = False

        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            with patch("openviper.auth.backends.jwt_backend.is_token_revoked") as mock_revoked:
                with patch("openviper.auth.backends.jwt_backend.get_user_by_id") as mock_get_user:
                    mock_decode.return_value = {
                        "sub": "42",
                        "jti": "token-id-123",
                        "type": "access",
                    }
                    mock_revoked.return_value = False
                    mock_get_user.return_value = mock_user

                    result = await backend.authenticate(scope)
                    assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_handles_token_without_jti(self):
        """Should handle token without jti claim gracefully."""
        mock_user = MagicMock()
        mock_user.is_active = True

        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            with patch("openviper.auth.backends.jwt_backend.get_user_by_id") as mock_get_user:
                mock_decode.return_value = {
                    "sub": "42",
                    "type": "access",
                }
                mock_get_user.return_value = mock_user

                result = await backend.authenticate(scope)

                assert result is not None
                user, auth_info = result
                assert user == mock_user

    @pytest.mark.asyncio
    async def test_authenticate_handles_multiple_authorization_headers(self):
        """Should use first Authorization header when multiple present."""
        mock_user = MagicMock()
        mock_user.is_active = True

        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer first-token"),
                (b"authorization", b"Bearer second-token"),
            ],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            with patch("openviper.auth.backends.jwt_backend.is_token_revoked") as mock_revoked:
                with patch("openviper.auth.backends.jwt_backend.get_user_by_id") as mock_get_user:
                    mock_decode.return_value = {
                        "sub": "42",
                        "jti": "token-id-123",
                        "type": "access",
                    }
                    mock_revoked.return_value = False
                    mock_get_user.return_value = mock_user

                    result = await backend.authenticate(scope)

                    assert result is not None
                    mock_decode.assert_called_once_with("first-token")

    @pytest.mark.asyncio
    async def test_authenticate_handles_empty_bearer_token(self):
        """Should handle empty Bearer token gracefully."""
        backend = JWTBackend()
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer ")],
        }

        with patch("openviper.auth.backends.jwt_backend.decode_access_token") as mock_decode:
            mock_decode.side_effect = Exception("Empty token")

            result = await backend.authenticate(scope)
            assert result is None
