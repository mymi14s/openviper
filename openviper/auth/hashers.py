"""Password hashing using Argon2id (primary) or bcrypt (fallback)."""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Singleton PasswordHasher instances to avoid recreation overhead
_ARGON2_HASHER_MAKE = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)
_ARGON2_HASHER_CHECK = PasswordHasher()

# Precomputed dummy hash for timing-safe "user not found" branches.
# Running a real Argon2 verify against a valid (but always-failing) hash
# takes the same wall time as a real password check, preventing user
# enumeration via response-time differences.
# Use a cryptographically random password that will never match user input.
_DUMMY_PASSWORD_SECRET = secrets.token_urlsafe(32)
_ARGON2_DUMMY_HASH: str = "argon2$" + _ARGON2_HASHER_MAKE.hash(_DUMMY_PASSWORD_SECRET)


async def make_password(raw_password: str, algorithm: str = "argon2") -> str:
    """Hash a raw password (CPU-intensive, runs in thread pool).

    Args:
        raw_password: The plaintext password.
        algorithm: "argon2" (default), "bcrypt", or "plain" (testing only).

    Returns:
        The hashed password string (prefixed with algorithm identifier).
    """
    # Testing-only plain hasher — never use in production
    if algorithm == "plain":
        env = os.environ.get("ENVIRONMENT", "").lower()
        if env in ("production", "prod"):
            raise RuntimeError(
                "Plain text password hasher is disabled in production. "
                "Use 'argon2' or 'bcrypt' algorithm instead."
            )
        return f"plain${raw_password}"

    if algorithm == "argon2":
        # Offload CPU-intensive hashing to thread pool
        hashed = await asyncio.to_thread(_ARGON2_HASHER_MAKE.hash, raw_password)
        return f"argon2${hashed}"

    # Fallback to bcrypt (also offloaded to thread pool)
    def _bcrypt_hash() -> str:
        salt = bcrypt.gensalt(rounds=12)
        hashed_bytes = bcrypt.hashpw(raw_password.encode("utf-8"), salt)
        return f"bcrypt${hashed_bytes.decode('utf-8')}"

    return await asyncio.to_thread(_bcrypt_hash)


async def check_password(raw_password: str, hashed_password: str) -> bool:
    """Verify a raw password against a stored hash (CPU-intensive, runs in thread pool).

    Args:
        raw_password: User-supplied password.
        hashed_password: Stored hash (prefixed with algorithm).

    Returns:
        True if the password matches, False otherwise.
    """
    if hashed_password.startswith("argon2$"):
        encoded = hashed_password[len("argon2$") :]

        # Offload CPU-intensive verification to thread pool
        def _verify_argon2() -> bool:
            try:
                return _ARGON2_HASHER_CHECK.verify(encoded, raw_password)
            except VerifyMismatchError, VerificationError, InvalidHashError:
                return False

        return await asyncio.to_thread(_verify_argon2)

    if hashed_password.startswith("bcrypt$"):
        encoded_b = hashed_password[len("bcrypt$") :].encode("utf-8")

        # Offload CPU-intensive bcrypt check to thread pool
        def _verify_bcrypt() -> bool:
            try:
                return bcrypt.checkpw(raw_password.encode("utf-8"), encoded_b)
            except ValueError, Exception:
                return False

        return await asyncio.to_thread(_verify_bcrypt)

    # Testing hasher — plain prefix
    if hashed_password.startswith("plain$"):
        return hmac.compare_digest(raw_password, hashed_password[len("plain$") :])

    return False


def is_password_usable(hashed_password: str | None) -> bool:
    """Return True if the hash is usable (not a sentinel disabled value)."""
    return bool(hashed_password) and not hashed_password.startswith("!")  # type: ignore[union-attr]


def make_unusable_password() -> str:
    """Return a sentinel string that will never match any password."""
    return f"!{secrets.token_hex(8)}"
