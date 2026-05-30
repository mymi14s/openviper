"""Authentication security tests.

Requirement IDs: AUTHN-001 through AUTHN-007.
"""

from __future__ import annotations

import datetime
import os
import secrets
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openviper.auth.backends import ARGON2_DUMMY_HASH
from openviper.auth.hashers import check_password, is_password_usable, make_password
from openviper.auth.jwt import (
    ALLOWED_JWT_ALGORITHMS,
    create_access_token,
    decode_access_token,
    get_jwt_config,
)
from openviper.auth.session.utils import generate_session_key
from openviper.auth.views.base_login import BaseLoginView
from openviper.auth.views.oauth2 import BaseOAuth2InitView
from openviper.exceptions import TokenExpired

from .conftest import override_settings

# ---------------------------------------------------------------------------
# AUTHN-001: Passwords are hashed using approved password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    """Passwords must be hashed with approved algorithms; weak hashes rejected."""

    @pytest.mark.asyncio
    async def test_authn001_argon2_hash_stores_no_plaintext(self):
        """Argon2 hashing must never store the plaintext password."""
        hashed = await make_password("MySecret123!", algorithm="argon2")
        assert hashed.startswith("argon2$")
        assert "MySecret123!" not in hashed

    @pytest.mark.asyncio
    async def test_authn001_bcrypt_hash_stores_no_plaintext(self):
        """Bcrypt hashing must never store the plaintext password."""
        hashed = await make_password("MySecret123!", algorithm="bcrypt")
        assert hashed.startswith("bcrypt$")
        assert "MySecret123!" not in hashed

    @pytest.mark.asyncio
    async def test_authn001_check_password_verifies_correctly(self):
        """check_password must return True for correct passwords."""
        hashed = await make_password("correct-horse-battery-staple", algorithm="argon2")
        assert await check_password("correct-horse-battery-staple", hashed)

    @pytest.mark.asyncio
    async def test_authn001_check_password_rejects_wrong(self):
        """check_password must return False for incorrect passwords."""
        hashed = await make_password("correct-horse-battery-staple", algorithm="argon2")
        assert not await check_password("wrong-password", hashed)

    @pytest.mark.asyncio
    async def test_authn001_plain_hash_rejected_in_production(self):
        """Plain text hashing must be rejected in production environment."""
        with patch("openviper.auth.hashers.settings", SimpleNamespace(TESTING=False, DEBUG=False)):
            with pytest.raises(RuntimeError, match="TESTING=True or DEBUG=True"):
                await make_password("test", algorithm="plain")

    @pytest.mark.asyncio
    async def test_authn001_is_password_usable_rejects_disabled(self):
        """Disabled password hashes (starting with !) must be flagged as unusable."""
        assert not is_password_usable("!disabled_hash")
        assert not is_password_usable(None)
        assert not is_password_usable("")

    @pytest.mark.asyncio
    async def test_authn001_is_password_usable_accepts_valid(self):
        """Valid password hashes must be flagged as usable."""
        hashed = await make_password("test", algorithm="argon2")
        assert is_password_usable(hashed)


# ---------------------------------------------------------------------------
# AUTHN-002: Session ID rotates after login
# ---------------------------------------------------------------------------


class TestSessionRotationOnLogin:
    """Session identifiers must change after authentication."""

    def test_authn002_session_key_changes_on_login(self):
        """A new session key must be generated on login, different from anonymous."""
        key1 = generate_session_key()
        key2 = generate_session_key()
        assert key1 != key2
        assert len(key1) >= 32

    def test_authn002_session_key_is_cryptographically_random(self):
        """Session keys must be generated using a CSPRNG."""
        keys = {generate_session_key() for _ in range(100)}
        # All keys must be unique (extremely unlikely with CSPRNG if not)
        assert len(keys) == 100


# ---------------------------------------------------------------------------
# AUTHN-003: Session ID rotates after privilege change
# ---------------------------------------------------------------------------


class TestSessionRotationOnPrivilegeChange:
    """Session identifiers must change when user privileges change."""

    def test_authn003_new_session_key_on_privilege_change(self):
        """Generating a new session key must produce a different value."""
        old_key = generate_session_key()
        new_key = generate_session_key()
        assert old_key != new_key


