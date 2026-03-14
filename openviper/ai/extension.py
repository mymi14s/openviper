"""Stable public API for third-party openviper AI provider authors.

Import everything you need from this single module.  The symbols exported
here follow semantic versioning — breaking changes will increment
``EXTENSION_API_VERSION``.

Quickstart::

    from openviper.ai.extension import (
        AIProvider,
        provider_registry,
        ModelCollisionError,
        EXTENSION_API_VERSION,
    )
    import asyncio
    from typing import Any


    class MyProvider(AIProvider):
        name = "my_provider"

        async def generate(self, prompt: str, **kwargs: Any) -> str:
            # Call your inference backend here
            return f"[MyProvider] {prompt}"


    def get_providers() -> list[AIProvider]:
        return [MyProvider({"models": {"My Model": "my-model-v1"}})]


    # Then register at app startup:
    #   provider_registry.register_from_module("mypackage.ai.my_provider")
    # Or via package entry-point in pyproject.toml:
    #   [project.entry-points."openviper.ai.providers"]
    #   my_provider = "mypackage.ai.my_provider:get_providers"


Versioning guarantee
--------------------
The :data:`EXTENSION_API_VERSION` constant is a ``(major, minor)`` tuple.

* **Minor** bumps add new optional methods / helpers without breaking
  existing providers.
* **Major** bumps indicate breaking interface changes; check the changelog.

Current version: ``(1, 0)``.
"""

from __future__ import annotations

#: Semantic version of the extension API as ``(major, minor)``.
#: Third-party packages may inspect this at import time to assert
#: compatibility::
#:
#:     from openviper.ai.extension import EXTENSION_API_VERSION
#:     assert EXTENSION_API_VERSION >= (1, 0), "openviper >= 1.0 required"
EXTENSION_API_VERSION: tuple[int, int] = (1, 0)

# Re-export everything a provider author needs — no internal imports required.
from openviper.ai.base import AIProvider  # noqa: E402
from openviper.ai.exceptions import (  # noqa: E402
    AIError,
    ModelCollisionError,
    ModelNotFoundError,
    ModelUnavailableError,
    ProviderNotAvailableError,
    ProviderNotConfiguredError,
)
from openviper.ai.registry import ProviderRegistry, provider_registry  # noqa: E402

__all__ = [
    # Version
    "EXTENSION_API_VERSION",
    # Core interface to implement
    "AIProvider",
    # Registry helpers
    "ProviderRegistry",
    "provider_registry",
    # Exceptions
    "AIError",
    "ModelCollisionError",
    "ModelNotFoundError",
    "ModelUnavailableError",
    "ProviderNotAvailableError",
    "ProviderNotConfiguredError",
]
