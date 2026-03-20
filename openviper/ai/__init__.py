"""OpenViper AI integration package.

Provider classes are lazily re-exported from ``openviper.ai.providers``
so that missing third-party SDKs do not prevent the rest of the
package from being imported.  Install the extras with::

    pip install openviper[ai]
"""

from __future__ import annotations

import importlib
from typing import Any

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
from openviper.ai.registry import ProviderRegistry, ai_registry, provider_registry
from openviper.ai.router import ModelRouter, model_router

_LAZY_PROVIDERS: dict[str, str] = {
    "AnthropicProvider": "openviper.ai.providers.anthropic_provider",
    "GeminiProvider": "openviper.ai.providers.gemini_provider",
    "GrokProvider": "openviper.ai.providers.grok_provider",
    "OllamaProvider": "openviper.ai.providers.ollama_provider",
    "OpenAIProvider": "openviper.ai.providers.openai_provider",
}

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


def __getattr__(name: str) -> Any:
    if name in _LAZY_PROVIDERS:
        module = importlib.import_module(_LAZY_PROVIDERS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
