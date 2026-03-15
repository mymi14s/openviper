"""AI model provider base class and inference protocol."""

from __future__ import annotations

import abc
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger("openviper.ai")


class AIProvider(abc.ABC):
    """Abstract base class for AI model providers.

    Implement :meth:`generate` (and optionally :meth:`stream`) to integrate a
    new AI backend with OpenViper.

    Example:
        .. code-block:: python

            from openviper.ai.base import AIProvider

            class MyProvider(AIProvider):
                name = "myprovider"

                async def generate(self, prompt: str, **kwargs) -> str:
                    return "Hello from MyProvider"
    """

    name: str = "base"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

        # Determine the default model name.
        # It can be in 'model' (as a string or dict) or 'models' (as a list or dict).
        model_cfg = config.get("model")
        models_cfg = config.get("models")

        # 1. Try 'model' key (might be a string or a dict with a 'default')
        if isinstance(model_cfg, str):
            self.default_model = model_cfg
        elif isinstance(model_cfg, dict):
            self.default_model = model_cfg.get("default") or next(iter(model_cfg.values()), None)
        else:
            self.default_model = None

        # 2. Try 'models' key if not yet found
        if not self.default_model:
            if isinstance(models_cfg, dict) and models_cfg:
                self.default_model = models_cfg.get("default") or next(iter(models_cfg.values()))
            elif isinstance(models_cfg, list) and models_cfg:
                self.default_model = models_cfg[0]

    # ── Primary interface ─────────────────────────────────────────────────────

    @abc.abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a text completion for the given prompt.

        Args:
            prompt: Input text.
            **kwargs: Provider-specific options (temperature, max_tokens, etc.).

        Returns:
            Generated text string.
        """

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream completion tokens.

        Default implementation calls :meth:`generate` and yields the full
        result as a single chunk.  Override for true token-by-token streaming.

        Args:
            prompt: Input text.
            **kwargs: Provider-specific options.

        Yields:
            Incremental text chunks.
        """
        result = await self.generate(prompt, **kwargs)
        yield result

    async def moderate(self, content: str, **kwargs: Any) -> dict[str, Any]:
        """Classify content for moderation.

        Default implementation sends a structured JSON prompt to
        :meth:`generate`.  Providers may override for a native moderation API.

        Args:
            content: Text to classify.
            **kwargs: Forwarded to :meth:`generate`.

        Returns:
            Dict with keys ``classification`` (str), ``confidence`` (float 0-1),
            ``reason`` (str), and ``is_safe`` (bool).
        """
        max_content = 2000
        truncated = len(content) > max_content
        safe_content = content[:max_content]
        if truncated:
            logger.warning(
                "moderate(): content truncated from %d to %d characters — "
                "only the first portion was evaluated.",
                len(content),
                max_content,
            )

        # Isolate user content from instructions with a clear delimiter to
        # prevent prompt injection attacks.
        prompt = (
            "You are a strict content moderation AI.\n"
            "Analyze the text between the <content> tags and respond ONLY with "
            "valid JSON (no markdown, no extra text):\n"
            '{"classification": "safe|spam|abusive|hate|sexual", '
            '"confidence": 0.0-1.0, "reason": "short explanation"}\n\n'
            f"<content>{safe_content}</content>\n\nRespond with valid JSON only:"
        )
        raw = await self.generate(prompt, **kwargs)

        # Strip markdown fences if present
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        if "{" in text and "}" in text:
            text = text[text.find("{") : text.rfind("}") + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {
                "classification": "safe",
                "confidence": 0.0,
                "reason": "Parse error — could not decode AI response.",
                "is_safe": True,
                "truncated": truncated,
            }

        classification = str(data.get("classification", "safe")).lower()
        valid_classes = {"safe", "spam", "abusive", "hate", "sexual"}
        if classification not in valid_classes:
            classification = "safe"
        try:
            confidence = float(data.get("confidence", 0.5))
        except ValueError, TypeError:
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        reason = str(data.get("reason", "No reason provided"))
        is_safe = classification == "safe" or confidence < 0.7

        return {
            "classification": classification,
            "confidence": confidence,
            "reason": reason,
            "is_safe": is_safe,
            "truncated": truncated,
        }

    def supported_models(self) -> list[str]:
        """Return the list of model IDs this provider can serve.

        Extracts unique model ID values (not display-name keys) from the
        ``models`` and ``model`` dicts in the provider config.

        Returns:
            Sorted list of model ID strings.
        """
        ids: set[str] = set()
        models_cfg = self.config.get("models")
        model_cfg = self.config.get("model")

        if isinstance(models_cfg, dict):
            for v in models_cfg.values():
                if isinstance(v, str):
                    ids.add(v)
        elif isinstance(models_cfg, list):
            for v in models_cfg:
                if isinstance(v, str):
                    ids.add(v)

        if isinstance(model_cfg, dict):
            for v in model_cfg.values():
                if isinstance(v, str):
                    ids.add(v)
        elif isinstance(model_cfg, str):
            ids.add(model_cfg)

        return sorted(ids)

    def provider_name(self) -> str:
        """Return the canonical name for this provider (same as the ``name`` class attribute)."""
        return self.name

    # ── Embedding ─────────────────────────────────────────────────────────────

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        """Return an embedding vector for the given text.

        Not all providers support embeddings.

        Raises:
            NotImplementedError: Provider does not support embeddings.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support embeddings.")

    # ── Hooks ─────────────────────────────────────────────────────────────────

    async def before_inference(
        self, prompt: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Hook called before each inference. Override to transform input.

        Args:
            prompt: The input prompt.
            kwargs: Inference keyword arguments.

        Returns:
            (modified_prompt, modified_kwargs)
        """
        return prompt, kwargs

    async def after_inference(self, prompt: str, response: str) -> str:
        """Hook called after each inference. Override to transform output.

        Args:
            prompt: Original prompt.
            response: Generated response.

        Returns:
            Modified response.
        """
        return response

    # ── Backward-compatibility aliases ────────────────────────────────────────

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        """Alias for :meth:`generate`.  Kept for backward compatibility."""
        return await self.generate(prompt, **kwargs)

    async def stream_complete(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Alias for :meth:`stream`.  Kept for backward compatibility."""
        async for chunk in self.stream(prompt, **kwargs):
            yield chunk
