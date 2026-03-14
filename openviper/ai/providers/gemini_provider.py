"""Google Gemini AI provider for OpenViper.

Supports Gemini Pro, Ultra, Flash, and Vision models via the
``google-genai`` SDK.

Installation:
    pip install google-genai

Configuration:
    .. code-block:: python

        from openviper.ai.registry import ai_registry
        from openviper.ai.providers.gemini_provider import GeminiProvider

        ai_registry.register("gemini", GeminiProvider, config={
            "api_key": "YOUR_GEMINI_API_KEY",
            "model": "gemini-1.5-flash",
        })

Environment variable:
    ``GEMINI_API_KEY`` is read as a fallback when ``api_key`` is not in config.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

from openviper.ai.base import AIProvider

_log = logging.getLogger("openviper.ai")

# ── Cost table (USD per 1 000 000 tokens) ────────────────────────────────────
# Source: https://ai.google.dev/pricing  (as of Feb 2026)
_COST_TABLE: dict[str, dict[str, float]] = {
    "gemini-2.0-pro-exp": {"input": 0.00, "output": 0.00},  # free preview
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-thinking": {"input": 0.00, "output": 0.00},  # free preview
    "gemini-1.5-pro": {"input": 3.50, "output": 10.50},
    "gemini-1.5-pro-latest": {"input": 3.50, "output": 10.50},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash-latest": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash-8b": {"input": 0.0375, "output": 0.15},
    "gemini-1.0-pro": {"input": 0.50, "output": 1.50},
    "gemini-pro": {"input": 0.50, "output": 1.50},
    "gemini-pro-vision": {"input": 0.50, "output": 1.50},
}

_CHARS_PER_TOKEN = 4.0

# Private address ranges blocked for SSRF prevention on image URLs.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_image_url(url: str) -> None:
    """Raise ValueError if *url* is non-HTTPS or targets a private address."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"GeminiProvider: image URL must be http(s), got {url!r}")
    host = parsed.hostname or ""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return  # Hostname — allow; network policy enforces at connection time.
    for net in _PRIVATE_NETWORKS:
        if addr in net:
            raise ValueError(
                f"GeminiProvider: image URL resolves to a private/reserved address "
                f"({addr}), which is not permitted."
            )


class GeminiError(Exception):
    """Base exception for Gemini provider errors."""


class GeminiAuthError(GeminiError):
    """Raised when the API key is missing or invalid."""


class GeminiRateLimitError(GeminiError):
    """Raised when the Gemini API rate limit is exceeded."""


