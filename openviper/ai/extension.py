"""Stable public API for third-party openviper AI provider authors."""

from __future__ import annotations

from openviper.ai.base import AIProvider
from openviper.ai.exceptions import (
    AIException,
    ModelCollisionError,
    ModelNotFoundError,
    ModelUnavailableError,
    ProviderNotAvailableError,
    ProviderNotConfiguredError,
)
from openviper.ai.registry import ProviderRegistry, provider_registry

EXTENSION_API_VERSION: tuple[int, int] = (1, 0)

__all__ = [
    # Version
    "EXTENSION_API_VERSION",
    # Core interface to implement
    "AIProvider",
    # Registry helpers
    "ProviderRegistry",
    "provider_registry",
    # Exceptions
    "AIException",
    "ModelCollisionError",
    "ModelNotFoundError",
    "ModelUnavailableError",
    "ProviderNotAvailableError",
    "ProviderNotConfiguredError",
]
