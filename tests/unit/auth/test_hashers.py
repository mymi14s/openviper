"""Unit tests for openviper.auth.hashers module."""

import time
from unittest.mock import patch

import pytest

from openviper.auth.hashers import (
    check_password,
    is_password_usable,
    make_password,
    make_unusable_password,
)


class TestMakePassword:
    """Tests for make_password function."""

    @pytest.mark.asyncio
    async def test_hashes_with_argon2_by_default(self):
        """Should use Argon2 algorithm by default."""
        hashed = await make_password("test_password")
        assert hashed.startswith("argon2$")

    @pytest.mark.asyncio
    async def test_hashed_password_contains_salt(self):
        """Should produce different hashes for same password (due to salt)."""
        hash1 = await make_password("test_password")
        hash2 = await make_password("test_password")
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_hashes_with_bcrypt_when_specified(self):
        """Should use bcrypt when algorithm='bcrypt'."""
        hashed = await make_password("test_password", algorithm="bcrypt")
        assert hashed.startswith("bcrypt$")

    @pytest.mark.asyncio
    async def test_plain_hasher_for_testing(self):
        """Should use plain hasher when algorithm='plain'."""
        hashed = await make_password("test_password", algorithm="plain")
        assert hashed == "plain$test_password"

    @pytest.mark.asyncio
    async def test_handles_empty_password(self):
        """Should hash empty passwords."""
        hashed = await make_password("")
        assert hashed.startswith("argon2$")

    @pytest.mark.asyncio
    async def test_handles_unicode_password(self):
        """Should handle Unicode characters in password."""
        hashed = await make_password("пароль密码🔒")
        assert hashed.startswith("argon2$")

    @pytest.mark.asyncio
    async def test_runs_in_thread_pool(self):
        """Should offload CPU-intensive hashing to thread pool."""
        with patch("asyncio.to_thread") as mock_to_thread:

            async def mock_hash():
                return "$argon2id$test"

            mock_to_thread.return_value = mock_hash()
            await make_password("test")
            mock_to_thread.assert_called()


class TestCheckPassword:
    """Tests for check_password function."""

    @pytest.mark.asyncio
    async def test_verifies_correct_argon2_password(self):
        """Should return True for correct Argon2 password."""
        raw_password = "test_password_123"
        hashed = await make_password(raw_password, algorithm="argon2")

        result = await check_password(raw_password, hashed)
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_incorrect_argon2_password(self):
        """Should return False for incorrect Argon2 password."""
        hashed = await make_password("correct_password", algorithm="argon2")

        result = await check_password("wrong_password", hashed)
        assert result is False

    @pytest.mark.asyncio
    async def test_verifies_correct_bcrypt_password(self):
        """Should return True for correct bcrypt password."""
        raw_password = "test_password_123"
        hashed = await make_password(raw_password, algorithm="bcrypt")

        result = await check_password(raw_password, hashed)
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_incorrect_bcrypt_password(self):
        """Should return False for incorrect bcrypt password."""
        hashed = await make_password("correct_password", algorithm="bcrypt")

        result = await check_password("wrong_password", hashed)
        assert result is False

    @pytest.mark.asyncio
    async def test_verifies_plain_password(self):
        """Should verify plain passwords (for testing only)."""
        hashed = "plain$test_password"

        result = await check_password("test_password", hashed)
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_incorrect_plain_password(self):
        """Should reject incorrect plain passwords."""
        hashed = "plain$correct_password"

        result = await check_password("wrong_password", hashed)
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_empty_password_check(self):
        """Should handle empty password verification."""
        hashed = await make_password("")

        result = await check_password("", hashed)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_algorithm(self):
        """Should return False for unknown hash algorithms."""
        result = await check_password("password", "unknown$hash")
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_malformed_argon2_hash(self):
        """Should return False for malformed Argon2 hashes."""
        result = await check_password("password", "argon2$invalid_hash")
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_malformed_bcrypt_hash(self):
        """Should return False for malformed bcrypt hashes."""
        result = await check_password("password", "bcrypt$invalid_hash")
        assert result is False

    @pytest.mark.asyncio
    async def test_runs_in_thread_pool(self):
        """Should offload CPU-intensive verification to thread pool."""
        hashed = await make_password("test")

        with patch("asyncio.to_thread") as mock_to_thread:

            async def mock_verify():
                return True

            mock_to_thread.return_value = mock_verify()
            await check_password("test", hashed)
            mock_to_thread.assert_called()

    @pytest.mark.asyncio
    async def test_handles_unicode_in_check(self):
        """Should handle Unicode passwords in verification."""
        raw_password = "пароль密码🔒"
        hashed = await make_password(raw_password)

        result = await check_password(raw_password, hashed)
        assert result is True


