"""Anthropic Claude provider (anthropic SDK)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openviper.ai.base import AIProvider
from openviper.ai.provider_utils import filter_kwargs

try:
    from anthropic import AsyncAnthropic as AsyncAnthropic
except ImportError:
    AsyncAnthropic: type | None = None

log = logging.getLogger("openviper.ai")

# Allowed kwargs forwarded to the Anthropic messages API.
ALLOWED_KWARGS = frozenset({"stop_sequences", "system", "top_p", "top_k", "metadata"})


class AnthropicProvider(AIProvider):
    """Anthropic Claude provider (anthropic SDK)."""

    name = "anthropic"

    def __init__(self, config: dict[str, object]) -> None:
        super().__init__(config)
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        """Get or create a persistent Anthropic client."""
        if self._client is None:
            if AsyncAnthropic is None:
                raise ImportError(
                    "The 'anthropic' package is required for AnthropicProvider. "
                    "Install it with: pip install openviper[ai]"
                )
            self._client = AsyncAnthropic(api_key=self.config.get("api_key"))
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def generate(self, prompt: str, **kwargs: object) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model) or ""
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        extra = filter_kwargs(kwargs, ALLOWED_KWARGS, provider="AnthropicProvider")

        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )
        result = response.content[0].text
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model) or ""
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        extra = filter_kwargs(kwargs, ALLOWED_KWARGS, provider="AnthropicProvider")

        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **extra,
        ) as stream:
            async for text in stream.text_stream:
                yield text
