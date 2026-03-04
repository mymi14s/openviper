"""Ollama local model provider implementation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from openviper.ai.base import AIProvider


class OllamaProvider(AIProvider):
    """Ollama local LLM provider.

    Config:
        base_url: Ollama server URL (default: DEFAULT_BASE_URL).
        model: Model name (e.g. "llama3", "mistral", "codellama").
    """

    name = "ollama"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.model = self.default_model or ""

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.model)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    **kwargs,
                },
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("response", "")
            return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.model)

        async with (
            httpx.AsyncClient(timeout=120.0) as client,
            client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": True, **kwargs},
            ) as stream,
        ):
            async for line in stream.aiter_lines():
                if line.strip():
                    data = json.loads(line)
                    token = data.get("response", "")
                    if token:
                        yield token
                    if data.get("done", False):
                        break

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        model = kwargs.pop("model", self.model)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            response.raise_for_status()
            return response.json().get("embedding", [])
