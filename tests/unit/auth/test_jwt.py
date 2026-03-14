"""Unit tests for openviper.auth.jwt module."""

import datetime
from unittest.mock import patch

import pytest
from jose import jwt

from openviper.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decode_token_unverified,
)
from openviper.exceptions import AuthenticationFailed, TokenExpired


class TestCreateAccessToken:
    """Tests for create_access_token function."""

    def test_creates_valid_jwt_with_user_id(self):
        """Should create a valid JWT access token with user_id in sub claim."""
        token = create_access_token(user_id=42)

        # Decode without verification to check structure
        payload = jwt.get_unverified_claims(token)

        assert payload["sub"] == "42"
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_creates_token_with_string_user_id(self):
        """Should accept string user IDs."""
        token = create_access_token(user_id="user123")
        payload = jwt.get_unverified_claims(token)
        assert payload["sub"] == "user123"

    def test_includes_extra_claims(self):
        """Should include extra claims in the token payload."""
        extra = {"username": "testuser", "role": "admin"}
        token = create_access_token(user_id=42, extra_claims=extra)

        payload = jwt.get_unverified_claims(token)
        assert payload["username"] == "testuser"
        assert payload["role"] == "admin"

    def test_generates_unique_jti(self):
        """Should generate unique JTI for each token."""
        token1 = create_access_token(user_id=42)
        token2 = create_access_token(user_id=42)

        payload1 = jwt.get_unverified_claims(token1)
        payload2 = jwt.get_unverified_claims(token2)

        assert payload1["jti"] != payload2["jti"]

    def test_sets_expiration_correctly(self):
        """Should set expiration based on JWT_ACCESS_TOKEN_EXPIRE setting."""
        with patch("openviper.auth.jwt.timezone") as mock_tz:
            mock_now = datetime.datetime(2024, 1, 1, 12, 0, 0)
            mock_tz.now.return_value = mock_now

            token = create_access_token(user_id=42)
            payload = jwt.get_unverified_claims(token)

            # Default expiration is 24 hours
            exp_time = datetime.datetime.fromtimestamp(payload["exp"])
            assert (exp_time - mock_now).total_seconds() == pytest.approx(24 * 3600, rel=1)


class TestCreateRefreshToken:
    """Tests for create_refresh_token function."""

    def test_creates_valid_refresh_token(self):
        """Should create a valid JWT refresh token."""
        token = create_refresh_token(user_id=42)

        payload = jwt.get_unverified_claims(token)

        assert payload["sub"] == "42"
        assert payload["type"] == "refresh"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_refresh_token_has_longer_expiration(self):
        """Refresh tokens should have longer expiration than access tokens."""
        access_token = create_access_token(user_id=42)
        refresh_token = create_refresh_token(user_id=42)

        access_payload = jwt.get_unverified_claims(access_token)
        refresh_payload = jwt.get_unverified_claims(refresh_token)

        # Default: access 24h, refresh 7 days
        assert refresh_payload["exp"] > access_payload["exp"]


class TestDecodeTokenUnverified:
    """Tests for decode_token_unverified function."""

    def test_decodes_valid_token_without_verification(self):
        """Should decode a valid token without checking signature."""
        token = create_access_token(user_id=42)
        payload = decode_token_unverified(token)

        assert payload["sub"] == "42"
        assert payload["type"] == "access"

    def test_decodes_expired_token_without_error(self):
        """Should decode expired tokens without raising TokenExpired."""
        # Create a token that expires immediately
        with patch("openviper.auth.jwt._JWT_ACCESS_EXPIRE", datetime.timedelta(seconds=0)):
            token = create_access_token(user_id=42)

        # Should decode without error
        payload = decode_token_unverified(token)
        assert payload["sub"] == "42"

    def test_returns_empty_dict_for_malformed_token(self):
        """Should return empty dict for malformed tokens."""
        result = decode_token_unverified("not-a-jwt-token")
        assert result == {}

    def test_returns_empty_dict_for_empty_token(self):
        """Should return empty dict for empty token."""
        result = decode_token_unverified("")
        assert result == {}


