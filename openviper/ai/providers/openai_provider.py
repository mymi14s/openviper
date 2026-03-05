"""OpenAI provider implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openviper.ai.base import AIProvider


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

        global AsyncOpenAI
        from openai import AsyncOpenAI

        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        current_loop = getattr(self, "_client_loop", None)
        if getattr(self, "_client", None) is None or (loop and current_loop is not loop):
            self._client = AsyncOpenAI(api_key=self.config.get("api_key"))
            self._client_loop = loop
        return self._client

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model)
        temperature = kwargs.pop("temperature", self.config.get("temperature"))
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        result = response.choices[0].message.content or ""
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        client = self._get_client()
        model = kwargs.pop("model", self.default_model)
        temperature = kwargs.pop("temperature", self.config.get("temperature"))

        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
            **kwargs,
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
