"""Provider Development Kit - helpers for building custom AI providers."""

from __future__ import annotations

import abc
import asyncio
import re
from collections.abc import AsyncIterator, Callable, Generator, Iterator
from concurrent.futures import Executor

from openviper.ai.base import AIProvider
from openviper.ai.exceptions import AIException, ModelUnavailableError, ProviderNotAvailableError


class SimpleProvider(AIProvider):
    """Abstract provider base with convenience defaults.

    Accepts ``name`` as a keyword argument for ad-hoc instances without
    subclassing.  :meth:`generate` raises a clearer ``NotImplementedError``.
    """

    def __init__(
        self,
        config: dict[str, object],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(config)
        if name is not None:
            self._instance_name = name

    def provider_name(self) -> str:
        return getattr(self, "_instance_name", self.name)

    @abc.abstractmethod
    async def generate(self, prompt: str, **kwargs: object) -> str:
        """Override this method to produce a text completion.

        Raises:
            NotImplementedError: Always - subclasses *must* implement this.
        """
        raise NotImplementedError(f"{type(self).__name__}.generate() is not implemented.")


def normalize_response(text: str) -> str:
    """Strip whitespace and collapse internal blank lines.

    Args:
        text: Raw model output.

    Returns:
        Cleaned string with stripped edges and at most one consecutive blank
        line in the middle.
    """
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


class StreamingAdapter:
    """Wrap a synchronous token generator into an AsyncIterator[str].

    The generator is consumed in a thread-pool executor so the event loop
    stays responsive.

    Args:
        source: A synchronous iterable that yields str tokens.
        executor: Optional Executor. Defaults to the event-loop's default executor.
    """

    def __init__(
        self,
        source: Generator[str] | Callable[[], Generator[str]],
        executor: Executor | None = None,
    ) -> None:
        self._source = source() if callable(source) else source
        self._executor = executor

    def __aiter__(self) -> AsyncIterator[str]:
        return self.iter()

    async def iter(self) -> AsyncIterator[str]:
        def next_token(it: Iterator[str]) -> str | None:
            try:
                return next(it)
            except StopIteration:
                return None

        while True:
            loop = asyncio.get_running_loop()
            token = await loop.run_in_executor(self._executor, next_token, self._source)
            if token is None:
                break
            yield token


def map_http_error(
    status_code: int,
    detail: str = "",
    *,
    provider: str = "unknown",
    model: str = "",
) -> AIException:
    """Convert an HTTP status code into a typed AIException.

    Args:
        status_code: HTTP response status code.
        detail: Error detail string from the response body.
        provider: Provider name for error messages.
        model: Model name / ID, included in ModelUnavailableError.

    Returns:
        An appropriate AIException subclass.
    """

    reason = detail or f"HTTP {status_code}"

    if status_code in (401, 403):
        return ProviderNotAvailableError(provider, reason=f"Auth failed - {reason}")
    if status_code == 429:
        return ProviderNotAvailableError(provider, reason=f"Rate limit - {reason}")
    if status_code == 404 and model:
        return ModelUnavailableError(model, provider, reason=reason)
    if status_code >= 500:
        return ProviderNotAvailableError(provider, reason=f"Server error - {reason}")
    return AIException(f"Provider '{provider}' returned HTTP {status_code}: {reason}")


__all__ = [
    "SimpleProvider",
    "StreamingAdapter",
    "map_http_error",
    "normalize_response",
]
