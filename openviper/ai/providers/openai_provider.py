"""OpenAI GPT provider (openai SDK)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openviper.ai.base import AIProvider
from openviper.ai.provider_utils import clamp_temperature, filter_kwargs

try:
    from openai import AsyncOpenAI as AsyncOpenAI
except ImportError:
    AsyncOpenAI: type | None = None

log = logging.getLogger("openviper.ai")

# Allowed kwargs forwarded to the OpenAI chat completions API.
ALLOWED_GENERATE_KWARGS = frozenset(
    {"stop", "presence_penalty", "frequency_penalty", "logit_bias", "user", "n", "seed"}
)
ALLOWED_STREAM_KWARGS = frozenset(
    {"stop", "presence_penalty", "frequency_penalty", "logit_bias", "user", "n", "seed"}
)


class OpenAIProvider(AIProvider):
    """OpenAI GPT provider (openai SDK)."""

    name = "openai"

    def __init__(self, config: dict[str, object]) -> None:
        super().__init__(config)
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        """Get or create a persistent OpenAI client."""
        if self._client is None:
            if AsyncOpenAI is None:
                raise ImportError(
                    "The 'openai' package is required for OpenAIProvider. "
                    "Install it with: pip install openviper[ai]"
                )
            self._client = AsyncOpenAI(api_key=self.config.get("api_key"))
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
        temperature = clamp_temperature(kwargs.pop("temperature", self.config.get("temperature")))
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        extra = filter_kwargs(kwargs, ALLOWED_GENERATE_KWARGS, provider="OpenAIProvider")

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
        result = response.choices[0].message.content or ""
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model) or ""
        temperature = clamp_temperature(kwargs.pop("temperature", self.config.get("temperature")))
        extra = filter_kwargs(kwargs, ALLOWED_STREAM_KWARGS, provider="OpenAIProvider")

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

    async def embed(self, text: str, **kwargs: object) -> list[float]:
        client = self._get_client()
        model = kwargs.pop("model", self.config.get("embed_model"))
        response = await client.embeddings.create(input=text, model=model)
        return response.data[0].embedding
