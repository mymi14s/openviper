"""create_provider management command — scaffold a new AI provider."""

from __future__ import annotations

import argparse
import os

from openviper.core.management.base import BaseCommand, CommandError

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_PROVIDER_TEMPLATE = '''\
"""{{ provider_title }} AI provider."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openviper.ai.extension import AIProvider


class {{ class_name }}(AIProvider):
    """{{ provider_title }} provider.

    Config keys:
        api_key (str): API key (falls back to {{ env_var }} env var).
        models (dict): Display-name → model-ID mapping.

    Example settings::

        AI_PROVIDERS = {
            "{{ provider_name }}": {
                "api_key": os.environ.get("{{ env_var }}"),
                "models": {
                    "default": "{{ provider_name }}-v1",
                    "{{ provider_title }} v1": "{{ provider_name }}-v1",
                },
            },
        }
    """

    name = "{{ provider_name }}"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        import os
        self._api_key: str = config.get("api_key") or os.environ.get("{{ env_var }}") or ""
        # TODO: initialise your SDK / HTTP client here

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Call the {{ provider_title }} API and return generated text.

        Args:
            prompt: Input text.
            **kwargs: Provider-specific options (model, temperature, …).

        Returns:
            Generated text string.
        """
        prompt, kwargs = await self.before_inference(prompt, kwargs)
        model = kwargs.pop("model", self.default_model)

        # TODO: Replace with real API call
        result = f"[{{ class_name }}] model={model!r}  prompt={prompt[:80]!r}"

        return await self.after_inference(prompt, result)

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream tokens from the {{ provider_title }} API.

        Default falls back to a single-chunk yield from generate().
        Override for real streaming.
        """
        result = await self.generate(prompt, **kwargs)
        yield result


def get_providers() -> list[AIProvider]:
    """Return provider instances for auto-registration.

    Called by ``provider_registry.register_from_module()`` and the
    ``openviper.ai.providers`` entry-point mechanism.
    """
    import os

    config: dict[str, Any] = {
        "api_key": os.environ.get("{{ env_var }}"),
        "models": {
            "default": "{{ provider_name }}-v1",
            "{{ provider_title }} v1": "{{ provider_name }}-v1",
        },
    }
    return [{{ class_name }}(config)]
'''

_TEST_TEMPLATE = '''\
"""Tests for {{ provider_title }} provider."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider():
    from {{ module_import }} import {{ class_name }}

    return {{ class_name }}({
        "api_key": "test-key",
        "models": {
            "default": "{{ provider_name }}-v1",
            "{{ provider_title }} v1": "{{ provider_name }}-v1",
        },
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_provider_name(provider):
    assert provider.provider_name() == "{{ provider_name }}"


def test_supported_models(provider):
    models = provider.supported_models()
    assert isinstance(models, list)
    assert "{{ provider_name }}-v1" in models


@pytest.mark.asyncio
async def test_generate(provider):
    result = await provider.generate("Hello, world!")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_stream(provider):
    chunks = []
    async for chunk in provider.stream("Hello!"):
        chunks.append(chunk)
    assert chunks
    assert all(isinstance(c, str) for c in chunks)


def test_get_providers():
    from {{ module_import }} import get_providers

    providers = get_providers()
    assert providers
    from openviper.ai.base import AIProvider
    assert all(isinstance(p, AIProvider) for p in providers)
'''

_INIT_TEMPLATE = '''\
"""{{ provider_title }} provider package."""

from .provider import {{ class_name }}, get_providers

__all__ = ["{{ class_name }}", "get_providers"]
'''

