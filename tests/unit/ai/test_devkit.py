"""Unit tests for openviper/ai/devkit.py — SimpleProvider, StreamingAdapter, helpers."""

from __future__ import annotations

import pytest

from openviper.ai.devkit import (
    SimpleProvider,
    StreamingAdapter,
    map_http_error,
    normalize_response,
)
from openviper.ai.exceptions import (
    AIError,
    ModelUnavailableError,
    ProviderNotAvailableError,
)

# ---------------------------------------------------------------------------
# SimpleProvider
# ---------------------------------------------------------------------------


class ConcreteSimple(SimpleProvider):
    name = "concrete"

    async def generate(self, prompt: str, **kwargs) -> str:
        return f"echo: {prompt}"


class TestSimpleProvider:
    def test_provider_name_uses_class_attribute(self):
        p = ConcreteSimple({})
        assert p.provider_name() == "concrete"

    def test_provider_name_uses_instance_override(self):
        p = ConcreteSimple({}, name="custom")
        assert p.provider_name() == "custom"

    def test_provider_name_without_override_uses_class_attr(self):
        p = ConcreteSimple({})
        assert not hasattr(p, "_instance_name")
        assert p.provider_name() == "concrete"

    @pytest.mark.asyncio
    async def test_generate_works(self):
        p = ConcreteSimple({})
        result = await p.generate("hello")
        assert result == "echo: hello"

    def test_config_passthrough(self):
        p = ConcreteSimple({"model": "test-model"})
        assert p.default_model == "test-model"


# ---------------------------------------------------------------------------
# normalize_response
# ---------------------------------------------------------------------------


class TestNormalizeResponse:
    def test_strips_whitespace(self):
        assert normalize_response("  hello  ") == "hello"

    def test_collapses_triple_newlines(self):
        result = normalize_response("a\n\n\nb")
        assert result == "a\n\nb"

    def test_preserves_double_newlines(self):
        result = normalize_response("a\n\nb")
        assert result == "a\n\nb"

    def test_collapses_many_newlines(self):
        result = normalize_response("a\n\n\n\n\n\nb")
        assert result == "a\n\nb"

    def test_empty_string(self):
        assert normalize_response("") == ""

    def test_single_newline_preserved(self):
        assert normalize_response("a\nb") == "a\nb"


# ---------------------------------------------------------------------------
# StreamingAdapter
# ---------------------------------------------------------------------------


class TestStreamingAdapter:
    @pytest.mark.asyncio
    async def test_wraps_sync_generator(self):
        def gen():
            yield "hello "
            yield "world"

        chunks = [c async for c in StreamingAdapter(gen())]
        assert chunks == ["hello ", "world"]

    @pytest.mark.asyncio
    async def test_wraps_callable(self):
        def gen_factory():
            def gen():
                yield "a"
                yield "b"

            return gen()

        chunks = [c async for c in StreamingAdapter(gen_factory)]
        assert chunks == ["a", "b"]

    @pytest.mark.asyncio
    async def test_empty_generator(self):
        def gen():
            return
            yield  # noqa: unreachable

        chunks = [c async for c in StreamingAdapter(gen())]
        assert chunks == []


# ---------------------------------------------------------------------------
# map_http_error
# ---------------------------------------------------------------------------


class TestMapHttpError:
    def test_401_returns_provider_not_available(self):
        err = map_http_error(401, "bad key", provider="openai")
        assert isinstance(err, ProviderNotAvailableError)
        assert "Auth failed" in err.reason

    def test_403_returns_provider_not_available(self):
        err = map_http_error(403, "forbidden", provider="openai")
        assert isinstance(err, ProviderNotAvailableError)
        assert "Auth failed" in err.reason

    def test_429_returns_rate_limit(self):
        err = map_http_error(429, "too many requests", provider="openai")
        assert isinstance(err, ProviderNotAvailableError)
        assert "Rate limit" in err.reason

    def test_404_with_model_returns_model_unavailable(self):
        err = map_http_error(404, "not found", provider="openai", model="gpt-5")
        assert isinstance(err, ModelUnavailableError)
        assert err.model == "gpt-5"
        assert err.provider == "openai"

    def test_404_without_model_returns_generic_error(self):
        err = map_http_error(404, "not found", provider="openai")
        assert isinstance(err, AIError)
        assert not isinstance(err, ModelUnavailableError)

    def test_500_returns_server_error(self):
        err = map_http_error(500, "internal", provider="ollama")
        assert isinstance(err, ProviderNotAvailableError)
        assert "Server error" in err.reason

    def test_502_returns_server_error(self):
        err = map_http_error(502, "bad gateway", provider="ollama")
        assert isinstance(err, ProviderNotAvailableError)

    def test_unknown_status_returns_generic_ai_error(self):
        err = map_http_error(418, "teapot", provider="custom")
        assert isinstance(err, AIError)
        assert "418" in str(err)

    def test_empty_detail_uses_http_code(self):
        err = map_http_error(500, provider="test")
        assert isinstance(err, ProviderNotAvailableError)
        assert "HTTP 500" in err.reason
