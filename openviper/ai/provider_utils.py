"""Shared utilities for AI provider implementations."""

from __future__ import annotations

import logging

log = logging.getLogger("openviper.ai")

CHARS_PER_TOKEN = 4.0
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


def count_tokens(text: str) -> int:
    """Estimate token count from character length using a 4:1 ratio."""
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cost_table: dict[str, dict[str, float]],
    model: str,
    *,
    fallback_model: str | None = None,
) -> dict[str, float]:
    """Compute per-call cost from token counts and a provider cost table.

    Args:
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        cost_table: Mapping of model name to ``{"input": float, "output": float}`` rates.
        model: Target model name.
        fallback_model: Model to fall back to if *model* is not in *cost_table*.

    Returns:
        Dict with ``input_cost``, ``output_cost``, and ``total_cost`` in USD.
    """
    rates = cost_table.get(model)
    if rates is None and fallback_model:
        rates = cost_table.get(fallback_model)
    if rates is None:
        rates = next(iter(cost_table.values()))

    input_cost = (input_tokens / 1_000_000) * rates["input"]
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return {
        "input_cost": round(input_cost, 8),
        "output_cost": round(output_cost, 8),
        "total_cost": round(input_cost + output_cost, 8),
    }
