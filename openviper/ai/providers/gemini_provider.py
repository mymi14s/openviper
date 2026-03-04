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

import os
from collections.abc import AsyncIterator
from typing import Any

from openviper.ai.base import AIProvider

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
        # Use default_model from base class if found, else DEFAULT_MODEL
        self._default_model: str = self.default_model or ""

        global genai, types
        from google import genai
        from google.genai import types

        self._client: "genai.Client" | None = None

    # ── SDK bootstrap ─────────────────────────────────────────────────────

    def _get_client(self) -> "genai.Client":
        """Return a lazily-initialised google-genai Client bound to the current event loop."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        current_loop = getattr(self, "_client_loop", None)
        if getattr(self, "_client", None) is None or (loop and current_loop is not loop):
            self._client = genai.Client(api_key=self._api_key)
            self._client_loop = loop
        return self._client

    def _make_config(self, overrides: dict[str, Any]) -> "types.GenerateContentConfig":
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
        return types.GenerateContentConfig(**cfg)

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _build_contents(
        prompt: str,
        images: list[dict[str, Any]] | None = None,
    ) -> list[Any]:
        """Build the contents list for generate_content.

        Args:
            prompt: Text prompt.
            images: Optional list of image dicts with either a ``data`` (bytes)
                    or ``url`` (str) key, plus an optional ``mime_type``.

        Returns:
            A list of parts accepted by ``client.aio.models.generate_content()``.
        """
        parts: list[Any] = [prompt]
        if images:
            for img in images:
                mime = img.get("mime_type", "image/jpeg")
                if "data" in img:
                    parts.append(types.Part.from_bytes(data=img["data"], mime_type=mime))
                elif "url" in img:
                    parts.append(types.Part.from_uri(file_uri=img["url"], mime_type=mime))
        return parts

    @staticmethod
    def _wrap_error(exc: Exception) -> GeminiError:
        """Convert a google-genai exception to a GeminiError subclass."""
        msg = str(exc)
        if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
            return GeminiAuthError(f"Gemini authentication failed: {msg}")
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            return GeminiRateLimitError(f"Gemini rate limit exceeded: {msg}")
        return GeminiError(f"Gemini API error: {msg}")

    # ── Core interface ─────────────────────────────────────────────────────

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a text completion.

        Args:
            prompt: Input text.
            **kwargs:
                model (str): Override the default model.
                images (list): Inline/URL images for vision requests.
                temperature (float): Sampling temperature.
                max_output_tokens (int): Max tokens in the response.
                top_p (float): Nucleus sampling.
                top_k (int): Top-k sampling.
                candidate_count (int): Number of candidates.

        Returns:
            Generated text string.

        Raises:
            GeminiAuthError: Invalid or missing API key.
            GeminiRateLimitError: Rate limit exceeded.
            GeminiError: Any other API error.
        """
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model_name = kwargs.pop("model", self._default_model)
        images = kwargs.pop("images", None)

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
        except Exception as exc:
            raise self._wrap_error(exc) from exc

        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream completion tokens.

        Args:
            prompt: Input text.
            **kwargs: Same as :meth:`generate`.

        Yields:
            Incremental text chunks.

        Raises:
            GeminiAuthError: Invalid or missing API key.
            GeminiRateLimitError: Rate limit exceeded.
            GeminiError: Any other API error.
        """
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
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        """Generate an embedding vector for *text*.

        Args:
            text: Input text to embed.
            **kwargs:
                model (str): Embedding model.  Defaults to
                    ``"models/text-embedding-004"``.
                task_type (str): One of ``"RETRIEVAL_DOCUMENT"``,
                    ``"RETRIEVAL_QUERY"``, ``"SEMANTIC_SIMILARITY"``, etc.

        Returns:
            List of floats (embedding vector).

        Raises:
            GeminiError: On API failure.
        """
        client = self._get_client()
        model = kwargs.get("model", self.config.get("embed_model"))
        task_type = kwargs.get("task_type", "RETRIEVAL_DOCUMENT")
        try:
            response = await client.aio.models.embed_content(
                model=model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            return response.embeddings[0].values
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    # ── Token counting & cost estimation ──────────────────────────────────

    def count_tokens(self, text: str) -> int:
        """Estimate the token count for *text* using a character-based heuristic.

        The google-genai SDK exposes ``client.aio.models.count_tokens()`` for
        exact counts, but ``count_tokens`` on the base class is synchronous.
        Callers needing an exact count should call the SDK directly; this
        provides a fast synchronous estimate (1 token ≈ 4 characters).

        Args:
            text: Text to count tokens in.

        Returns:
            Estimated token count (minimum 1).
        """
        return max(1, round(len(text) / _CHARS_PER_TOKEN))

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str | None = None,
    ) -> dict[str, float]:
        """Estimate API cost for a request.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            model: Model name (defaults to configured model).

        Returns:
            Dict with keys ``"input_cost"``, ``"output_cost"``, ``"total_cost"``
            (all in USD).
        """
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