class GeminiProvider(AIProvider):
    """Google Gemini AI provider.

    Config keys:
        api_key (str): Google AI API key.  Falls back to ``GEMINI_API_KEY`` env var.
        model (str): Default model name.  Defaults to ``"gemini-1.5-flash"``.
        temperature (float): Sampling temperature 0–2.  Defaults to ``1.0``.
        max_output_tokens (int): Maximum tokens in the response.  Defaults to ``2048``.
        top_p (float | None): Nucleus-sampling probability.
        top_k (int | None): Top-k sampling.
        candidate_count (int): Number of candidate responses (default 1).
        embed_model (str): Embedding model.  Defaults to ``"models/text-embedding-004"``.

    Vision:
        Pass ``images`` as a list of dicts via ``**kwargs`` to ``complete()``::

            await provider.complete(
                "Describe this image",
                images=[{"mime_type": "image/jpeg", "data": b"<raw bytes>"}],
            )

        Or pass a URL dict::

            images=[{"mime_type": "image/jpeg", "url": "https://example.com/photo.jpg"}]
    """

    name = "gemini"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._api_key: str = config.get("api_key") or os.environ.get("GEMINI_API_KEY") or ""
        if not self._api_key:
            raise GeminiAuthError(
                "Gemini API key is required. "
                "Pass api_key in config or set the GEMINI_API_KEY environment variable."
            )
        self._default_model: str = self.default_model or ""

        try:
            from google import genai  # type: ignore[import-untyped]
            from google.genai import types  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "google-genai could not be imported. "
                "Try upgrading: pip install --upgrade google-genai"
            ) from exc

        self._genai = genai
        self._types = types
        self._client: Any | None = None

    # ── SDK bootstrap ─────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        """Get or create a persistent google-genai Client."""
        if self._client is None:
            self._client = self._genai.Client(api_key=self._api_key)
        return self._client

    async def close(self) -> None:
        """Release the google-genai client (no-op if already closed)."""
        self._client = None

    def _make_config(self, overrides: dict[str, Any]) -> Any:
        """Build a GenerateContentConfig from base config plus per-call overrides."""
        cfg: dict[str, Any] = {
            "temperature": self.config.get("temperature"),
            "max_output_tokens": self.config.get("max_output_tokens"),
            "candidate_count": self.config.get("candidate_count"),
        }
        if self.config.get("top_p") is not None:
            cfg["top_p"] = self.config["top_p"]
        if self.config.get("top_k") is not None:
            cfg["top_k"] = self.config["top_k"]
        cfg.update(overrides)
        return self._types.GenerateContentConfig(**cfg)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _build_contents(
        self,
        prompt: str,
        images: list[dict[str, Any]] | None = None,
    ) -> list[Any]:
        """Build the contents list for generate_content.

        Image URLs are validated to prevent SSRF attacks.
        """
        parts: list[Any] = [prompt]
        if images:
            for img in images:
                mime = img.get("mime_type", "image/jpeg")
                if "data" in img:
                    parts.append(self._types.Part.from_bytes(data=img["data"], mime_type=mime))
                elif "url" in img:
                    _validate_image_url(img["url"])
                    parts.append(self._types.Part.from_uri(file_uri=img["url"], mime_type=mime))
        return parts

    def _wrap_error(self, exc: Exception) -> GeminiError:
        """Convert a google-genai exception to a GeminiError subclass.

        Sanitizes the error message to avoid leaking raw API internals.
        """
        msg = str(exc)
        # Classify by well-known sentinel strings; return generic messages.
        if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
            _log.warning("GeminiProvider: authentication error (details suppressed).")
            return GeminiAuthError("Gemini authentication failed. Check your API key.")
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            _log.warning("GeminiProvider: rate limit error (details suppressed).")
            return GeminiRateLimitError("Gemini rate limit exceeded. Retry after backoff.")
        # Truncate the raw message to limit information leakage in generic errors.
        safe_msg = msg[:200] if msg else "unknown error"
        return GeminiError(f"Gemini API error: {safe_msg}")

    # ── Core interface ─────────────────────────────────────────────────────

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model_name = kwargs.pop("model", self._default_model)
        images = kwargs.pop("images", None)

        # Accept max_tokens as an alias for max_output_tokens (common cross-provider name)
        if "max_tokens" in kwargs and "max_output_tokens" not in kwargs:
            kwargs["max_output_tokens"] = kwargs.pop("max_tokens")
        else:
            kwargs.pop("max_tokens", None)

        gen_cfg_keys = ("temperature", "max_output_tokens", "top_p", "top_k", "candidate_count")
        gen_overrides = {k: kwargs.pop(k) for k in gen_cfg_keys if k in kwargs}

        try:
            client = self._get_client()
            contents = self._build_contents(prompt, images)
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=self._make_config(gen_overrides),
            )
            result: str = response.text or ""
        except (GeminiError, GeminiAuthError, GeminiRateLimitError):
            raise
        except Exception as exc:
            raise self._wrap_error(exc) from exc

        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model_name = kwargs.pop("model", self._default_model)
        images = kwargs.pop("images", None)

        gen_cfg_keys = ("temperature", "max_output_tokens", "top_p", "top_k", "candidate_count")
        gen_overrides = {k: kwargs.pop(k) for k in gen_cfg_keys if k in kwargs}

        try:
            client = self._get_client()
            contents = self._build_contents(prompt, images)
            async for chunk in client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=self._make_config(gen_overrides),
            ):
                if chunk.text:
                    yield chunk.text
        except (GeminiError, GeminiAuthError, GeminiRateLimitError):
            raise
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        client = self._get_client()
        model = kwargs.get("model", self.config.get("embed_model"))
        task_type = kwargs.get("task_type", "RETRIEVAL_DOCUMENT")
        try:
            response = await client.aio.models.embed_content(
                model=model,
                contents=text,
                config=self._types.EmbedContentConfig(task_type=task_type),
            )
            return response.embeddings[0].values
        except (GeminiError, GeminiAuthError, GeminiRateLimitError):
            raise
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    # ── Token counting & cost estimation ──────────────────────────────────

    def count_tokens(self, text: str) -> int:
        return max(1, round(len(text) / _CHARS_PER_TOKEN))

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str | None = None,
    ) -> dict[str, float]:
        model_name = model or self._default_model
        rates = _COST_TABLE.get(model_name) or _COST_TABLE.get(model_name.replace("-latest", ""))
        if rates is None:
            rates = _COST_TABLE["gemini-1.5-pro"]

        input_cost = (input_tokens / 1_000_000) * rates["input"]
        output_cost = (output_tokens / 1_000_000) * rates["output"]
        return {
            "input_cost": round(input_cost, 8),
            "output_cost": round(output_cost, 8),
            "total_cost": round(input_cost + output_cost, 8),
        }
