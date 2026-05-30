"""Google Gemini AI provider (google-genai SDK)."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from types import ModuleType

from openviper.ai.base import AIProvider
from openviper.ai.security import validate_image_url

try:
    from google import genai as google_genai
    from google.genai import types as google_genai_types
except ImportError:
    google_genai: ModuleType | None = None
    google_genai_types: ModuleType | None = None

log = logging.getLogger("openviper.ai")

COST_TABLE: dict[str, dict[str, float]] = {
    "gemini-2.0-pro-exp": {"input": 0.00, "output": 0.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-thinking": {"input": 0.00, "output": 0.00},
    "gemini-1.5-pro": {"input": 3.50, "output": 10.50},
    "gemini-1.5-pro-latest": {"input": 3.50, "output": 10.50},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash-latest": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash-8b": {"input": 0.0375, "output": 0.15},
    "gemini-1.0-pro": {"input": 0.50, "output": 1.50},
    "gemini-pro": {"input": 0.50, "output": 1.50},
    "gemini-pro-vision": {"input": 0.50, "output": 1.50},
}


class GeminiError(Exception):
    """Base exception for Gemini provider errors."""


class GeminiAuthError(GeminiError):
    """Raised when the API key is missing or invalid."""


class GeminiRateLimitError(GeminiError):
    """Raised when the Gemini API rate limit is exceeded."""


def resolve_google_genai_modules() -> tuple[ModuleType, ModuleType]:
    """Return google-genai modules or raise the provider install error."""
    blocked_google = sys.modules.get("google") is None and "google" in sys.modules
    blocked_genai = sys.modules.get("google.genai") is None and "google.genai" in sys.modules
    if blocked_google or blocked_genai:
        raise ImportError(
            "The 'google-genai' package is required for GeminiProvider. "
            "Install it with: pip install openviper[ai]"
        )

    global google_genai, google_genai_types
    if google_genai is None or google_genai_types is None:
        try:
            from google import genai as loaded_genai
            from google.genai import types as loaded_types
        except ImportError as exc:
            raise ImportError(
                "The 'google-genai' package is required for GeminiProvider. "
                "Install it with: pip install openviper[ai]"
            ) from exc
        google_genai = loaded_genai
        google_genai_types = loaded_types
    return google_genai, google_genai_types


class GeminiProvider(AIProvider):
    """Google Gemini AI provider (google-genai SDK)."""

    name = "gemini"

    def __init__(self, config: dict[str, object]) -> None:
        super().__init__(config)
        self._api_key: str = config.get("api_key") or os.environ.get("GEMINI_API_KEY") or ""
        if not self._api_key:
            raise GeminiAuthError(
                "Gemini API key is required. "
                "Pass api_key in config or set the GEMINI_API_KEY environment variable."
            )
        self._default_model: str = self.default_model or ""

        self._genai, self._types = resolve_google_genai_modules()
        self._client: object | None = None

    def get_client(self) -> object:
        """Get or create a persistent google-genai Client."""
        if self._client is None:
            self._client = self._genai.Client(api_key=self._api_key)
        return self._client

    async def close(self) -> None:
        """Release the google-genai client (no-op if already closed)."""
        self._client = None

    def make_config(self, overrides: dict[str, object]) -> object:
        """Build a GenerateContentConfig from base config plus per-call overrides."""
        cfg: dict[str, object] = {
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

    def build_contents(
        self,
        prompt: str,
        images: list[dict[str, object]] | None = None,
    ) -> list[object]:
        """Build the contents list for generate_content.

        Image URLs are validated to prevent SSRF attacks.
        """
        parts: list[object] = [prompt]
        if images:
            for img in images:
                mime = img.get("mime_type", "image/jpeg")
                if "data" in img:
                    parts.append(self._types.Part.from_bytes(data=img["data"], mime_type=mime))
                elif "url" in img:
                    validate_image_url(img["url"], provider="GeminiProvider")
                    parts.append(self._types.Part.from_uri(file_uri=img["url"], mime_type=mime))
        return parts

    def wrap_error(self, exc: Exception) -> GeminiError:
        """Convert a google-genai exception to a GeminiError subclass.

        Sanitizes the error message to avoid leaking raw API internals.
        """
        msg = str(exc)
        # Classify by well-known sentinel strings; return generic messages.
        if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
            log.warning("GeminiProvider: authentication error (details suppressed).")
            return GeminiAuthError("Gemini authentication failed. Check your API key.")
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            log.warning("GeminiProvider: rate limit error (details suppressed).")
            return GeminiRateLimitError("Gemini rate limit exceeded. Retry after backoff.")
        # Truncate the raw message to limit information leakage in generic errors.
        safe_msg = msg[:200] if msg else "unknown error"
        return GeminiError(f"Gemini API error: {safe_msg}")

    async def generate(self, prompt: str, **kwargs: object) -> str:
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
            client = self.get_client()
            contents = self.build_contents(prompt, images)
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=self.make_config(gen_overrides),
            )
            result: str = response.text or ""
        except GeminiError, GeminiAuthError, GeminiRateLimitError:
            raise
        except Exception as exc:
            raise self.wrap_error(exc) from exc

        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model_name = kwargs.pop("model", self._default_model)
        images = kwargs.pop("images", None)

        gen_cfg_keys = ("temperature", "max_output_tokens", "top_p", "top_k", "candidate_count")
        gen_overrides = {k: kwargs.pop(k) for k in gen_cfg_keys if k in kwargs}

        try:
            client = self.get_client()
            contents = self.build_contents(prompt, images)
            async for chunk in client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=self.make_config(gen_overrides),
            ):
                if chunk.text:
                    yield chunk.text
        except GeminiError, GeminiAuthError, GeminiRateLimitError:
            raise
        except Exception as exc:
            raise self.wrap_error(exc) from exc

    async def embed(self, text: str, **kwargs: object) -> list[float]:
        client = self.get_client()
        model = kwargs.get("model", self.config.get("embed_model"))
        task_type = kwargs.get("task_type", "RETRIEVAL_DOCUMENT")
        try:
            response = await client.aio.models.embed_content(
                model=model,
                contents=text,
                config=self._types.EmbedContentConfig(task_type=task_type),
            )
            return response.embeddings[0].values
        except GeminiError, GeminiAuthError, GeminiRateLimitError:
            raise
        except Exception as exc:
            raise self.wrap_error(exc) from exc
