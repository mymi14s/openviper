"""Anthropic Claude provider implementation.

Requires the ``anthropic`` package::

    pip install openviper[ai]
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

try:
    from anthropic import AsyncAnthropic
except ImportError as _exc:
    raise ImportError(
        "The 'anthropic' package is required for AnthropicProvider. "
        "Install it with: pip install openviper[ai]"
    ) from _exc

from openviper.ai.base import AIProvider

_log = logging.getLogger("openviper.ai")

# Allowed kwargs forwarded to the Anthropic messages API.
_ALLOWED_KWARGS = frozenset({"stop_sequences", "system", "top_p", "top_k", "metadata"})


class AnthropicProvider(AIProvider):
    """Anthropic Claude provider.

    Config:
        api_key: Your Anthropic API key.
        model: Model name (e.g. "claude-3-5-sonnet-20241022").
        max_tokens: Maximum completion tokens.
    """

    name = "anthropic"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        """Get or create a persistent Anthropic client."""
        if self._client is None:
            self._client = AsyncAnthropic(api_key=self.config.get("api_key"))
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _filter_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Return only whitelisted keys from *kwargs*, warning on unknown ones."""
        filtered = {}
        for k, v in kwargs.items():
            if k in _ALLOWED_KWARGS:
                filtered[k] = v
            else:
                _log.warning("AnthropicProvider: ignoring unknown kwarg %r", k)
        return filtered

    @staticmethod
    def _clamp_temperature(value: Any) -> float | None:
        if value is None:
            return None
        try:
            t = float(value)
        except TypeError, ValueError:
            return None
        return max(0.0, min(1.0, t))

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model) or ""
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        extra = self._filter_kwargs(kwargs)

        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )
        result = response.content[0].text
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model) or ""
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        extra = self._filter_kwargs(kwargs)

        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **extra,
        ) as stream:
            async for text in stream.text_stream:
                yield text
