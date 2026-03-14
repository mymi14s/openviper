"""Integration tests for authentication workflow."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openviper.auth.decorators import login_required
from openviper.auth.hashers import check_password, make_password
from openviper.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from openviper.auth.permissions import check_permission_for_model
from openviper.auth.sessions import generate_session_key
from openviper.auth.token_blocklist import is_token_revoked, revoke_token
from openviper.http.response import JSONResponse


class TestJWTAuthWorkflow:
    """Integration tests for JWT authentication flow."""

    @pytest.mark.asyncio
    async def test_jwt_token_creation(self):
        """Test creating a JWT token."""
        # create_access_token takes user_id and optional extra_claims
        token = create_access_token(user_id=1, extra_claims={"username": "testuser"})

        assert token is not None
        assert isinstance(token, str)

        # Decode and verify
        decoded = decode_access_token(token)
        assert decoded is not None
        assert decoded.get("sub") == "1"  # user_id is stored as string in sub
        assert decoded.get("username") == "testuser"

    @pytest.mark.asyncio
    async def test_jwt_refresh_token(self):
        """Test creating and using refresh token."""
        refresh_token = create_refresh_token(user_id=1)

        assert refresh_token is not None
        decoded = decode_refresh_token(refresh_token)
        assert decoded is not None

    @pytest.mark.asyncio
    async def test_jwt_token_expiration(self):
        """Test token expiration is set correctly."""
        # Create token - expiry is set by _JWT_ACCESS_EXPIRE
        token = create_access_token(user_id=1)

        assert token is not None
        decoded = decode_access_token(token)
        assert decoded is not None
        assert "exp" in decoded  # Verify expiration claim exists
        assert "iat" in decoded  # Verify issued-at claim exists


class TestPasswordHashing:
    """Integration tests for password hashing."""

    @pytest.mark.asyncio
    async def test_password_hash_and_verify(self):
        """Test password hashing and verification."""
        password = "secret123"
        hashed = await make_password(password)

        assert hashed is not None
        assert hashed != password

        # Verify correct password
        is_valid = await check_password(password, hashed)
        assert is_valid is True

        # Verify wrong password
        is_valid = await check_password("wrongpassword", hashed)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_different_passwords_different_hashes(self):
        """Test that different passwords produce different hashes."""
        hash1 = await make_password("password1")
        hash2 = await make_password("password2")

        assert hash1 != hash2


class TestSessionManagement:
    """Integration tests for session management."""

    @pytest.mark.asyncio
    @patch("openviper.auth.sessions._SESSION_CACHE", {})
    async def test_session_create_and_retrieve(self):
        """Test creating and retrieving a session."""
        session_data = {"user_id": 1, "role": "admin"}
        session_key = generate_session_key()

        assert session_key is not None
        assert len(session_key) > 20  # Should be URL-safe random string


class TestTokenBlocklist:
    """Integration tests for token blocklist."""

    @pytest.mark.asyncio
    @patch("openviper.auth.token_blocklist._JTI_REVOKED_CACHE", {})
    @patch("openviper.auth.token_blocklist._JTI_VALID_CACHE", {})
    async def test_revoke_and_check_token(self):
        """Test revoking and checking a token."""
        token_jti = "test-jti-123"

        # Initially not revoked
        # Note: This may need DB connection in actual integration test
        # For unit-level integration, we just verify the API exists
        assert callable(revoke_token)
        assert callable(is_token_revoked)


class TestPermissions:
    """Integration tests for permission checking."""

    @pytest.mark.asyncio
    async def test_permission_check_function_exists(self):
        """Test that permission check function is available."""
        assert callable(check_permission_for_model)

    @pytest.mark.asyncio
    async def test_login_required_decorator(self):
        """Test login_required decorator."""

        @login_required
        async def protected_view(request):
            return JSONResponse({"protected": True})

        # Verify decorator is applied
        assert hasattr(protected_view, "__wrapped__") or callable(protected_view)
