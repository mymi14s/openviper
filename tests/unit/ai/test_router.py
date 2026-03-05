"""Tests for openviper/ai/router.py — ModelRouter."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from openviper.ai.registry import ProviderRegistry
from openviper.ai.router import ModelRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_router(model_id: str = "test-model") -> tuple[ModelRouter, MagicMock]:
    """Return a router wired to a fake provider."""
    provider = MagicMock()
    provider.generate = AsyncMock(return_value="generated text")
    provider.stream = AsyncMock()
    provider.moderate = AsyncMock(return_value={"is_safe": True})
    provider.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    registry = MagicMock(spec=ProviderRegistry)
    registry.get_by_model.return_value = provider
    registry.list_models.return_value = [model_id]

    router = ModelRouter(registry=registry, default_model=model_id)
    return router, provider


# ---------------------------------------------------------------------------
# set_model / get_model (lines 66-72)
# ---------------------------------------------------------------------------


def test_set_model_updates_active_model():
    """Line 66-67: set_model() changes the active model."""
    router, _ = _make_router()
    router.set_model("new-model")
    assert router.get_model() == "new-model"


def test_get_model_returns_none_when_unset():
    """get_model() returns None when no model has been selected."""
    registry = MagicMock(spec=ProviderRegistry)
    router = ModelRouter(registry=registry)
    assert router.get_model() is None


def test_set_model_is_thread_safe():
    router, _ = _make_router("initial")
    results = []
    barrier = threading.Barrier(5)

    def worker(model_name):
        barrier.wait()
        router.set_model(model_name)
        results.append(router.get_model())

    threads = [threading.Thread(target=worker, args=(f"model-{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All results should be valid model names
    assert all(r is not None for r in results)


def test_get_model_is_thread_safe():
    router, _ = _make_router("stable-model")
    results = []
    barrier = threading.Barrier(5)

    def worker():
        barrier.wait()
        results.append(router.get_model())

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r == "stable-model" for r in results)


# ---------------------------------------------------------------------------
# _get_provider (lines 93-102)
# ---------------------------------------------------------------------------


def test_get_provider_with_explicit_model():
    """Line 93-94: explicit model override bypasses active model."""
    router, provider = _make_router("default-model")
    router._get_provider(model="override-model")
    router._registry.get_by_model.assert_called_with("override-model")


def test_get_provider_uses_active_model_when_no_override():
    router, provider = _make_router("active-model")
    router._get_provider()
    router._registry.get_by_model.assert_called_with("active-model")


def test_get_provider_raises_runtime_error_when_no_model_set():
    registry = MagicMock(spec=ProviderRegistry)
    router = ModelRouter(registry=registry)  # no default_model
    with pytest.raises(RuntimeError, match="No model selected"):
        router._get_provider()


# ---------------------------------------------------------------------------
# generate (line 117)
# ---------------------------------------------------------------------------


def test_generate_delegates_to_provider():
    """Line 117: generate() calls provider.generate()."""
    router, provider = _make_router()

    async def _run():
        return await router.generate("Hello world")

    result = asyncio.run(_run())
    assert result == "generated text"
    provider.generate.assert_called_once_with("Hello world")


def test_generate_with_model_override():
    """generate() with model kwarg uses that model."""
    router, provider = _make_router()

    async def _run():
        return await router.generate("prompt", model="gpt-4o")

    asyncio.run(_run())
    router._registry.get_by_model.assert_called_with("gpt-4o")


# ---------------------------------------------------------------------------
# stream (lines 132-133)
# ---------------------------------------------------------------------------


def test_stream_yields_chunks_from_provider():
    provider = MagicMock()

    async def _fake_stream(prompt, **kw):
        for chunk in ["Hello", " world"]:
            yield chunk

    provider.stream = _fake_stream

    registry = MagicMock(spec=ProviderRegistry)
    registry.get_by_model.return_value = provider

    router = ModelRouter(registry=registry, default_model="test-model")

    async def _run():
        chunks = []
        async for chunk in router.stream("Hello world"):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(_run())
    assert result == ["Hello", " world"]


# ---------------------------------------------------------------------------
# moderate (line 148)
# ---------------------------------------------------------------------------


def test_moderate_delegates_to_provider():
    """Line 148: moderate() calls provider.moderate()."""
    router, provider = _make_router()

    async def _run():
        return await router.moderate("some content")

    result = asyncio.run(_run())
    assert result == {"is_safe": True}
    provider.moderate.assert_called_once_with("some content")


# ---------------------------------------------------------------------------
# embed (line 163)
# ---------------------------------------------------------------------------


def test_embed_delegates_to_provider():
    """Line 163: embed() calls provider.embed()."""
    router, provider = _make_router()

    async def _run():
        return await router.embed("some text")

    result = asyncio.run(_run())
    assert result == [0.1, 0.2, 0.3]
    provider.embed.assert_called_once_with("some text")


# ---------------------------------------------------------------------------
# list_models (line 169)
# ---------------------------------------------------------------------------


def test_list_models_delegates_to_registry():
    """Line 169: list_models() delegates to registry.list_models()."""
    router, _ = _make_router("my-model")
    models = router.list_models()
    assert "my-model" in models
    router._registry.list_models.assert_called_once()


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


def test_repr_shows_active_model():
    router, _ = _make_router("repr-model")
    assert "repr-model" in repr(router)


def test_repr_shows_none_when_no_model():
    registry = MagicMock(spec=ProviderRegistry)
    router = ModelRouter(registry=registry)
    assert "None" in repr(router)
