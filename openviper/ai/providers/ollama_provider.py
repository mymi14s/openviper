"""Ollama local model provider implementation."""

from __future__ import annotations

import ipaddress
import json
import logging
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

import httpx

from openviper.ai.base import AIProvider

_log = logging.getLogger("openviper.ai")

# Maximum byte length of a single SSE/JSON line accepted from the server.
# Protects against memory exhaustion from a malicious or buggy Ollama server.
_MAX_LINE_BYTES = 1 * 1024 * 1024  # 1 MiB

# Private IPv4/IPv6 ranges that must not be targeted (SSRF prevention).
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_base_url(url: str) -> None:
    """Raise ValueError if *url* targets a private/loopback address on a non-localhost host."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""

    # localhost variants are always permitted (local dev use-case).
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):  # nosec B104
        return

    # Reject non-HTTPS for non-localhost hosts.
    if parsed.scheme != "https":
        raise ValueError(f"OllamaProvider: non-localhost base_url must use HTTPS, got {url!r}")

    # Resolve and check for private IP ranges.
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Hostname — cannot resolve at config time; allow and rely on network policy.
        return

    for net in _PRIVATE_NETWORKS:
        if addr in net:
            raise ValueError(
                f"OllamaProvider: base_url resolves to a private/reserved address "
                f"({addr}), which is not permitted."
            )


class OllamaProvider(AIProvider):
    """Ollama local LLM provider.

    Config:
        base_url: Ollama server URL (default: http://localhost:11434).
        model: Model name (e.g. "llama3", "mistral", "codellama").
    """

    name = "ollama"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        base_url = config.get("base_url", "http://localhost:11434")
        _validate_base_url(base_url)
        self.base_url = base_url
        self.model = self.default_model or ""
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client with connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.model)

        client = self._get_client()
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

        client = self._get_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": True, **kwargs},
        ) as stream:
            async for raw_line in stream.aiter_lines():
                # Guard against memory exhaustion from oversized lines.
                if len(raw_line.encode()) > _MAX_LINE_BYTES:
                    _log.warning(
                        "OllamaProvider: stream line exceeded %d bytes, skipping.",
                        _MAX_LINE_BYTES,
                    )
                    continue
                if not raw_line.strip():
                    continue
                try:
                    data = json.loads(raw_line)
                except json.JSONDecodeError:
                    _log.warning("OllamaProvider: could not parse stream line as JSON, skipping.")
                    continue
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done", False):
                    break

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        model = kwargs.pop("model", self.model)
        client = self._get_client()
        response = await client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": model, "prompt": text},
        )
        response.raise_for_status()
        return response.json().get("embedding", [])