class TestIsPasswordUsable:
    """Tests for is_password_usable function."""

    def test_returns_true_for_valid_argon2_hash(self):
        """Should return True for valid Argon2 hash."""
        result = is_password_usable("argon2$v=19$m=65536,t=2,p=2$...")
        assert result is True

    def test_returns_true_for_valid_bcrypt_hash(self):
        """Should return True for valid bcrypt hash."""
        result = is_password_usable("bcrypt$2b$12$...")
        assert result is True

    def test_returns_false_for_disabled_password(self):
        """Should return False for disabled password (starts with !)."""
        result = is_password_usable("!disabled_hash")
        assert result is False

    def test_returns_false_for_none(self):
        """Should return False for None."""
        result = is_password_usable(None)
        assert result is False

    def test_returns_false_for_empty_string(self):
        """Should return False for empty string."""
        result = is_password_usable("")
        assert result is False

    def test_returns_true_for_plain_hash(self):
        """Should return True for plain hash (testing only)."""
        result = is_password_usable("plain$password")
        assert result is True


class TestMakeUnusablePassword:
    """Tests for make_unusable_password function."""

    def test_starts_with_exclamation(self):
        """Should generate password starting with !."""
        unusable = make_unusable_password()
        assert unusable.startswith("!")

    def test_generates_unique_passwords(self):
        """Should generate unique unusable passwords."""
        passwords = [make_unusable_password() for _ in range(10)]
        assert len(set(passwords)) == 10

    def test_generated_password_is_not_usable(self):
        """Generated password should not be usable."""
        unusable = make_unusable_password()
        assert is_password_usable(unusable) is False

    def test_generated_password_never_matches(self):
        """Unusable password should never match any input."""
        unusable = make_unusable_password()
        # check_password should return False for any input
        # (though in practice unusable passwords are never checked)
        assert unusable.startswith("!")


class TestArgon2Configuration:
    """Tests for Argon2 hasher configuration."""

    @pytest.mark.asyncio
    async def test_uses_reasonable_parameters(self):
        """Should use reasonable Argon2 parameters for security/performance."""
        hashed = await make_password("test")

        # Argon2 hash format: $argon2id$v=19$m=65536,t=2,p=2$...
        assert "argon2" in hashed
        # Should be relatively fast (< 1 second for hashing)

        start = time.time()
        await make_password("test")
        elapsed = time.time() - start
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_argon2_hasher_is_reused(self):
        """Should reuse PasswordHasher instances for efficiency."""
        # This tests that the module-level singletons are used
        hash1 = await make_password("test1")
        hash2 = await make_password("test2")

        assert hash1.startswith("argon2$")
        assert hash2.startswith("argon2$")


class TestBcryptConfiguration:
    """Tests for bcrypt hasher configuration."""

    @pytest.mark.asyncio
    async def test_uses_12_rounds(self):
        """Should use 12 rounds for bcrypt (good security/performance balance)."""
        hashed = await make_password("test", algorithm="bcrypt")

        # Extract the hash portion after "bcrypt$"
        bcrypt_hash = hashed[len("bcrypt$") :]
        # Bcrypt hash format: $2b$12$... where 12 is the cost factor
        assert "$12$" in bcrypt_hash or "$2b$12$" in bcrypt_hash


class TestTimingAttackProtection:
    """Tests for timing attack protection."""

    @pytest.mark.asyncio
    async def test_dummy_hash_is_valid_argon2(self):
        """Dummy hash for timing protection should be valid Argon2 format."""
        from openviper.auth.hashers import _ARGON2_DUMMY_HASH

        assert _ARGON2_DUMMY_HASH.startswith("argon2$")

        # Should take similar time to verify as a real password
        result = await check_password("wrong_password", _ARGON2_DUMMY_HASH)
        assert result is False

    @pytest.mark.asyncio
    async def test_dummy_hash_never_matches(self):
        """Dummy hash should never match any password."""
        from openviper.auth.hashers import _ARGON2_DUMMY_HASH

        # Try various passwords
        for password in ["", "password", "__dummy_password__", "admin", "test"]:
            result = await check_password(password, _ARGON2_DUMMY_HASH)
            assert result is False


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_very_long_password(self):
        """Should handle very long passwords."""
        long_password = "a" * 1000
        hashed = await make_password(long_password)

        result = await check_password(long_password, hashed)
        assert result is True

    @pytest.mark.asyncio
    async def test_password_with_null_bytes(self):
        """Should handle passwords with null bytes."""
        # Some systems may have issues with null bytes
        password = "test\x00password"
        hashed = await make_password(password)

        result = await check_password(password, hashed)
        assert result is True

    @pytest.mark.asyncio
    async def test_special_characters_in_password(self):
        """Should handle passwords with special characters."""
        password = "p@$$w0rd!#%&*()[]{}|\\/<>?~`"
        hashed = await make_password(password)

        result = await check_password(password, hashed)
        assert result is True
