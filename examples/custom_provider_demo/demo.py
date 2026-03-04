"""custom_provider_demo — end-to-end demonstration of the openviper extension API.

Run this script from the examples/custom_provider_demo directory::

    python demo.py

What this demo shows
--------------------
1. **Programmatic registration** — register an EchoProvider instance directly.
2. **Module-based registration** — register via ``register_from_module()``.
3. **Runtime model switching** — swap models on a live ``ModelRouter``.
4. **Streaming** — iterate token-by-token over the provider's stream.
5. **Coexistence** — two providers share the same registry without conflict.
6. **Collision detection** — strict mode raises ``ModelCollisionError``.
"""

from __future__ import annotations

import asyncio
import os
import sys

# ---------------------------------------------------------------------------
# Make the demo directory importable as a package root so that
# ``echo_provider`` can be imported without installing it.
# ---------------------------------------------------------------------------
DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
if DEMO_DIR not in sys.path:
    sys.path.insert(0, DEMO_DIR)


# ---------------------------------------------------------------------------
# openviper bootstrap — use a minimal in-memory settings object so the demo
# works without a full openviper project.
# ---------------------------------------------------------------------------

import openviper

openviper.setup(
    {
        "INSTALLED_APPS": ["openviper.core"],
        "AI_PROVIDERS": {},  # We register manually below
        "DATABASE": {"default": {"ENGINE": "openviper.db.backends.sqlite", "NAME": ":memory:"}},
    }
)


# ---------------------------------------------------------------------------
# Imports (after setup)
# ---------------------------------------------------------------------------

from openviper.ai.exceptions import ModelCollisionError, ModelNotFoundError
from openviper.ai.registry import ProviderRegistry
from openviper.ai.router import ModelRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEP = "-" * 60


def section(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


async def main() -> None:
    # ── 1. Programmatic registration ────────────────────────────────────────
    section("1. Programmatic registration")

    from echo_provider.provider import EchoProvider

    registry = ProviderRegistry()

    echo = EchoProvider(
        {
            "models": {
                "default": "echo-v1",
                "Echo v1": "echo-v1",
                "Reverse v1": "reverse-v1",
            },
        }
    )
    registry.register_provider(echo)

    print(f"Registered models: {registry.list_models()}")
    print(f"Provider names:    {registry.list_provider_names()}")

    # ── 2. Module-based registration ────────────────────────────────────────
    section("2. Module-based registration (register_from_module)")

    registry2 = ProviderRegistry()
    count = registry2.register_from_module("echo_provider.provider")
    print(f"Loaded {count} provider(s) from module.")
    print(f"Registered models: {registry2.list_models()}")

    # ── 3. Runtime model switching ───────────────────────────────────────────
    section("3. Runtime model switching via ModelRouter")

    router = ModelRouter(registry=registry, default_model="echo-v1")

    prompt = "The quick brown fox jumps over the lazy dog."

    router.set_model("echo-v1")
    result = await router.generate(prompt)
    print(f"[echo-v1]   {result}")

    router.set_model("reverse-v1")
    result = await router.generate(prompt)
    print(f"[reverse-v1] {result}")

    # ── 4. Streaming ────────────────────────────────────────────────────────
    section("4. Streaming tokens")

    router.set_model("echo-v1")
    print("Stream output: ", end="", flush=True)
    async for token in await router.stream("Stream this sentence!"):
        print(token, end="", flush=True)
    print()  # newline after stream

    # ── 5. Coexistence with a second provider ────────────────────────────────
    section("5. Coexistence — two providers, same registry")

    # Register a second mock provider with different models
    from openviper.ai.devkit import SimpleProvider

    class UpperProvider(SimpleProvider):
        """Toy provider that returns the prompt in upper-case."""

        name = "upper"

        async def generate(self, prompt: str, **kwargs):  # type: ignore[override]
            prompt, kwargs = await self.before_inference(prompt, kwargs)
            result = f"[UpperProvider] {prompt.upper()}"
            return await self.after_inference(prompt, result)

    upper = UpperProvider(
        {
            "models": {"default": "upper-v1", "Upper v1": "upper-v1"},
        }
    )
    registry.register_provider(upper)

    print(f"Models after second provider: {registry.list_models()}")
    print(f"Providers: {registry.list_provider_names()}")

    router.set_model("upper-v1")
    result = await router.generate("hello from upper provider")
    print(f"[upper-v1]  {result}")

    # Switch back to echo
    router.set_model("echo-v1")
    result = await router.generate("back to echo")
    print(f"[echo-v1]   {result}")

    # ── 6. Collision detection ───────────────────────────────────────────────
    section("6. Collision detection (strict mode)")

    duplicate = EchoProvider(
        {
            "models": {
                "default": "echo-v1",  # same model ID as the first EchoProvider
            },
        }
    )

    # Default allow_override=True → logs warning, silently replaces
    registry.register_provider(duplicate, allow_override=True)
    print("allow_override=True: override succeeded (warning logged).")

    # Strict mode → raises ModelCollisionError
    try:
        registry.register_provider(duplicate, allow_override=False)
    except ModelCollisionError as exc:
        print(f"allow_override=False: caught ModelCollisionError — {exc}")

    # ── 7. ModelNotFoundError ────────────────────────────────────────────────
    section("7. Looking up an unregistered model")

    try:
        registry.get_by_model("gpt-99-ultra")
    except ModelNotFoundError as exc:
        print(f"ModelNotFoundError — {exc}")

    section("Done")
    print("All demonstrations completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
