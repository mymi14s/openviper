"""OpenAI provider implementation."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from openviper.ai.base import AIProvider

_log = logging.getLogger("openviper.ai")

# Allowed kwargs forwarded to the OpenAI chat completions API.
_ALLOWED_GENERATE_KWARGS = frozenset(
    {"stop", "presence_penalty", "frequency_penalty", "logit_bias", "user", "n", "seed"}
)
_ALLOWED_STREAM_KWARGS = frozenset(
    {"stop", "presence_penalty", "frequency_penalty", "logit_bias", "user", "n", "seed"}
)


class OpenAIProvider(AIProvider):
    """OpenAI GPT provider.

    Config:
        api_key: Your OpenAI API key.
        model: Model name (e.g. "gpt-4o", "gpt-3.5-turbo").
        temperature: Sampling temperature.
        max_tokens: Maximum completion tokens.
        embed_model: Embedding model name.
    """

    name = "openai"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        """Get or create a persistent OpenAI client."""
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.config.get("api_key"))
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    @staticmethod
    def _filter_kwargs(kwargs: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
        """Return only whitelisted keys from *kwargs*, warning on unknown ones."""
        filtered = {}
        for k, v in kwargs.items():
            if k in allowed:
                filtered[k] = v
            else:
                _log.warning("OpenAIProvider: ignoring unknown kwarg %r", k)
        return filtered

    @staticmethod
    def _clamp_temperature(value: Any) -> float | None:
        if value is None:
            return None
        try:
            t = float(value)
        except TypeError, ValueError:
            return None
        return max(0.0, min(2.0, t))

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model) or ""
        temperature = self._clamp_temperature(
            kwargs.pop("temperature", self.config.get("temperature"))
        )
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        extra = self._filter_kwargs(kwargs, _ALLOWED_GENERATE_KWARGS)

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
        result = response.choices[0].message.content or ""
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model) or ""
        temperature = self._clamp_temperature(
            kwargs.pop("temperature", self.config.get("temperature"))
        )
        extra = self._filter_kwargs(kwargs, _ALLOWED_STREAM_KWARGS)

        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
            **extra,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        client = self._get_client()
        model = kwargs.pop("model", self.config.get("embed_model"))
        response = await client.embeddings.create(input=text, model=model)
        return response.data[0].embedding
