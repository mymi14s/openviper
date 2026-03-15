"""xAI Grok AI provider for OpenViper.

Grok uses an OpenAI-compatible REST API hosted at ``https://api.x.ai/v1``.
This provider uses ``httpx`` directly — no ``openai`` dependency required.

Installation:
    pip install openviper[ai]           # includes httpx

Configuration:
    .. code-block:: python

        from openviper.ai.registry import ai_registry
        from openviper.ai.providers.grok_provider import GrokProvider

        ai_registry.register("grok", GrokProvider, config={
            "api_key": "YOUR_XAI_API_KEY",
            "model": "grok-2-latest",
        })

Environment variable:
    ``XAI_API_KEY`` is read as a fallback when ``api_key`` is not in config.

Reasoning (for Grok 3 / grok-2):

    Pass ``reasoning_effort="high"`` to ``complete()`` or ``stream_complete()``
    to enable chain-of-thought reasoning.

Real-time web search:

    Pass ``search_enabled=True`` to ``complete()`` / ``stream_complete()`` to
    enable Grok's live internet search capability.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

import httpx

from openviper.ai.base import AIProvider

_log = logging.getLogger("openviper.ai")

# ── Cost table (USD per 1 000 000 tokens) ─────────────────────────────────
# Source: https://x.ai/api#pricing  (as of Feb 2026)
_COST_TABLE: dict[str, dict[str, float]] = {
    "grok-3": {"input": 3.00, "output": 15.00},
    "grok-3-fast": {"input": 5.00, "output": 25.00},
    "grok-3-mini": {"input": 0.30, "output": 0.50},
    "grok-3-mini-fast": {"input": 0.60, "output": 4.00},
    "grok-2-latest": {"input": 2.00, "output": 10.00},
    "grok-2-1212": {"input": 2.00, "output": 10.00},
    "grok-2-vision-1212": {"input": 2.00, "output": 10.00},
    "grok-beta": {"input": 5.00, "output": 15.00},
}

# Characters-per-token estimate used for count_tokens fallback
_CHARS_PER_TOKEN = 4.0

# Maximum byte length of a single SSE line accepted from the server.
_MAX_LINE_BYTES = 1 * 1024 * 1024  # 1 MiB

# Allowed extra kwargs forwarded to the Grok API payload.
_ALLOWED_EXTRA_KWARGS = frozenset({"stop", "n", "user", "seed", "logit_bias"})

# Private address ranges blocked for SSRF prevention.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_base_url(url: str) -> None:
    """Raise ValueError if *url* is not HTTPS or targets a private address."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""

    if parsed.scheme != "https":
        raise ValueError(f"GrokProvider: base_url must use HTTPS, got {url!r}")

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return  # Hostname — allow; network policy enforces at connection time.

    for net in _PRIVATE_NETWORKS:
        if addr in net:
            raise ValueError(
                f"GrokProvider: base_url resolves to a private/reserved address "
                f"({addr}), which is not permitted."
            )


class GrokError(Exception):
    """Base exception for Grok provider errors."""


class GrokAuthError(GrokError):
    """Raised when the API key is missing or invalid."""


class GrokRateLimitError(GrokError):
    """Raised when the xAI rate limit is exceeded."""


