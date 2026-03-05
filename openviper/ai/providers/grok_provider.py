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
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from openviper.ai.base import AIProvider

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
        self._base_url: str = config.get("base_url", "https://api.x.ai/v1").rstrip("/")
        self._timeout: float = float(config.get("timeout", 60.0))

    # ── Helpers ────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_messages(
        self,
        prompt: str,
        images: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the chat messages list.

        Args:
            prompt: User text prompt.
            images: Optional list of image descriptors.

        Returns:
            List of ``{"role": "user", "content": ...}`` dicts.
        """
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

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        extra: dict[str, Any],
        stream: bool = False,
    ) -> dict[str, Any]:
        """Assemble the JSON request body."""
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            **extra,
        }

    def _build_extra_params(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Extract and translate Grok-specific parameters from kwargs.

        Pops: ``reasoning_effort``, ``search_enabled``.
        """
        extra: dict[str, Any] = {}

        reasoning_effort = kwargs.pop("reasoning_effort", self.config.get("reasoning_effort"))
        if reasoning_effort is not None:
            extra["reasoning_effort"] = reasoning_effort

        search_enabled = kwargs.pop("search_enabled", self.config.get("search_enabled"))
        if search_enabled:
            extra["search_parameters"] = {"mode": "auto"}

        return extra

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Raise an appropriate GrokError for non-2xx responses."""
        if response.is_success:
            return
        status = response.status_code
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except Exception:
            detail = response.text
        if status == 401:
            raise GrokAuthError(f"Grok authentication failed: {detail}")
        if status == 429:
            raise GrokRateLimitError(f"Grok rate limit exceeded: {detail}")
        raise GrokError(f"Grok API error {status}: {detail}")

    # ── Core interface ─────────────────────────────────────────────────

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a text completion via the Grok API.

        Args:
            prompt: Input text.
            **kwargs:
                model (str): Override the default model.
                temperature (float): Sampling temperature.
                max_tokens (int): Maximum tokens in the response.
                images (list): Inline/URL images for vision requests.
                reasoning_effort (str): ``"low"``, ``"medium"``, ``"high"``.
                search_enabled (bool): Enable live internet search.

        Returns:
            Generated text string.

        Raises:
            GrokAuthError: Invalid or missing API key.
            GrokRateLimitError: Rate limit exceeded.
            GrokError: Any other API error.
        """
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self._default_model)
        temperature = kwargs.pop("temperature", self.config.get("temperature"))
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        images = kwargs.pop("images", None)
        extra = self._build_extra_params(kwargs)
        extra.update(kwargs)  # forward any remaining caller-supplied kwargs

        messages = self._build_messages(prompt, images)
        payload = self._build_payload(messages, model, temperature, max_tokens, extra)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            )

        self._raise_for_status(response)
        result: str = response.json()["choices"][0]["message"]["content"] or ""
        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream completion tokens from the Grok API.

        Args:
            prompt: Input text.
            **kwargs: Same as :meth:`generate`.

        Yields:
            Incremental text chunks.

        Raises:
            GrokAuthError: Invalid or missing API key.
            GrokRateLimitError: Rate limit exceeded.
            GrokError: Any other API error.
        """
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self._default_model)
        temperature = kwargs.pop("temperature", self.config.get("temperature"))
        max_tokens = kwargs.pop("max_tokens", self.config.get("max_tokens"))
        images = kwargs.pop("images", None)
        extra = self._build_extra_params(kwargs)
        extra.update(kwargs)

        messages = self._build_messages(prompt, images)
        payload = self._build_payload(messages, model, temperature, max_tokens, extra, stream=True)

        async with (
            httpx.AsyncClient(timeout=self._timeout) as client,
            client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            ) as response,
        ):
            self._raise_for_status(response)
            async for line in response.aiter_lines():
                # Server-sent events are prefixed with "data: "
                if not line.startswith("data: "):
                    continue
                data = line[len("data: ") :]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    content = chunk["choices"][0]["delta"].get("content")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        """Not supported by the Grok API.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "The Grok (xAI) API does not expose an embeddings endpoint. "
            "Consider using a dedicated embedding service instead."
        )

    # ── Token counting & cost estimation ──────────────────────────────

    def count_tokens(self, text: str) -> int:
        """Estimate the token count for *text*.

        xAI does not expose a tokeniser endpoint, so this uses a
        character-based heuristic (1 token ≈ 4 characters).

        Args:
            text: Text to estimate token count for.

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
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.
            model: Model name (defaults to configured model).

        Returns:
            Dict with keys ``"input_cost"``, ``"output_cost"``, ``"total_cost"``
            (all in USD).
        """
        model_name = model or self._default_model
        rates = _COST_TABLE.get(model_name, _COST_TABLE["grok-2-latest"])

        input_cost = (input_tokens / 1_000_000) * rates["input"]
        output_cost = (output_tokens / 1_000_000) * rates["output"]
        return {
            "input_cost": round(input_cost, 8),
            "output_cost": round(output_cost, 8),
            "total_cost": round(input_cost + output_cost, 8),
        }