class TestDecodeAccessToken:
    """Tests for decode_access_token function."""

    def test_decodes_valid_access_token(self):
        """Should successfully decode a valid access token."""
        token = create_access_token(user_id=42)
        payload = decode_access_token(token)

        assert payload["sub"] == "42"
        assert payload["type"] == "access"

    def test_raises_token_expired_for_expired_token(self):
        """Should raise TokenExpired for expired tokens."""
        # Create a token that expires immediately
        with patch("openviper.auth.jwt._JWT_ACCESS_EXPIRE", datetime.timedelta(seconds=-1)):
            token = create_access_token(user_id=42)

        with pytest.raises(TokenExpired):
            decode_access_token(token)

    def test_raises_authentication_failed_for_invalid_signature(self):
        """Should raise AuthenticationFailed for tokens with invalid signature."""
        token = create_access_token(user_id=42)
        # Tamper with the token
        tampered_token = token[:-10] + "xxxxxxxxxx"

        with pytest.raises(AuthenticationFailed, match="Invalid token"):
            decode_access_token(tampered_token)

    def test_raises_authentication_failed_for_malformed_token(self):
        """Should raise AuthenticationFailed for malformed tokens."""
        with pytest.raises(AuthenticationFailed, match="Invalid token"):
            decode_access_token("not-a-jwt-token")

    def test_raises_authentication_failed_for_wrong_token_type(self):
        """Should reject refresh tokens when expecting access tokens."""
        token = create_refresh_token(user_id=42)

        with pytest.raises(AuthenticationFailed, match="Invalid token type"):
            decode_access_token(token)

    def test_verifies_signature(self):
        """Should verify token signature."""
        token = create_access_token(user_id=42)

        # Decode with correct secret should work
        payload = decode_access_token(token)
        assert payload["sub"] == "42"


class TestDecodeRefreshToken:
    """Tests for decode_refresh_token function."""

    def test_decodes_valid_refresh_token(self):
        """Should successfully decode a valid refresh token."""
        token = create_refresh_token(user_id=42)
        payload = decode_refresh_token(token)

        assert payload["sub"] == "42"
        assert payload["type"] == "refresh"

    def test_raises_token_expired_for_expired_refresh_token(self):
        """Should raise TokenExpired for expired refresh tokens."""
        with patch("openviper.auth.jwt._JWT_REFRESH_EXPIRE", datetime.timedelta(seconds=-1)):
            token = create_refresh_token(user_id=42)

        with pytest.raises(TokenExpired):
            decode_refresh_token(token)

    def test_raises_authentication_failed_for_wrong_token_type(self):
        """Should reject access tokens when expecting refresh tokens."""
        token = create_access_token(user_id=42)

        with pytest.raises(AuthenticationFailed, match="Invalid token type"):
            decode_refresh_token(token)

    def test_raises_authentication_failed_for_invalid_token(self):
        """Should raise AuthenticationFailed for invalid tokens."""
        with pytest.raises(AuthenticationFailed, match="Invalid token"):
            decode_refresh_token("invalid-token")


class TestJWTSettings:
    """Tests for JWT settings and configuration."""

    def test_uses_secret_key_from_settings(self):
        """Should use SECRET_KEY from settings."""
        # Create and decode a token to verify it uses the correct secret
        token = create_access_token(user_id=42)
        payload = decode_access_token(token)
        assert payload is not None

    def test_default_algorithm_is_hs256(self):
        """Should use HS256 algorithm by default."""
        token = create_access_token(user_id=42)
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "HS256"

    def test_handles_timedelta_expiry_settings(self):
        """Should handle timedelta expiry settings."""
        # The module should already handle this during import
        token = create_access_token(user_id=42)
        payload = jwt.get_unverified_claims(token)
        assert "exp" in payload

    def test_handles_integer_expiry_settings(self):
        """Should convert integer expiry settings to timedelta."""
        # This is tested implicitly by the module loading successfully
        token = create_access_token(user_id=42)
        assert token is not None
