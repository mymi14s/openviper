"""OpenViper AI integration package."""

from openviper.ai.base import AIProvider
from openviper.ai.devkit import (
    SimpleProvider,
    StreamingAdapter,
    map_http_error,
    normalize_response,
)
from openviper.ai.exceptions import (
    AIError,
    ModelCollisionError,
    ModelNotFoundError,
    ModelUnavailableError,
    ProviderNotAvailableError,
    ProviderNotConfiguredError,
)
from openviper.ai.extension import EXTENSION_API_VERSION
from openviper.ai.providers import (
    AnthropicProvider,
    GeminiProvider,
    GrokProvider,
    OllamaProvider,
    OpenAIProvider,
)
from openviper.ai.registry import ProviderRegistry, ai_registry, provider_registry
from openviper.ai.router import ModelRouter, model_router

__all__ = [
    # Base
    "AIProvider",
    # Extension API version
    "EXTENSION_API_VERSION",
    # Exceptions
    "AIError",
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
    # Providers
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
