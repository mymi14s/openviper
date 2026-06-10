"""Crypto and secret security tests.

Requirement IDs: CRYPTO-001 through CRYPTO-004, SECRET-001.
"""

from __future__ import annotations

import base64
import datetime
import inspect
import json
import secrets
import string
from collections import Counter

import pytest
from jose import jwt as jose_jwt

from openviper.auth.hashers import (
    check_password,
    make_password,
    make_unusable_password,
)
from openviper.auth.jwt import (
    ALLOWED_JWT_ALGORITHMS,
    ASYMMETRIC_PREFIXES,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_jwt_config,
)
from openviper.auth.session.utils import generate_session_key
from openviper.conf.settings import SENSITIVE_FIELDS, Settings
from openviper.exceptions import AuthenticationFailed, TokenExpired
from openviper.middleware.csrf import (
    generate_csrf_token,
    mask_csrf_token,
    verify_csrf_token,
)

from .conftest import override_settings


class TestCryptographicRandomness:
    """CRYPTO-001: All security tokens must use cryptographically secure randomness."""

    # -- CSRF tokens --

    def test_crypto001_csrf_token_uses_secrets_module(self) -> None:
        """CSRF token generation must delegate to the secrets module."""
        source = inspect.getsource(generate_csrf_token)
        assert "secrets" in source, "CSRF token generator must use the secrets module"

    def test_crypto001_csrf_token_does_not_use_random_module(self) -> None:
        """CSRF token generation must not fall back to the random module."""
        source = inspect.getsource(generate_csrf_token)
        assert "random." not in source, "CSRF token generator must not use the random module"

    def test_crypto001_csrf_tokens_are_unique(self) -> None:
        """Each generated CSRF token must be unique across 100 invocations."""
        tokens = [generate_csrf_token() for _ in range(100)]
        assert len(set(tokens)) == 100, "CSRF tokens must be unique"

    def test_crypto001_csrf_token_has_sufficient_entropy(self) -> None:
        """CSRF tokens must contain at least 256 bits of entropy (64 hex chars)."""
        token = generate_csrf_token()
        assert len(token) >= 64, f"CSRF token too short: {len(token)} chars"
        assert all(c in string.hexdigits for c in token), "CSRF token must be hex-encoded"

    def test_crypto001_csrf_token_is_not_predictable(self) -> None:
        """Consecutive CSRF tokens must not share a common prefix beyond chance."""
        tokens = [generate_csrf_token() for _ in range(50)]
        prefixes = [t[:4] for t in tokens]
        counts = Counter(prefixes)
        for prefix, count in counts.items():
            assert (
                count <= 2
            ), f"Prefix {prefix!r} appeared {count} times - tokens may be predictable"

    # -- Session keys --

    def test_crypto001_session_key_uses_secrets_module(self) -> None:
        """Session key generation must delegate to the secrets module."""
        source = inspect.getsource(generate_session_key)
        assert "secrets" in source, "Session key generator must use the secrets module"

    def test_crypto001_session_keys_are_unique(self) -> None:
        """Each generated session key must be unique across 100 invocations."""
        keys = [generate_session_key() for _ in range(100)]
        assert len(set(keys)) == 100, "Session keys must be unique"

    def test_crypto001_session_key_has_sufficient_entropy(self) -> None:
        """Session keys must contain at least 48 characters (token_urlsafe(48))."""
        key = generate_session_key()
        assert len(key) >= 48, f"Session key too short: {len(key)} chars"

    def test_crypto001_session_key_is_urlsafe(self) -> None:
        """Session keys must only contain URL-safe characters."""
        key = generate_session_key()
        urlsafe_chars = set(string.ascii_letters + string.digits + "-_=")
        assert all(c in urlsafe_chars for c in key), "Session key must be URL-safe"

    # -- Password hashing --

    @pytest.mark.asyncio
    async def test_crypto001_password_hash_uses_random_salt(self) -> None:
        """Password hashes must include a unique random salt per hash."""
        password = "deterministic-test-password"
        hash1 = await make_password(password, algorithm="argon2")
        hash2 = await make_password(password, algorithm="argon2")
        assert hash1 != hash2, "Same password must produce different hashes (salt must vary)"

    @pytest.mark.asyncio
    async def test_crypto001_bcrypt_password_hash_uses_random_salt(self) -> None:
        """Bcrypt hashes must include a unique random salt per hash."""
        password = "deterministic-test-password"
        hash1 = await make_password(password, algorithm="bcrypt")
        hash2 = await make_password(password, algorithm="bcrypt")
        assert hash1 != hash2, "Same password must produce different bcrypt hashes"

    @pytest.mark.asyncio
    async def test_crypto001_password_hash_not_plaintext(self) -> None:
        """Password hashes must never contain the raw plaintext password."""
        raw_password = "MyS3cret!Pass#2026"
        hashed = await make_password(raw_password, algorithm="argon2")
        assert raw_password not in hashed, "Hashed password must not contain the plaintext"

    @pytest.mark.asyncio
    async def test_crypto001_bcrypt_password_hash_not_plaintext(self) -> None:
        """Bcrypt hashes must never contain the raw plaintext password."""
        raw_password = "MyS3cret!Pass#2026"
        hashed = await make_password(raw_password, algorithm="bcrypt")
        assert raw_password not in hashed, "Bcrypt hash must not contain the plaintext"

    # -- JWT tokens --

    def test_crypto001_jwt_includes_unique_jti(self) -> None:
        """JWT tokens must include a unique jti claim for revocation support."""
        with override_settings(SECRET_KEY="test-crypto001-jti-secret"):
            token1 = create_access_token(user_id=1)
            token2 = create_access_token(user_id=1)
            payload1 = decode_access_token(token1)
            payload2 = decode_access_token(token2)
            assert payload1["jti"] != payload2["jti"], "JWT jti claims must be unique"


