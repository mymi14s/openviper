"""Echo AI provider — a zero-dependency mock for demonstration purposes.

This provider is intentionally simple: it has no external API dependencies and
works out of the box.  Use it to explore the openviper extension mechanism
without signing up for any third-party service.

Supported models
----------------
* ``echo-v1``   — returns the prompt prefixed with a label.
* ``reverse-v1`` — returns the reversed prompt text.

Registration
------------
Programmatic::

    from openviper.ai.registry import provider_registry
    from echo_provider.provider import EchoProvider

    provider_registry.register_provider(EchoProvider({
        "models": {"Echo v1": "echo-v1", "Reverse v1": "reverse-v1"},
    }))

Via module auto-discovery::

    provider_registry.register_from_module("echo_provider.provider")
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openviper.ai.extension import AIProvider


class EchoProvider(AIProvider):
    """Mock provider that echoes (or reverses) the input prompt.

    Config keys:
        models (dict): Display-name → model-ID mapping.

    Example settings::

        AI_PROVIDERS = {
            "echo": {
                "models": {
                    "Echo v1": "echo-v1",
                    "Reverse v1": "reverse-v1",
                },
            },
        }
    """

    name = "echo"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # No SDK / HTTP client needed — this is a local mock.

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Return the prompt, optionally reversed, based on the active model.

        Args:
            prompt: Input text.
            **kwargs: Accepts ``model`` to override the active model.

        Returns:
            Generated text string.
        """
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.default_model)

        if model == "reverse-v1":
            result = f"[EchoProvider/reverse] {prompt[::-1]}"
        else:
            result = f"[EchoProvider/echo] {prompt}"

        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream the response word-by-word to illustrate streaming support."""
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.default_model)

        if model == "reverse-v1":
            words = f"[EchoProvider/reverse] {prompt[::-1]}".split()
        else:
            words = f"[EchoProvider/echo] {prompt}".split()

        for word in words:
            yield word + " "


def get_providers() -> list[AIProvider]:
    """Return provider instances for auto-registration.

    Called by ``provider_registry.register_from_module()`` and the
    ``openviper.ai.providers`` entry-point mechanism.
    """
    config: dict[str, Any] = {
        "models": {
            "default": "echo-v1",
            "Echo v1": "echo-v1",
            "Reverse v1": "reverse-v1",
        },
    }
    return [EchoProvider(config)]
