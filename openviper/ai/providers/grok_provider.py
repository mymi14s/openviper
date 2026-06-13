"""xAI Grok AI provider (OpenAI-compatible REST API via httpx)."""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import AsyncIterator

import httpx

from openviper.ai.base import AIProvider
from openviper.ai.provider_utils import (
    MAX_LINE_BYTES,
    clamp_temperature,
)
from openviper.ai.security import validate_base_url, validate_image_url

log = logging.getLogger("openviper.ai")

COST_TABLE: dict[str, dict[str, float]] = {
    "grok-3": {"input": 3.00, "output": 15.00},
    "grok-3-fast": {"input": 5.00, "output": 25.00},
    "grok-3-mini": {"input": 0.30, "output": 0.50},
    "grok-3-mini-fast": {"input": 0.60, "output": 4.00},
    "grok-2-latest": {"input": 2.00, "output": 10.00},
    "grok-2-1212": {"input": 2.00, "output": 10.00},
    "grok-2-vision-1212": {"input": 2.00, "output": 10.00},
    "grok-beta": {"input": 5.00, "output": 15.00},
}

ALLOWED_EXTRA_KWARGS = frozenset({"stop", "n", "user", "seed", "logit_bias"})


class GrokError(Exception):
    """Base exception for Grok provider errors."""


class GrokAuthError(GrokError):
    """Raised when the API key is missing or invalid."""


class GrokRateLimitError(GrokError):
    """Raised when the xAI rate limit is exceeded."""


class GrokProvider(AIProvider):
    """xAI Grok AI provider (OpenAI-compatible REST API via httpx)."""

    name = "grok"

    def __init__(self, config: dict[str, object]) -> None:
        super().__init__(config)
        self._api_key: str = config.get("api_key") or os.environ.get("XAI_API_KEY") or ""
        if not self._api_key:
            raise GrokAuthError(
                "xAI API key is required. "
                "Pass api_key in config or set the XAI_API_KEY environment variable."
            )
        self._default_model: str = self.default_model or ""
        base_url = config.get("base_url", "https://api.x.ai/v1").rstrip("/")
        validate_base_url(base_url, provider="GrokProvider")
        self._base_url: str = base_url
        self._timeout: float = float(config.get("timeout", 60.0))
        self._client: httpx.AsyncClient | None = None

    def get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client with connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get_headers(self) -> dict[str, str]:
        """Return request headers. Built fresh each call; never stored."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def build_messages(
        self,
        prompt: str,
        images: list[dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        if not images:
            return [{"role": "user", "content": prompt}]

        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        for img in images:
            if "url" in img:
                url = img["url"]
                if not url.startswith("data:"):
                    validate_image_url(url, provider="GrokProvider")
                data_url = url
            elif "base64" in img:
                mime = img.get("mime_type", "image/jpeg")
                data_url = f"data:{mime};base64,{img['base64']}"
            elif "data" in img:
                mime = img.get("mime_type", "image/jpeg")
                b64 = base64.b64encode(img["data"]).decode()
                data_url = f"data:{mime};base64,{b64}"
            else:
                continue
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        return [{"role": "user", "content": content}]

    @staticmethod
    def build_payload(
        messages: list[dict[str, object]],
        model: str,
        temperature: float,
        max_tokens: int,
        extra: dict[str, object],
    ) -> dict[str, object]:
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **extra,
        }

    def build_extra_params(self, kwargs: dict[str, object]) -> dict[str, object]:
        """Extract Grok-specific parameters and whitelist remaining kwargs."""
        extra: dict[str, object] = {}

        reasoning_effort = kwargs.pop("reasoning_effort", self.config.get("reasoning_effort"))
        if reasoning_effort is not None:
            extra["reasoning_effort"] = reasoning_effort

        search_enabled = kwargs.pop("search_enabled", self.config.get("search_enabled"))
        if search_enabled:
            extra["search_parameters"] = {"mode": "auto"}

        # Whitelist remaining kwargs - ignore unknown keys with a warning.
        for k in list(kwargs.keys()):
            if k in ALLOWED_EXTRA_KWARGS:
                extra[k] = kwargs.pop(k)
            else:
                log.warning("GrokProvider: ignoring unknown kwarg %r", k)
                kwargs.pop(k)

        return extra

    @staticmethod
    def raise_for_status(response: httpx.Response) -> None:
        """Raise an appropriate GrokError for non-2xx responses."""
        if response.is_success:
            return
        status = response.status_code
        try:
            raw_msg = response.json().get("error", {}).get("message", "")
            detail = str(raw_msg)[:200] if raw_msg else f"HTTP {status}"
        except ValueError, KeyError:
            detail = f"HTTP {status}"
        if status == 401:
            raise GrokAuthError("Grok authentication failed (401). Check your API key.")
        if status == 429:
            raise GrokRateLimitError("Grok rate limit exceeded (429). Retry after backoff.")
        raise GrokError(f"Grok API error {status}: {detail}")

    async def generate(self, prompt: str, **kwargs: object) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self._default_model)
        temperature = (
            clamp_temperature(kwargs.pop("temperature", self.config.get("temperature"))) or 1.0
        )
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        images = kwargs.pop("images", None)
        extra = self.build_extra_params(kwargs)

        messages = self.build_messages(prompt, images)
        payload = self.build_payload(messages, model, temperature, max_tokens, extra)

        client = self.get_client()
        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers=self.get_headers(),
            json=payload,
        )

        self.raise_for_status(response)
        result: str = response.json()["choices"][0]["message"]["content"] or ""
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self._default_model)
        temperature = (
            clamp_temperature(kwargs.pop("temperature", self.config.get("temperature"))) or 1.0
        )
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        images = kwargs.pop("images", None)
        extra = self.build_extra_params(kwargs)

        messages = self.build_messages(prompt, images)
        extra["stream"] = True
        payload = self.build_payload(messages, model, temperature, max_tokens, extra)

        client = self.get_client()
        async with client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            headers=self.get_headers(),
            json=payload,
        ) as response:
            self.raise_for_status(response)
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                if len(line.encode()) > MAX_LINE_BYTES:
                    log.warning(
                        "GrokProvider: stream line exceeded %d bytes, skipping.",
                        MAX_LINE_BYTES,
                    )
                    continue
                data = line[len("data: ") :]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    content = chunk["choices"][0]["delta"].get("content")
                    if content:
                        yield content
                except json.JSONDecodeError, KeyError, IndexError:
                    continue

    async def embed(self, text: str, **kwargs: object) -> list[float]:
        raise NotImplementedError(
            "The Grok (xAI) API does not expose an embeddings endpoint. "
            "Consider using a dedicated embedding service instead."
        )
