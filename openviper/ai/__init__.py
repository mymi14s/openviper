"""OpenViper AI integration package."""

from __future__ import annotations

import importlib

from openviper.ai.base import AIProvider
from openviper.ai.devkit import (
    SimpleProvider,
    StreamingAdapter,
    map_http_error,
    normalize_response,
)
from openviper.ai.exceptions import (
    AIException,
    ModelCollisionError,
    ModelNotFoundError,
    ModelUnavailableError,
    ProviderNotAvailableError,
    ProviderNotConfiguredError,
)
from openviper.ai.extension import EXTENSION_API_VERSION
from openviper.ai.providers import PROVIDER_MAP
from openviper.ai.registry import ProviderRegistry, ai_registry, provider_registry
from openviper.ai.router import ModelRouter, model_router

__all__ = [
    # Base
    "AIProvider",
    # Extension API version
    "EXTENSION_API_VERSION",
    # Exceptions
    "AIException",
    "ModelCollisionError",
    "ModelNotFoundError",
    "ModelUnavailableError",
    "ProviderNotAvailableError",
    "ProviderNotConfiguredError",
    # Development toolkit
    "SimpleProvider",
    "StreamingAdapter",
    "map_http_error",
    "normalize_response",
    # Providers (lazy)
    "AnthropicProvider",
    "GeminiProvider",
    "GrokProvider",
    "OllamaProvider",
    "OpenAIProvider",
    # Registries
    "ProviderRegistry",
    "ai_registry",
    "provider_registry",
    # Router
    "ModelRouter",
    "model_router",
]


def __getattr__(name: str) -> type:
    if name in PROVIDER_MAP:
        module = importlib.import_module(PROVIDER_MAP[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
