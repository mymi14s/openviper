"""Ollama local model provider implementation."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from openviper.ai.base import AIProvider
from openviper.ai.provider_utils import MAX_LINE_BYTES, filter_kwargs
from openviper.ai.security import validate_base_url

log = logging.getLogger("openviper.ai")

ALLOWED_GENERATE_KWARGS = frozenset(
    {"options", "system", "template", "context", "raw", "format", "keep_alive", "images"}
)
ALLOWED_EMBED_KWARGS = frozenset({"options", "keep_alive"})


class OllamaProvider(AIProvider):
    """Ollama local LLM provider."""

    name = "ollama"

    def __init__(self, config: dict[str, object]) -> None:
        super().__init__(config)
        base_url = config.get("base_url", "http://localhost:11434")
        validate_base_url(base_url, allow_localhost=True, provider="OllamaProvider")
        self.base_url = base_url
        self.model = self.default_model or ""
        self._client: httpx.AsyncClient | None = None

    def get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client with connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt: str, **kwargs: object) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.model)
        extra = filter_kwargs(kwargs, ALLOWED_GENERATE_KWARGS, provider="OllamaProvider")

        client = self.get_client()
        response = await client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                **extra,
            },
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("response", "")
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.model)
        extra = filter_kwargs(kwargs, ALLOWED_GENERATE_KWARGS, provider="OllamaProvider")

        client = self.get_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": True, **extra},
        ) as stream:
            async for raw_line in stream.aiter_lines():
                if len(raw_line.encode()) > MAX_LINE_BYTES:
                    log.warning(
                        "OllamaProvider: stream line exceeded %d bytes, skipping.",
                        MAX_LINE_BYTES,
                    )
                    continue
                if not raw_line.strip():
                    continue
                try:
                    data = json.loads(raw_line)
                except json.JSONDecodeError:
                    log.warning("OllamaProvider: could not parse stream line as JSON, skipping.")
                    continue
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done", False):
                    break

    async def embed(self, text: str, **kwargs: object) -> list[float]:
        model = kwargs.pop("model", self.model)
        extra = filter_kwargs(kwargs, ALLOWED_EMBED_KWARGS, provider="OllamaProvider")
        client = self.get_client()
        response = await client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": model, "prompt": text, **extra},
        )
        response.raise_for_status()
        return response.json().get("embedding", [])
