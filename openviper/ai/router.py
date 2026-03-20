"""ModelRouter — runtime-swappable AI provider client.

:class:`ModelRouter` is the high-level entry-point for AI inference.  It
stores the currently active model name and resolves the appropriate provider
from :class:`~openviper.ai.registry.ProviderRegistry` on every call.

Usage::

    from openviper.ai.router import model_router

    # Point at any registered model at any time (thread-safe)
    model_router.set_model("gemini-2.0-flash")
    result = await model_router.generate("Summarise this text...")

    # Switch to a different model mid-flight
    model_router.set_model("gpt-4o")
    async for chunk in model_router.stream("Write a haiku about clouds"):
        print(chunk, end="", flush=True)

Providers are never imported or instantiated here — the router delegates
all inference to the :class:`~openviper.ai.registry.ProviderRegistry`.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from openviper.ai.registry import ProviderRegistry, provider_registry

if TYPE_CHECKING:
    from openviper.ai.base import AIProvider


class ModelRouter:
    """Runtime-swappable AI inference client.

    The router holds the name of the current model and resolves its provider
    from :class:`~openviper.ai.registry.ProviderRegistry` on each call.
    All reads and writes of ``_model`` are protected by ``_lock``.

    Args:
        registry: :class:`~openviper.ai.registry.ProviderRegistry` to use.
                  Defaults to the global :data:`~openviper.ai.registry.provider_registry`.
        default_model: Optional model to use before :meth:`set_model` is called.
    """

    __slots__ = ("_registry", "_model", "_lock")

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        default_model: str | None = None,
    ) -> None:
        self._registry = registry or provider_registry
        self._model: str | None = default_model
        self._lock = threading.Lock()

    # ── Model selection ───────────────────────────────────────────────────────

    def set_model(self, model: str) -> None:
        """Select the active model.

        Args:
            model: Model ID (must be registered in the ProviderRegistry).
        """
        with self._lock:
            self._model = model

    def get_model(self) -> str | None:
        """Return the currently active model ID, or ``None`` if unset."""
        with self._lock:
            return self._model

    # ── Provider resolution ───────────────────────────────────────────────────

    def _get_provider(self, model: str | None = None) -> AIProvider:
        """Resolve the provider for *model* (falls back to active model).

        Takes a local snapshot of ``_model`` to avoid a race with concurrent
        :meth:`set_model` calls.  String attribute reads are atomic in CPython
        so we only need the lock for writes.

        Args:
            model: Override the active model for this call only.

        Returns:
            :class:`~openviper.ai.base.AIProvider` instance.

        Raises:
            :class:`~openviper.exceptions.ModelNotFoundError`:
                Neither *model* nor the active model is registered.
            RuntimeError: No model has been set and no override supplied.
        """
        target = model if model is not None else self._model
        if not target:
            raise RuntimeError("No model selected. Call model_router.set_model('model-id') first.")
        return self._registry.get_by_model(target)

    # ── Inference API ─────────────────────────────────────────────────────────

    async def generate(self, prompt: str, *, model: str | None = None, **kwargs: Any) -> str:
        """Generate a text completion.

        Args:
            prompt: Input text.
            model: Override the active model for this call only.
            **kwargs: Provider-specific options (temperature, max_tokens, etc.).

        Returns:
            Generated text string.
        """
        return await self._get_provider(model).generate(prompt, **kwargs)

    async def stream(
        self, prompt: str, *, model: str | None = None, **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream completion tokens.

        Args:
            prompt: Input text.
            model: Override the active model for this call only.
            **kwargs: Provider-specific options.

        Yields:
            Incremental text chunks.
        """
        async for chunk in self._get_provider(model).stream(prompt, **kwargs):
            yield chunk

    async def moderate(
        self, content: str, *, model: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Classify content for moderation.

        Args:
            content: Text to classify.
            model: Override the active model for this call only.
            **kwargs: Forwarded to the underlying provider.

        Returns:
            Dict with ``classification``, ``confidence``, ``reason``, ``is_safe``.
        """
        return await self._get_provider(model).moderate(content, **kwargs)

    async def embed(self, text: str, *, model: str | None = None, **kwargs: Any) -> list[float]:
        """Return an embedding vector for *text*.

        Args:
            text: Input text.
            model: Override the active model for this call only.
            **kwargs: Provider-specific options.

        Returns:
            List of floats.
        """
        return await self._get_provider(model).embed(text, **kwargs)

    # ── Convenience ───────────────────────────────────────────────────────────

    def list_models(self) -> list[str]:
        """Return all model IDs currently registered in the ProviderRegistry."""
        return self._registry.list_models()

    def __repr__(self) -> str:
        with self._lock:
            model = self._model
        return f"ModelRouter(model={model!r})"


# Global singleton — the primary inference entry-point for application code.
model_router = ModelRouter()