class GrokProvider(AIProvider):
    """xAI Grok AI provider (OpenAI-compatible REST API via httpx).

    Config keys:

    - api_key (str): xAI API key.  Falls back to ``XAI_API_KEY`` env var.
    - model (str): Default model name.  Defaults to ``"grok-2-latest"``.
    - temperature (float): Sampling temperature 0–2.  Defaults to ``1.0``.
    - max_tokens (int): Maximum completion tokens.  Defaults to ``2048``.
    - base_url (str): Override the API base URL.
      Defaults to ``"https://api.x.ai/v1"``.
    - timeout (float): HTTP timeout in seconds.  Defaults to ``60.0``.
    - reasoning_effort (str | None): ``"low"``, ``"medium"``, or ``"high"``.
      Enables chain-of-thought for supported models.
    - search_enabled (bool): Enable real-time web search capability.

    Vision:

    Pass an ``images`` list in ``**kwargs``::

        await provider.complete(
            "What's in this image?",
            images=[{"url": "https://example.com/photo.jpg"}],
        )

    Or supply raw bytes::

        import base64
        b64 = base64.b64encode(image_bytes).decode()
        await provider.complete(
            "Describe the image",
            images=[{"base64": b64, "mime_type": "image/png"}],
        )
    """

    name = "grok"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._api_key: str = config.get("api_key") or os.environ.get("XAI_API_KEY") or ""
        if not self._api_key:
            raise GrokAuthError(
                "xAI API key is required. "
                "Pass api_key in config or set the XAI_API_KEY environment variable."
            )
        self._default_model: str = self.default_model or ""
        base_url = config.get("base_url", "https://api.x.ai/v1").rstrip("/")
        _validate_base_url(base_url)
        self._base_url: str = base_url
        self._timeout: float = float(config.get("timeout", 60.0))
        self._client: httpx.AsyncClient | None = None

    # ── Helpers ────────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client with connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> dict[str, str]:
        """Return request headers. Built fresh each call; never stored."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_messages(
        self,
        prompt: str,
        images: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not images:
            return [{"role": "user", "content": prompt}]

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            if "url" in img:
                data_url = img["url"]
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
    def _build_payload(
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **extra,
        }

    def _build_extra_params(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Extract Grok-specific parameters and whitelist remaining kwargs."""
        extra: dict[str, Any] = {}

        reasoning_effort = kwargs.pop("reasoning_effort", self.config.get("reasoning_effort"))
        if reasoning_effort is not None:
            extra["reasoning_effort"] = reasoning_effort

        search_enabled = kwargs.pop("search_enabled", self.config.get("search_enabled"))
        if search_enabled:
            extra["search_parameters"] = {"mode": "auto"}

        # Whitelist remaining kwargs — ignore unknown keys with a warning.
        for k in list(kwargs.keys()):
            if k in _ALLOWED_EXTRA_KWARGS:
                extra[k] = kwargs.pop(k)
            else:
                _log.warning("GrokProvider: ignoring unknown kwarg %r", k)
                kwargs.pop(k)

        return extra

    @staticmethod
    def _clamp_temperature(value: Any) -> float:
        if value is None:
            return 1.0
        try:
            t = float(value)
        except TypeError, ValueError:
            return 1.0
        return max(0.0, min(2.0, t))

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Raise an appropriate GrokError for non-2xx responses."""
        if response.is_success:
            return
        status = response.status_code
        # Extract a safe, brief error message — avoid leaking raw API internals.
        try:
            raw_msg = response.json().get("error", {}).get("message", "")
            # Truncate to prevent log-flooding and info leakage.
            detail = str(raw_msg)[:200] if raw_msg else f"HTTP {status}"
        except ValueError, KeyError:
            detail = f"HTTP {status}"
        if status == 401:
            raise GrokAuthError("Grok authentication failed (401). Check your API key.")
        if status == 429:
            raise GrokRateLimitError("Grok rate limit exceeded (429). Retry after backoff.")
        raise GrokError(f"Grok API error {status}: {detail}")

    # ── Core interface ─────────────────────────────────────────────────

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self._default_model)
        temperature = self._clamp_temperature(
            kwargs.pop("temperature", self.config.get("temperature"))
        )
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        images = kwargs.pop("images", None)
        extra = self._build_extra_params(kwargs)

        messages = self._build_messages(prompt, images)
        payload = self._build_payload(messages, model, temperature, max_tokens, extra)

        client = self._get_client()
        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers=self._get_headers(),
            json=payload,
        )

        self._raise_for_status(response)
        result: str = response.json()["choices"][0]["message"]["content"] or ""
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self._default_model)
        temperature = self._clamp_temperature(
            kwargs.pop("temperature", self.config.get("temperature"))
        )
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        images = kwargs.pop("images", None)
        extra = self._build_extra_params(kwargs)

        messages = self._build_messages(prompt, images)
        extra["stream"] = True
        payload = self._build_payload(messages, model, temperature, max_tokens, extra)

        client = self._get_client()
        async with client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            headers=self._get_headers(),
            json=payload,
        ) as response:
            self._raise_for_status(response)
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                # Guard against memory exhaustion from oversized lines.
                if len(line.encode()) > _MAX_LINE_BYTES:
                    _log.warning(
                        "GrokProvider: stream line exceeded %d bytes, skipping.",
                        _MAX_LINE_BYTES,
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

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        raise NotImplementedError(
            "The Grok (xAI) API does not expose an embeddings endpoint. "
            "Consider using a dedicated embedding service instead."
        )

    # ── Token counting & cost estimation ──────────────────────────────

    def count_tokens(self, text: str) -> int:
        return max(1, round(len(text) / _CHARS_PER_TOKEN))

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str | None = None,
    ) -> dict[str, float]:
        model_name = model or self._default_model
        rates = _COST_TABLE.get(model_name, _COST_TABLE["grok-2-latest"])

        input_cost = (input_tokens / 1_000_000) * rates["input"]
        output_cost = (output_tokens / 1_000_000) * rates["output"]
        return {
            "input_cost": round(input_cost, 8),
            "output_cost": round(output_cost, 8),
            "total_cost": round(input_cost + output_cost, 8),
        }