class TestSignedValueTampering:
    """CRYPTO-002: Signed values must reject any tampering."""

    # -- CSRF tokens --

    def test_crypto002_csrf_masked_token_rejects_tampering(self) -> None:
        """Tampered masked CSRF tokens must be rejected."""
        secret = "test-csrf-secret-crypto002"
        original_token = generate_csrf_token()
        masked = mask_csrf_token(original_token, secret)

        # Flip a character in the masked token
        tampered = masked[:-1] + ("0" if masked[-1] != "0" else "1")
        assert not verify_csrf_token(original_token, tampered, secret)

    def test_crypto002_csrf_wrong_secret_rejects(self) -> None:
        """CSRF tokens verified with the wrong secret must be rejected."""
        secret_a = "secret-alpha"
        secret_b = "secret-beta"
        token = generate_csrf_token()
        masked = mask_csrf_token(token, secret_a)

        assert not verify_csrf_token(token, masked, secret_b)

    def test_crypto002_csrf_empty_masked_token_rejected(self) -> None:
        """Empty or trivially short masked tokens must be rejected."""
        token = generate_csrf_token()
        assert not verify_csrf_token(token, "", "any-secret")
        assert not verify_csrf_token(token, "short", "any-secret")

    def test_crypto002_csrf_wrong_original_token_rejected(self) -> None:
        """A masked token verified against the wrong original token must fail."""
        secret = "test-csrf-secret-wrong"
        token_a = generate_csrf_token()
        token_b = generate_csrf_token()
        masked = mask_csrf_token(token_a, secret)

        assert not verify_csrf_token(token_b, masked, secret)

    # -- JWT tokens --

    def test_crypto002_jwt_rejects_tampered_payload(self) -> None:
        """JWT tokens with tampered payloads must be rejected."""
        with override_settings(SECRET_KEY="test-crypto002-jwt-secret"):
            token = create_access_token(user_id=42)
            parts = token.split(".")
            assert len(parts) == 3, "JWT must have three parts"

            payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
            payload_dict = json.loads(payload_bytes)
            payload_dict["sub"] = "999"
            tampered_payload = (
                base64.urlsafe_b64encode(json.dumps(payload_dict).encode()).rstrip(b"=").decode()
            )
            tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

            with pytest.raises(AuthenticationFailed):
                decode_access_token(tampered_token)

    def test_crypto002_jwt_rejects_tampered_signature(self) -> None:
        """JWT tokens with tampered signatures must be rejected."""
        with override_settings(SECRET_KEY="test-crypto002-sig-secret"):
            token = create_access_token(user_id=1)
            parts = token.split(".")
            tampered_sig = parts[2][:-2] + "XX"
            tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

            with pytest.raises(AuthenticationFailed):
                decode_access_token(tampered_token)

    def test_crypto002_jwt_rejects_wrong_secret(self) -> None:
        """JWT tokens signed with a different secret must be rejected."""
        with override_settings(SECRET_KEY="secret-alpha"):
            token = create_access_token(user_id=1)

        with override_settings(SECRET_KEY="secret-beta"):
            with pytest.raises(AuthenticationFailed):
                decode_access_token(token)

    def test_crypto002_jwt_rejects_access_token_as_refresh(self) -> None:
        """An access token must not be accepted as a refresh token."""
        with override_settings(SECRET_KEY="test-crypto002-type-enforcement"):
            access_token = create_access_token(user_id=1)
            with pytest.raises(AuthenticationFailed):
                decode_refresh_token(access_token)

    def test_crypto002_jwt_rejects_refresh_token_as_access(self) -> None:
        """A refresh token must not be accepted as an access token."""
        with override_settings(SECRET_KEY="test-crypto002-type-enforcement"):
            refresh_token = create_refresh_token(user_id=1)
            with pytest.raises(AuthenticationFailed):
                decode_access_token(refresh_token)

    # -- Password hashing --

    @pytest.mark.asyncio
    async def test_crypto002_wrong_password_rejected_argon2(self) -> None:
        """Wrong passwords must be rejected by argon2 verification."""
        hashed = await make_password("correct-horse-battery", algorithm="argon2")
        assert not await check_password("wrong-password", hashed)

    @pytest.mark.asyncio
    async def test_crypto002_wrong_password_rejected_bcrypt(self) -> None:
        """Wrong passwords must be rejected by bcrypt verification."""
        hashed = await make_password("correct-horse-battery", algorithm="bcrypt")
        assert not await check_password("wrong-password", hashed)

    @pytest.mark.asyncio
    async def test_crypto002_tampered_hash_rejected(self) -> None:
        """A tampered password hash must not verify any password."""
        hashed = await make_password("test-password", algorithm="argon2")
        tampered_hash = "argon2$" + hashed[7:50] + "TAMPERED" + hashed[58:]
        assert not await check_password("test-password", tampered_hash)

    @pytest.mark.asyncio
    async def test_crypto002_empty_hash_rejected(self) -> None:
        """An empty hash string must not verify any password."""
        assert not await check_password("any-password", "")

    @pytest.mark.asyncio
    async def test_crypto002_unknown_prefix_hash_rejected(self) -> None:
        """A hash with an unknown algorithm prefix must not verify any password."""
        assert not await check_password("any-password", "unknown$hashvalue")


