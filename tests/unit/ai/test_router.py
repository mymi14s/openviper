"""Unit tests for openviper/ai/router.py — ModelRouter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.ai.registry import ProviderRegistry
from openviper.ai.router import ModelRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_with_provider(model_id: str = "test-model") -> tuple:
    """Return (registry, mock_provider) with model registered."""
    provider = MagicMock()
    provider.generate = AsyncMock(return_value="generated")
    provider.moderate = AsyncMock(return_value={"classification": "safe"})
    provider.embed = AsyncMock(return_value=[0.1, 0.2])
    provider.provider_name.return_value = "mock"
    provider.supported_models.return_value = [model_id]
    provider.default_model = model_id

    registry = ProviderRegistry()
    registry._loaded = True
    registry.register_provider(provider)
    return registry, provider


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------


class TestModelSelection:
    def test_set_and_get_model(self):
        registry, _ = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        router.set_model("test-model")
        assert router.get_model() == "test-model"

    def test_default_model(self):
        registry, _ = _make_registry_with_provider()
        router = ModelRouter(registry=registry, default_model="test-model")
        assert router.get_model() == "test-model"

    def test_no_model_set_returns_none(self):
        registry, _ = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        assert router.get_model() is None


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


class TestProviderResolution:
    def test_no_model_raises_runtime_error(self):
        registry, _ = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        with pytest.raises(RuntimeError, match="No model selected"):
            router._get_provider()

    def test_model_override(self):
        registry, provider = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        result = router._get_provider(model="test-model")
        assert result is provider

    def test_uses_active_model(self):
        registry, provider = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        router.set_model("test-model")
        result = router._get_provider()
        assert result is provider


# ---------------------------------------------------------------------------
# Inference delegation
# ---------------------------------------------------------------------------


class TestInferenceDelegation:
    @pytest.mark.asyncio
    async def test_generate(self):
        registry, provider = _make_registry_with_provider()
        router = ModelRouter(registry=registry, default_model="test-model")
        result = await router.generate("hello")
        assert result == "generated"
        provider.generate.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_generate_with_model_override(self):
        registry, provider = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        result = await router.generate("hello", model="test-model")
        assert result == "generated"

    @pytest.mark.asyncio
    async def test_moderate(self):
        registry, provider = _make_registry_with_provider()
        router = ModelRouter(registry=registry, default_model="test-model")
        result = await router.moderate("check this")
        assert result == {"classification": "safe"}
        provider.moderate.assert_awaited_once_with("check this")

    @pytest.mark.asyncio
    async def test_embed(self):
        registry, provider = _make_registry_with_provider()
        router = ModelRouter(registry=registry, default_model="test-model")
        result = await router.embed("hello")
        assert result == [0.1, 0.2]
        provider.embed.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_stream(self):
        registry, _ = _make_registry_with_provider()
        # Need a real async generator for stream
        provider = MagicMock()
        provider.provider_name.return_value = "mock"
        provider.supported_models.return_value = ["stream-model"]
        provider.default_model = "stream-model"

        async def mock_stream(prompt, **kw):
            yield "chunk1"
            yield "chunk2"

        provider.stream = mock_stream

        registry2 = ProviderRegistry()
        registry2._loaded = True
        registry2.register_provider(provider)

        router = ModelRouter(registry=registry2, default_model="stream-model")
        chunks = [c async for c in router.stream("hello")]
        assert chunks == ["chunk1", "chunk2"]


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


class TestConvenience:
    def test_list_models(self):
        registry, _ = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        assert "test-model" in router.list_models()

    def test_repr(self):
        registry, _ = _make_registry_with_provider()
        router = ModelRouter(registry=registry, default_model="gpt-4o")
        assert "gpt-4o" in repr(router)

    def test_repr_no_model(self):
        registry, _ = _make_registry_with_provider()
        router = ModelRouter(registry=registry)
        assert "None" in repr(router)
