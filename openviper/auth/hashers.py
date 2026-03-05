"""Password hashing using Argon2id (primary) or bcrypt (fallback)."""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError


def make_password(raw_password: str, algorithm: str = "argon2") -> str:
    """Hash a raw password.

    Args:
        raw_password: The plaintext password.
        algorithm: "argon2" (default), "bcrypt", or "plain" (testing only).

    Returns:
        The hashed password string (prefixed with algorithm identifier).
    """
    import bcrypt

    # Testing-only plain hasher — never use in production
    if algorithm == "plain":
        return f"plain${raw_password}"

    if algorithm == "argon2":
        try:
            ph = PasswordHasher(
                time_cost=2,
                memory_cost=65536,
                parallelism=2,
                hash_len=32,
                salt_len=16,
            )
            hashed = ph.hash(raw_password)
            return f"argon2${hashed}"
        except ImportError:
            pass

    # Fallback to bcrypt
    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(raw_password.encode("utf-8"), salt)
    return f"bcrypt${hashed_bytes.decode('utf-8')}"


def check_password(raw_password: str, hashed_password: str) -> bool:
    """Verify a raw password against a stored hash.

    Args:
        raw_password: User-supplied password.
        hashed_password: Stored hash (prefixed with algorithm).

    Returns:
        True if the password matches, False otherwise.
    """
    if hashed_password.startswith("argon2$"):
        try:
            ph = PasswordHasher()
            encoded = hashed_password[len("argon2$") :]
            try:
                return ph.verify(encoded, raw_password)
            except (VerifyMismatchError, VerificationError):
                return False
        except ImportError:
            return False

    if hashed_password.startswith("bcrypt$"):
        import bcrypt

        encoded_b = hashed_password[len("bcrypt$") :].encode("utf-8")
        return bcrypt.checkpw(raw_password.encode("utf-8"), encoded_b)

    # Testing hasher — plain prefix
    if hashed_password.startswith("plain$"):
        return raw_password == hashed_password[len("plain$") :]

    return False


def is_password_usable(hashed_password: str | None) -> bool:
    """Return True if the hash is usable (not a sentinel disabled value)."""
    return bool(hashed_password) and not hashed_password.startswith("!")  # type: ignore[union-attr]


def make_unusable_password() -> str:
    """Return a sentinel string that will never match any password."""
    return f"!{secrets.token_hex(8)}"