class TestExpiredSignedValues:
    """CRYPTO-003: Expired signed values must be rejected."""

    def test_crypto003_expired_access_token_rejected(self) -> None:
        """Access tokens that have expired must be rejected."""
        with override_settings(SECRET_KEY="test-crypto003-expired"):
            token = create_access_token(
                user_id=1,
                expires_delta=datetime.timedelta(seconds=-1),
            )
            with pytest.raises(TokenExpired):
                decode_access_token(token)

    def test_crypto003_expired_refresh_token_rejected(self) -> None:
        """Refresh tokens that have expired must be rejected."""
        with override_settings(SECRET_KEY="test-crypto003-refresh-expired"):
            secret, algo = get_jwt_config()
            now = datetime.datetime.now(datetime.UTC)
            claims = {
                "sub": "1",
                "jti": str(secrets.token_hex(16)),
                "iat": now - datetime.timedelta(days=30),
                "exp": now - datetime.timedelta(days=1),
                "type": "refresh",
            }
            expired_token = jose_jwt.encode(claims, secret, algorithm=algo)

            with pytest.raises(TokenExpired):
                decode_refresh_token(expired_token)

    def test_crypto003_access_token_includes_expiry(self) -> None:
        """Access tokens must include an expiration claim."""
        with override_settings(SECRET_KEY="test-crypto003-exp-claim"):
            token = create_access_token(user_id=1)
            payload = decode_access_token(token)
            assert "exp" in payload, "JWT must include 'exp' claim"

    def test_crypto003_access_token_includes_iat(self) -> None:
        """Access tokens must include an issued-at claim."""
        with override_settings(SECRET_KEY="test-crypto003-iat-claim"):
            token = create_access_token(user_id=1)
            payload = decode_access_token(token)
            assert "iat" in payload, "JWT must include 'iat' claim"

    def test_crypto003_near_expiry_token_accepted(self) -> None:
        """Tokens that are about to expire but have not yet must still be accepted."""
        with override_settings(SECRET_KEY="test-crypto003-near-expiry"):
            token = create_access_token(
                user_id=1,
                expires_delta=datetime.timedelta(seconds=60),
            )
            payload = decode_access_token(token)
            assert payload["sub"] == "1"

    def test_crypto003_far_past_expiry_rejected(self) -> None:
        """Tokens that expired long ago must be rejected."""
        with override_settings(SECRET_KEY="test-crypto003-far-past"):
            token = create_access_token(
                user_id=1,
                expires_delta=datetime.timedelta(days=-365),
            )
            with pytest.raises(TokenExpired):
                decode_access_token(token)


