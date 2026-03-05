"""Provider Development Kit — helpers for building custom AI providers.

Import from this module to reduce boilerplate when writing a new provider::

    from openviper.ai.devkit import SimpleProvider, map_http_error

    class MyProvider(SimpleProvider):
        name = "my_provider"

        async def generate(self, prompt: str, **kwargs) -> str:
            ...

Contents
--------
* :class:`SimpleProvider` — abstract base with extra convenience defaults.
* :func:`normalize_response` — strip and clean model output.
* :class:`StreamingAdapter` — wrap a sync generator into an async iterator.
* :func:`map_http_error` — convert HTTP status codes to typed exceptions.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Callable, Generator
from typing import Any

from openviper.ai.base import AIProvider
from openviper.ai.exceptions import (
    AIError,
    ModelUnavailableError,
    ProviderNotAvailableError,
)

# ---------------------------------------------------------------------------
# SimpleProvider
# ---------------------------------------------------------------------------


class SimpleProvider(AIProvider):
    """Abstract provider base with sensible convenience defaults.

    Differences from the bare :class:`~openviper.ai.base.AIProvider`:

    * Constructor accepts ``name`` as a keyword argument so you can create
      ad-hoc instances without subclassing.
    * :meth:`generate` gives a clearer ``NotImplementedError`` message.
    * :meth:`provider_name` returns an instance-level name override if set.

    Example::

        from openviper.ai.devkit import SimpleProvider

        class EchoProvider(SimpleProvider):
            name = "echo"

            async def generate(self, prompt: str, **kwargs: Any) -> str:
                return normalize_response(f"Echo: {prompt}")
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(config)
        if name is not None:
            self._instance_name = name

    def provider_name(self) -> str:
        return getattr(self, "_instance_name", self.name)

    @abc.abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Override this method to produce a text completion.

        Raises:
            NotImplementedError: Always — subclasses *must* implement this.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.generate() is not implemented. "
            "See openviper.ai.base.AIProvider for the full interface."
        )


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------


def normalize_response(text: str) -> str:
    """Strip leading/trailing whitespace and collapse internal blank lines.

    Useful as a one-liner post-processing step in :meth:`~AIProvider.generate`::

        async def generate(self, prompt, **kwargs):
            raw = await self._call_api(prompt)
            return normalize_response(raw)

    Args:
        text: Raw model output.

    Returns:
        Cleaned string with stripped edges and at most one consecutive blank
        line in the middle.
    """
    import re

    text = text.strip()
    # Collapse runs of 3+ newlines → 2 newlines (one blank line).
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# ---------------------------------------------------------------------------
# Streaming adapter
# ---------------------------------------------------------------------------


class StreamingAdapter:
    """Wrap a synchronous token generator into an ``AsyncIterator[str]``.

    Some inference libraries (e.g. local GGML bindings) expose a synchronous
    generator.  Wrap it with :class:`StreamingAdapter` to satisfy the
    ``stream()`` interface without blocking the event loop::

        from openviper.ai.devkit import StreamingAdapter

        async def stream(self, prompt, **kwargs):
            sync_gen = self._llm.generate(prompt, stream=True)
            async for token in StreamingAdapter(sync_gen):
                yield token

    The generator is consumed in a thread-pool executor so the event loop
    stays responsive.

    Args:
        source: A synchronous iterable that yields ``str`` tokens.
        executor: Optional :class:`~concurrent.futures.Executor`.  Defaults
            to the event-loop's default executor.
    """

    def __init__(
        self,
        source: Generator[str, None, None] | Callable[[], Generator[str, None, None]],
        executor: Any = None,
    ) -> None:
        self._source = source() if callable(source) else source
        self._executor = executor

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        import asyncio

        loop = asyncio.get_event_loop()

        def _next(it: Any) -> str | None:
            try:
                return next(it)
            except StopIteration:
                return None

        while True:
            token = await loop.run_in_executor(self._executor, _next, self._source)
            if token is None:
                break
            yield token


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------


def map_http_error(
    status_code: int,
    detail: str = "",
    *,
    provider: str = "unknown",
    model: str = "",
) -> AIError:
    """Convert an HTTP status code into a typed :class:`~openviper.ai.exceptions.AIError`.

    Use this in provider implementations to surface consistent exceptions::

        response = await client.post(url, json=payload)
        if not response.is_success:
            raise map_http_error(
                response.status_code,
                response.text,
                provider=self.name,
            )

    Args:
        status_code: HTTP response status code.
        detail: Error detail string from the response body.
        provider: Provider name for error messages.
        model: Model name / ID, included in ``ModelUnavailableError``.

    Returns:
        An appropriate :class:`~openviper.ai.exceptions.AIError` subclass.
    """

    reason = detail or f"HTTP {status_code}"

    if status_code in (401, 403):
        return ProviderNotAvailableError(provider, reason=f"Auth failed — {reason}")
    if status_code == 429:
        return ProviderNotAvailableError(provider, reason=f"Rate limit — {reason}")
    if status_code == 404 and model:
        return ModelUnavailableError(model, provider, reason=reason)
    if status_code >= 500:
        return ProviderNotAvailableError(provider, reason=f"Server error — {reason}")
    return AIError(f"Provider '{provider}' returned HTTP {status_code}: {reason}")


__all__ = [
    "SimpleProvider",
    "StreamingAdapter",
    "map_http_error",
    "normalize_response",
]
