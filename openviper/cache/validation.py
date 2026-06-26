"""Cache key validation utilities.

Isolated from the main package to break circular import cycles between
``openviper.cache`` and its submodules.
"""

from __future__ import annotations

import re

CACHE_KEY_MAX_LEN: int = 250
CACHE_KEY_RE: re.Pattern[str] = re.compile(r"^\S+$")


def validate_cache_key(key: str) -> str:
    """Validate and return a cache key, raising ``ValueError`` on invalid input.

    Keys must be non-empty, no longer than ``CACHE_KEY_MAX_LEN`` characters,
    and must not contain whitespace.
    """
    if not key:
        msg = "Cache key must not be empty"
        raise ValueError(msg)
    if len(key) > CACHE_KEY_MAX_LEN:
        msg = f"Cache key exceeds maximum length of {CACHE_KEY_MAX_LEN} characters"
        raise ValueError(msg)
    if not CACHE_KEY_RE.match(key):
        msg = f"Cache key {key!r} contains invalid characters (whitespace)"
        raise ValueError(msg)
    return key