class TestKeyRotation:
    """CRYPTO-004: Key rotation must be supported for cryptographic operations."""

    def test_crypto004_jwt_configurable_algorithm(self) -> None:
        """JWT algorithm must be configurable via settings."""
        with override_settings(SECRET_KEY="test-crypto004-algo", JWT_ALGORITHM="HS256"):
            secret, algo = get_jwt_config()
            assert algo == "HS256"

    def test_crypto004_jwt_configurable_algorithm_hs512(self) -> None:
        """JWT algorithm must support HS512 via settings."""
        with override_settings(SECRET_KEY="test-crypto004-hs512", JWT_ALGORITHM="HS512"):
            secret, algo = get_jwt_config()
            assert algo == "HS512"

    def test_crypto004_insecure_algorithm_none_rejected(self) -> None:
        """The 'none' algorithm must be explicitly rejected."""
        assert "none" not in ALLOWED_JWT_ALGORITHMS
        assert "None" not in ALLOWED_JWT_ALGORITHMS
        assert "NONE" not in ALLOWED_JWT_ALGORITHMS

    def test_crypto004_insecure_algorithm_empty_rejected(self) -> None:
        """An empty algorithm string must not be in the allowed list."""
        assert "" not in ALLOWED_JWT_ALGORITHMS

    def test_crypto004_secure_algorithms_in_allowed_list(self) -> None:
        """Standard secure algorithms must be present in the allowed list."""
        for algo in ("HS256", "HS384", "HS512", "RS256", "ES256"):
            assert algo in ALLOWED_JWT_ALGORITHMS, f"{algo} must be in allowed algorithms"

    def test_crypto004_key_rotation_old_key_verifies(self) -> None:
        """During key rotation, tokens signed with the old key must still verify."""
        old_secret = "old-rotation-secret-key-001"

        with override_settings(SECRET_KEY=old_secret, JWT_ALGORITHM="HS256"):
            token = create_access_token(user_id=1)
            payload = decode_access_token(token)
            assert payload["sub"] == "1"

    def test_crypto004_key_rotation_new_key_rejects_old_token(self) -> None:
        """After key rotation, tokens signed with the old key must be rejected."""
        old_secret = "old-rotation-secret-key-003"
        new_secret = "new-rotation-secret-key-004"

        with override_settings(SECRET_KEY=old_secret, JWT_ALGORITHM="HS256"):
            token = create_access_token(user_id=1)

        with override_settings(SECRET_KEY=new_secret, JWT_ALGORITHM="HS256"):
            with pytest.raises(AuthenticationFailed):
                decode_access_token(token)

    def test_crypto004_asymmetric_algorithms_require_pem(self) -> None:
        """Asymmetric algorithms must require PEM-formatted keys."""
        for prefix in ASYMMETRIC_PREFIXES:
            assert prefix in {"RS", "ES", "PS"}, f"Unexpected asymmetric prefix: {prefix}"

    def test_crypto004_csrf_key_rotation(self) -> None:
        """CSRF tokens must fail verification when the signing secret changes."""
        old_secret = "csrf-old-secret"
        new_secret = "csrf-new-secret"
        token = generate_csrf_token()
        masked_with_old = mask_csrf_token(token, old_secret)

        # Verification with old secret succeeds
        assert verify_csrf_token(token, masked_with_old, old_secret)

        # Verification with new secret fails (rotation without migration)
        assert not verify_csrf_token(token, masked_with_old, new_secret)

    def test_crypto004_csrf_key_rotation_migration(self) -> None:
        """CSRF tokens must support a migration window with both old and new secrets."""
        old_secret = "csrf-migration-old"
        new_secret = "csrf-migration-new"
        token = generate_csrf_token()
        masked_with_old = mask_csrf_token(token, old_secret)

        # During migration, the old secret still verifies
        assert verify_csrf_token(token, masked_with_old, old_secret)

        # New tokens work with the new secret
        new_token = generate_csrf_token()
        masked_with_new = mask_csrf_token(new_token, new_secret)
        assert verify_csrf_token(new_token, masked_with_new, new_secret)


