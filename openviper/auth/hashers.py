"""Password hashing using Argon2id (primary) or bcrypt (fallback)."""

from __future__ import annotations

import hmac
import secrets

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from openviper.conf import settings

# Reuse hasher instances to avoid per-call re-initialisation.
ARGON2_HASHER_MAKE = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)
ARGON2_HASHER_CHECK = PasswordHasher()

# A precomputed Argon2 dummy hash makes "user not found" branches
# take the same wall time as a real password check, preventing
# user enumeration via response-time differences.
DUMMY_PASSWORD_SECRET = secrets.token_urlsafe(32)
ARGON2_DUMMY_HASH: str = "argon2$" + ARGON2_HASHER_MAKE.hash(DUMMY_PASSWORD_SECRET)


async def make_password(raw_password: str, algorithm: str | None = None) -> str:
    """Hash a raw password.

    Args:
        raw_password: The plaintext password.
        algorithm: "argon2" (default), "bcrypt", or "plain" (testing only).

    Returns:
        The hashed password string (prefixed with algorithm identifier).
    """
    if algorithm is None:
        hashers: tuple[str, ...] = getattr(settings, "PASSWORD_HASHERS", ("argon2", "bcrypt"))
        algorithm = hashers[0] if hashers else "argon2"
    if algorithm == "plain":
        if not getattr(settings, "TESTING", False) and not getattr(settings, "DEBUG", False):
            raise RuntimeError(
                "Plain text password hasher requires TESTING=True or DEBUG=True. "
                "Use 'argon2' or 'bcrypt' algorithm instead."
            )
        return f"plain${raw_password}"

    if algorithm == "argon2":
        hashed = ARGON2_HASHER_MAKE.hash(raw_password)
        return f"argon2${hashed}"

    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(raw_password.encode("utf-8"), salt)
    return f"bcrypt${hashed_bytes.decode('utf-8')}"


async def check_password(raw_password: str, hashed_password: str) -> bool:
    """Verify a raw password against a stored hash.

    Args:
        raw_password: User-supplied password.
        hashed_password: Stored hash (prefixed with algorithm).

    Returns:
        True if the password matches, False otherwise.
    """
    if hashed_password.startswith("argon2$"):
        encoded = hashed_password[len("argon2$") :]
        try:
            return bool(ARGON2_HASHER_CHECK.verify(encoded, raw_password))
        except VerifyMismatchError, VerificationError, InvalidHashError:
            return False

    if hashed_password.startswith("bcrypt$"):
        encoded_b = hashed_password[len("bcrypt$") :].encode("utf-8")
        try:
            return bcrypt.checkpw(raw_password.encode("utf-8"), encoded_b)
        except ValueError, Exception:
            return False

    # Keep deterministic hashes available for test settings.
    if hashed_password.startswith("plain$"):
        return hmac.compare_digest(raw_password, hashed_password[len("plain$") :])

    return False


def is_password_usable(hashed_password: str | None) -> bool:
    """Return True if the hash is usable (not a sentinel disabled value)."""
    if not hashed_password:
        return False
    return not hashed_password.startswith("!")


def make_unusable_password() -> str:
    """Return a sentinel string that will never match any password."""
    return f"!{secrets.token_hex(8)}"