_README_TEMPLATE = """\
# {{ provider_title }} Provider

A custom AI provider for [openviper](https://github.com/anthropics/openviper).

## Installation

```bash
pip install -e .
```

## Configuration

Add to your project\'s `settings.py`:

```python
import os

AI_PROVIDERS = {
    "{{ provider_name }}": {
        "api_key": os.environ.get("{{ env_var }}"),
        "models": {
            "default": "{{ provider_name }}-v1",
            "{{ provider_title }} v1": "{{ provider_name }}-v1",
        },
    },
}
```

Set the API key environment variable:

```bash
export {{ env_var }}=your-api-key-here
```

## Usage

```python
from openviper.ai.router import model_router

model_router.set_model("{{ provider_name }}-v1")
result = await model_router.generate("Hello, world!")
print(result)
```

## Registration (without settings)

```python
from openviper.ai.registry import provider_registry

# From this module
provider_registry.register_from_module("{{ pkg_name }}.provider")

# Or programmatically:
from {{ pkg_name }}.provider import {{ class_name }}
provider_registry.register_provider(
    {{ class_name }}({"models": {"default": "{{ provider_name }}-v1"}}))
```

## Publishing as a reusable package

Add to your `pyproject.toml` to enable auto-discovery:

```toml
[project.entry-points."openviper.ai.providers"]
{{ provider_name }} = "{{ pkg_name }}.provider:get_providers"
```

Then any project that installs your package and calls:

```python
provider_registry.discover_entrypoints()
```

will automatically register your provider.
"""


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def _to_class_name(name: str) -> str:
    """Convert snake_case / kebab-case to PascalCase with 'Provider' suffix."""
    return "".join(part.capitalize() for part in name.replace("-", "_").split("_")) + "Provider"


def _to_env_var(name: str) -> str:
    return name.upper().replace("-", "_") + "_API_KEY"


def _render(template: str, ctx: dict[str, str]) -> str:
    result = template
    for k, v in ctx.items():
        result = result.replace("{{ " + k + " }}", v)
    return result


class Command(BaseCommand):
    help = "Scaffold a new custom AI provider package."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "name",
            help=(
                "Provider name in snake_case (e.g. my_provider). "
                "Used as the package directory name."
            ),
        )
        parser.add_argument(
            "--output-dir",
            "-o",
            default=None,
            help="Directory to create the provider package in (default: cwd).",
        )

    def handle(self, **options):  # type: ignore[override]
        name: str = options["name"].replace("-", "_")
        if not name.isidentifier():
            raise CommandError(f"'{name}' is not a valid Python identifier after normalisation.")

        base_dir = os.path.realpath(options.get("output_dir") or os.getcwd())
        pkg_dir = os.path.join(base_dir, name)

        if os.path.exists(pkg_dir):
            raise CommandError(
                f"Directory '{pkg_dir}' already exists.  "
                "Choose a different name or --output-dir."
            )

        class_name = _to_class_name(name)
        env_var = _to_env_var(name)
        title = " ".join(part.capitalize() for part in name.split("_"))

        ctx = {
            "provider_name": name,
            "provider_title": title,
            "class_name": class_name,
            "env_var": env_var,
            "pkg_name": name,
            "module_import": f"{name}.provider",
        }

        # Create package directory
        tests_dir = os.path.join(pkg_dir, "tests")
        os.makedirs(tests_dir, exist_ok=True)

        files = {
            os.path.join(pkg_dir, "__init__.py"): _render(_INIT_TEMPLATE, ctx),
            os.path.join(pkg_dir, "provider.py"): _render(_PROVIDER_TEMPLATE, ctx),
            os.path.join(tests_dir, "__init__.py"): "",
            os.path.join(tests_dir, f"test_{name}.py"): _render(_TEST_TEMPLATE, ctx),
            os.path.join(pkg_dir, "README.md"): _render(_README_TEMPLATE, ctx),
        }

        for filepath, content in files.items():
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content)

        self.stdout(self.style_success(f"Created provider package '{name}' at {pkg_dir}"))
        self.stdout("")
        self.stdout(self.style_notice("Next steps:"))
        self.stdout(f"  1. Implement generate() in {os.path.join(name, 'provider.py')}")
        self.stdout(f"  2. Set {env_var}=<your-key> in your environment")
        self.stdout(f"  3. Add '{name}' to settings.AI_PROVIDERS  (see {name}/README.md)")
        self.stdout(f"  4. Run tests: pytest {name}/tests/")
        self.stdout("")
        self.stdout(
            self.style_dim(
                "  Or register without settings:\n"
                f"    from openviper.ai.registry import provider_registry\n"
                f"    provider_registry.register_from_module('{name}.provider')"
            )
        )
