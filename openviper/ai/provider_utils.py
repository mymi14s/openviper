"""Shared utilities for AI provider implementations."""

from __future__ import annotations

import logging

log = logging.getLogger("openviper.ai")

MAX_LINE_BYTES = 1 * 1024 * 1024  # 1 MiB


def filter_kwargs(
    kwargs: dict[str, object],
    allowed: frozenset[str],
    *,
    provider: str = "Provider",
) -> dict[str, object]:
    """Return only whitelisted keys from *kwargs*, warning on unknown ones."""
    filtered: dict[str, object] = {}
    for k, v in kwargs.items():
        if k in allowed:
            filtered[k] = v
        else:
            log.warning("%s: ignoring unknown kwarg %r", provider, k)
    return filtered


def clamp_temperature(value: object, *, max_temp: float = 2.0) -> float | None:
    """Clamp a temperature value between 0.0 and *max_temp*.

    Returns None for non-numeric or None inputs.
    """
    if value is None:
        return None
    try:
        t = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(max_temp, t))