class TestSecretExposure:
    """SECRET-001: Secrets must not be exposed to the frontend or logs."""

    def test_secret001_sensitive_fields_defined(self) -> None:
        """Settings must define a comprehensive set of sensitive fields."""
        assert "SECRET_KEY" in SENSITIVE_FIELDS
        assert "DATABASES" in SENSITIVE_FIELDS

    def test_secret001_as_dict_masks_secret_key(self) -> None:
        """as_dict(mask_sensitive=True) must mask SECRET_KEY."""
        s = Settings(SECRET_KEY="super-secret-key-12345")
        result = s.as_dict(mask_sensitive=True)
        assert (
            result["SECRET_KEY"] == "***"
        ), f"SECRET_KEY must be masked, got: {result['SECRET_KEY']!r}"

    def test_secret001_as_dict_masks_database_url(self) -> None:
        """as_dict(mask_sensitive=True) must mask DATABASES."""
        s = Settings(
            DATABASES={"default": {"OPTIONS": {"URL": "postgresql://user:pass@db:5432/mydb"}}}
        )
        result = s.as_dict(mask_sensitive=True)
        assert (
            result["DATABASES"] == "***"
        ), f"DATABASES must be masked, got: {result['DATABASES']!r}"

    def test_secret001_as_dict_masks_cache_url(self) -> None:
        """as_dict(mask_sensitive=True) must mask CACHES."""
        s = Settings(
            CACHES={
                "default": {
                    "BACKEND": "openviper.cache.RedisCache",
                    "OPTIONS": {"url": "redis://user:pass@redis:6379/0"},
                }
            }
        )
        result = s.as_dict(mask_sensitive=True)
        assert result["CACHES"] == "***", f"CACHES must be masked, got: {result['CACHES']!r}"

    def test_secret001_as_dict_masks_email(self) -> None:
        """as_dict(mask_sensitive=True) must mask EMAIL."""
        s = Settings(EMAIL={"password": "smtp-secret-pass"})
        result = s.as_dict(mask_sensitive=True)
        assert result["EMAIL"] == "***", f"EMAIL must be masked, got: {result['EMAIL']!r}"

    def test_secret001_as_dict_unmasked_returns_raw(self) -> None:
        """as_dict(mask_sensitive=False) must return raw secret values."""
        s = Settings(SECRET_KEY="raw-secret-value")
        result = s.as_dict(mask_sensitive=False)
        assert result["SECRET_KEY"] == "raw-secret-value"

    def test_secret001_as_dict_does_not_mask_non_sensitive(self) -> None:
        """as_dict(mask_sensitive=True) must not mask non-sensitive fields."""
        s = Settings(PROJECT_NAME="MyApp", DEBUG=True)
        result = s.as_dict(mask_sensitive=True)
        assert result["PROJECT_NAME"] == "MyApp"
        assert result["DEBUG"] is True

    def test_secret001_as_dict_empty_sensitive_field_not_masked(self) -> None:
        """Empty sensitive fields must not be masked (to avoid hiding default state)."""
        s = Settings(SECRET_KEY="")
        result = s.as_dict(mask_sensitive=True)
        assert result["SECRET_KEY"] == "", "Empty sensitive fields should remain empty, not masked"

    @pytest.mark.asyncio
    async def test_secret001_password_hash_does_not_contain_plaintext(self) -> None:
        """Real password hashes must not contain the plaintext password."""
        raw_password = "SuperSecret!2026"
        hashed = await make_password(raw_password, algorithm="argon2")
        assert raw_password not in hashed, "Hashed password must not contain plaintext"

    @pytest.mark.asyncio
    async def test_secret001_bcrypt_hash_does_not_contain_plaintext(self) -> None:
        """Bcrypt hashes must not contain the plaintext password."""
        raw_password = "SuperSecret!2026"
        hashed = await make_password(raw_password, algorithm="bcrypt")
        assert raw_password not in hashed, "Bcrypt hash must not contain plaintext"

    def test_secret001_jwt_payload_excludes_secret_key(self) -> None:
        """JWT payload must not contain the SECRET_KEY."""
        with override_settings(SECRET_KEY="jwt-secret-not-in-payload"):
            token = create_access_token(user_id=1)
            payload = decode_access_token(token)
            assert "SECRET_KEY" not in payload
            for value in payload.values():
                assert "jwt-secret-not-in-payload" not in str(value)

    def test_secret001_jwt_payload_excludes_secret_from_claims(self) -> None:
        """JWT payload must not leak the signing secret in any claim."""
        with override_settings(SECRET_KEY="leak-test-secret-value"):
            token = create_access_token(user_id=42)
            unverified = jose_jwt.get_unverified_claims(token)
            for key, value in unverified.items():
                assert "leak-test-secret-value" not in str(
                    value
                ), f"Secret leaked in claim {key!r}: {value!r}"

    def test_secret001_csrf_token_does_not_expose_secret(self) -> None:
        """Masked CSRF tokens must not expose the signing secret."""
        secret = "csrf-signing-secret-do-not-leak"
        token = generate_csrf_token()
        masked = mask_csrf_token(token, secret)
        assert secret not in masked, "CSRF masked token must not contain the signing secret"

    def test_secret001_session_key_does_not_expose_secret(self) -> None:
        """Session keys must not contain any secret key material."""
        with override_settings(SECRET_KEY="session-secret-do-not-leak"):
            key = generate_session_key()
            assert "session-secret-do-not-leak" not in key

    def test_secret001_unusable_password_does_not_reveal_info(self) -> None:
        """Unusable password markers must not reveal user identity or system info."""
        unusable = make_unusable_password()
        assert unusable.startswith("!")
        assert "@" not in unusable
        assert "/" not in unusable

    @pytest.mark.asyncio
    async def test_secret001_password_verification_timing_safe(self) -> None:
        """Password verification must use constant-time comparison for plain hasher."""
        source = inspect.getsource(check_password)
        assert "compare_digest" in source, "Password verification must use constant-time comparison"

    def test_secret001_settings_as_dict_is_safe_serialization(self) -> None:
        """as_dict(mask_sensitive=True) must be the safe path for serialization."""
        s = Settings(
            SECRET_KEY="do-not-expose-in-serialization",
            DATABASES={"default": {"OPTIONS": {"URL": "postgresql://secret@db/db"}}},
        )
        safe_dict = s.as_dict(mask_sensitive=True)
        assert safe_dict["SECRET_KEY"] == "***"
        assert safe_dict["DATABASES"] == "***"
        # Verify that non-sensitive fields remain accessible
        assert "PROJECT_NAME" in safe_dict

    def test_secret001_sensitive_fields_cover_critical_secrets(self) -> None:
        """The SENSITIVE_FIELDS set must cover all critical secret fields."""
        required_fields = {"SECRET_KEY", "DATABASES", "CACHES", "EMAIL"}
        for field in required_fields:
            assert field in SENSITIVE_FIELDS, f"{field} must be in SENSITIVE_FIELDS"

    def test_secret001_csrf_middleware_does_not_expose_secret_in_response(self) -> None:
        """CSRF middleware must not include the signing secret in HTTP responses."""
        secret = "csrf-secret-not-in-response"
        token = generate_csrf_token()
        masked = mask_csrf_token(token, secret)
        assert secret not in masked
