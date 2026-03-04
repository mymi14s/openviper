"""Anthropic Claude provider implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openviper.ai.base import AIProvider


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

        global AsyncAnthropic
        from anthropic import AsyncAnthropic

        self._client: "AsyncAnthropic" | None = None

    def _get_client(self) -> "AsyncAnthropic":
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        current_loop = getattr(self, "_client_loop", None)
        if getattr(self, "_client", None) is None or (loop and current_loop is not loop):
            self._client = AsyncAnthropic(api_key=self.config.get("api_key"))
            self._client_loop = loop
        return self._client

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model)
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))

        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        result = response.content[0].text
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model)
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))

        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield text
