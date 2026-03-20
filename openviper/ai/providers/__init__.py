"""AI providers package.

Providers are lazily imported so that missing third-party SDKs
(``openai``, ``anthropic``, ``google-genai``) do not crash the
framework at import time.  Install the extras with::

    pip install openviper[ai]
"""

from __future__ import annotations

import importlib
from typing import Any

_PROVIDER_MAP: dict[str, str] = {
    "AnthropicProvider": "openviper.ai.providers.anthropic_provider",
    "GeminiProvider": "openviper.ai.providers.gemini_provider",
    "GrokProvider": "openviper.ai.providers.grok_provider",
    "OllamaProvider": "openviper.ai.providers.ollama_provider",
    "OpenAIProvider": "openviper.ai.providers.openai_provider",
}

__all__ = list(_PROVIDER_MAP)


def __getattr__(name: str) -> Any:
    if name in _PROVIDER_MAP:
        module = importlib.import_module(_PROVIDER_MAP[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