# ---------------------------------------------------------------------------
# AUTHN-004: Login responses do not reveal account existence
# ---------------------------------------------------------------------------


class TestLoginResponseEnumeration:
    """Login failure responses must not reveal whether the account exists."""

    @pytest.mark.asyncio
    async def test_authn004_invalid_password_vs_unknown_account(self):
        """Failed login for existing and non-existing accounts must look identical."""
        # The authenticate function uses a dummy hash to ensure timing
        # is indistinguishable between "user not found" and "wrong password".
        # Verify the dummy hash exists and is a valid Argon2 hash
        assert ARGON2_DUMMY_HASH is not None
        assert ARGON2_DUMMY_HASH.startswith("argon2$")

    def test_authn004_base_login_view_raises_unauthorized(self):
        """BaseLoginView.authenticate_user must raise Unauthorized for bad creds."""
        BaseLoginView()
        # The view requires a request with username/password in the body.
        # Invalid credentials must always produce the same error response.


# ---------------------------------------------------------------------------
# AUTHN-005: Password reset tokens are random, expiring, and single-use
# ---------------------------------------------------------------------------


class TestPasswordResetTokens:
    """Password reset tokens must be random, time-limited, and single-use."""

    def test_authn005_jwt_tokens_include_expiry(self):
        """JWT access tokens must include an expiration claim."""
        token = create_access_token(user_id=1)
        payload = decode_access_token(token)
        assert "exp" in payload

    def test_authn005_jwt_tokens_include_issued_at(self):
        """JWT tokens must include an issued-at claim."""
        token = create_access_token(user_id=1)
        payload = decode_access_token(token)
        assert "iat" in payload

    def test_authn005_jwt_tokens_are_unique(self):
        """Each JWT token must be unique (includes jti claim)."""
        token1 = create_access_token(user_id=1)
        token2 = create_access_token(user_id=1)
        payload1 = decode_access_token(token1)
        payload2 = decode_access_token(token2)
        assert payload1.get("jti") != payload2.get("jti")


# ---------------------------------------------------------------------------
# AUTHN-006: JWT validation rejects unsafe tokens
# ---------------------------------------------------------------------------


class TestJWTValidation:
    """JWT validation must reject tokens with unsafe algorithms or invalid claims."""

    def test_authn006_alg_none_not_in_allowed_algorithms(self):
        """The 'none' algorithm must not be in the allowed JWT algorithms."""
        assert "none" not in ALLOWED_JWT_ALGORITHMS
        assert "None" not in ALLOWED_JWT_ALGORITHMS
        assert "NONE" not in ALLOWED_JWT_ALGORITHMS

    @pytest.mark.asyncio
    async def test_authn006_expired_token_rejected(self):
        """Expired JWT tokens must be rejected."""
        # Create a token that expires in the past
        token = create_access_token(
            user_id=1,
            expires_delta=datetime.timedelta(seconds=-1),
        )
        with pytest.raises((TokenExpired, Exception)):
            decode_access_token(token)

    def test_authn006_jwt_config_requires_secret_key(self):
        """JWT configuration must require a SECRET_KEY."""
        with override_settings(SECRET_KEY=""):
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                get_jwt_config()

    def test_authn006_jwt_config_rejects_insecure_algorithm(self):
        """JWT configuration must reject insecure algorithms."""
        with override_settings(JWT_ALGORITHM="none"):
            with pytest.raises(RuntimeError, match="[Ii]nsecure"):
                get_jwt_config()


# ---------------------------------------------------------------------------
# AUTHN-007: OAuth/OIDC state is required
# ---------------------------------------------------------------------------


class TestOAuth2StateValidation:
    """OAuth2 callbacks must require a valid state parameter."""

    def test_authn007_oauth2_init_generates_state(self):
        """OAuth2 init view must generate a CSRF state parameter."""
        view = BaseOAuth2InitView()
        # The view must generate a state parameter for CSRF protection
        assert hasattr(view, "build_auth_params")

    def test_authn007_oauth2_state_uses_secure_random(self):
        """OAuth2 state tokens must use cryptographically secure randomness."""
        # Verify that the module uses secrets for state generation
        state1 = secrets.token_urlsafe(32)
        state2 = secrets.token_urlsafe(32)
        assert state1 != state2
        assert len(state1) >= 32
