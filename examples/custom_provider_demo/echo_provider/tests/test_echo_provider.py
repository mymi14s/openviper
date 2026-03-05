"""Tests for the EchoProvider."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider():
    from echo_provider.provider import EchoProvider

    return EchoProvider(
        {
            "models": {
                "default": "echo-v1",
                "Echo v1": "echo-v1",
                "Reverse v1": "reverse-v1",
            },
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_provider_name(provider):
    assert provider.provider_name() == "echo"


def test_supported_models(provider):
    models = provider.supported_models()
    assert isinstance(models, list)
    assert "echo-v1" in models
    assert "reverse-v1" in models


@pytest.mark.asyncio
async def test_generate_echo(provider):
    result = await provider.generate("Hello, world!")
    assert "Hello, world!" in result
    assert "EchoProvider/echo" in result


@pytest.mark.asyncio
async def test_generate_reverse(provider):
    result = await provider.generate("Hello!", model="reverse-v1")
    assert "EchoProvider/reverse" in result
    # The reversed text of "Hello!" is "!olleH"
    assert "!olleH" in result


@pytest.mark.asyncio
async def test_stream(provider):
    chunks = []
    async for chunk in provider.stream("Hello!"):
        chunks.append(chunk)
    assert chunks
    assert all(isinstance(c, str) for c in chunks)
    full = "".join(chunks)
    assert "Hello!" in full


@pytest.mark.asyncio
async def test_stream_reverse(provider):
    chunks = []
    async for chunk in provider.stream("Hello!", model="reverse-v1"):
        chunks.append(chunk)
    full = "".join(chunks)
    assert "!olleH" in full


def test_get_providers():
    from echo_provider.provider import get_providers

    from openviper.ai.base import AIProvider

    providers = get_providers()
    assert providers
    assert all(isinstance(p, AIProvider) for p in providers)


def test_registration():
    """Verify the provider integrates correctly with ProviderRegistry."""
    from echo_provider.provider import EchoProvider

    from openviper.ai.registry import ProviderRegistry

    registry = ProviderRegistry()
    p = EchoProvider(
        {
            "models": {"default": "echo-v1", "Echo v1": "echo-v1"},
        }
    )
    registry.register_provider(p)

    assert "echo-v1" in registry.list_models()
    retrieved = registry.get_by_model("echo-v1")
    assert retrieved is p
