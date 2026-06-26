"""AI providers package (lazy-loaded)."""

from __future__ import annotations

import importlib

PROVIDER_MAP: dict[str, str] = {
    "AnthropicProvider": "openviper.ai.providers.anthropic_provider",
    "GeminiProvider": "openviper.ai.providers.gemini_provider",
    "GrokProvider": "openviper.ai.providers.grok_provider",
    "OllamaProvider": "openviper.ai.providers.ollama_provider",
    "OpenAIProvider": "openviper.ai.providers.openai_provider",
}

PROVIDER_TYPE_MAP: dict[str, str] = {
    "openai": "openviper.ai.providers.openai_provider.OpenAIProvider",
    "anthropic": "openviper.ai.providers.anthropic_provider.AnthropicProvider",
    "ollama": "openviper.ai.providers.ollama_provider.OllamaProvider",
    "gemini": "openviper.ai.providers.gemini_provider.GeminiProvider",
    "grok": "openviper.ai.providers.grok_provider.GrokProvider",
}

__all__ = list(PROVIDER_MAP)


def __getattr__(name: str) -> type:
    if name in PROVIDER_MAP:
        module = importlib.import_module(PROVIDER_MAP[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
