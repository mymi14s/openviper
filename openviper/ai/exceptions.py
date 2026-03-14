"""Exceptions for the openviper AI subsystem.

:class:`ModelNotFoundError` and :class:`ModelCollisionError` have been
promoted to the top-level :mod:`openviper.exceptions` module and are
re-exported here for convenience.
"""

from __future__ import annotations

from openviper.exceptions import AIException, ModelCollisionError, ModelNotFoundError  # noqa: F401

# Re-export so existing ``from openviper.ai.exceptions import ...`` imports
# continue to work during the migration window.
__all__ = [
    "AIError",
    "AIException",
    "ModelUnavailableError",
    "ProviderNotAvailableError",
    "ProviderNotConfiguredError",
]

# Alias kept for code that catches AIError directly.
AIError = AIException


class ProviderNotConfiguredError(AIException):
    """Raised when a provider type is listed in settings but has no usable configuration."""

    __slots__ = ("provider",)

    def __init__(self, provider: str) -> None:
        super().__init__(f"AI provider '{provider}' is not configured in settings.AI_PROVIDERS.")
        self.provider = provider

    def __reduce__(self):
        return self.__class__, (self.provider,)


class ProviderNotAvailableError(AIException):
    """Raised when a provider cannot be initialised (e.g. missing SDK or bad API key)."""

    __slots__ = ("provider", "reason")

    def __init__(self, provider: str, reason: str = "") -> None:
        msg = f"AI provider '{provider}' is not available."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)
        self.provider = provider
        self.reason = reason

    def __reduce__(self):
        return self.__class__, (self.provider, self.reason)


class ModelUnavailableError(AIException):
    """Raised when a model is registered but the underlying provider cannot serve it."""

    __slots__ = ("model", "provider", "reason")

    def __init__(self, model: str, provider: str, reason: str = "") -> None:
        msg = f"Model '{model}' via provider '{provider}' is unavailable."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)
        self.model = model
        self.provider = provider
        self.reason = reason

    def __reduce__(self):
        return self.__class__, (self.model, self.provider, self.reason)
