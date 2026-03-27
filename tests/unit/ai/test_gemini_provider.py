"""Unit tests for GeminiProvider.

All google-genai interactions are faked to avoid requiring the real SDK or
network access.
"""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

import openviper.ai.providers.gemini_provider as gemini_provider


class _FakeChunk:
    def __init__(self, text: str | None):
        self.text = text


class _FakeResponse:
    def __init__(self, text: str | None):
        self.text = text


class _FakeEmbedding:
    def __init__(self, values: list[float]):
        self.values = values


class _FakeEmbedResponse:
    def __init__(self, values: list[float]):
        self.embeddings = [_FakeEmbedding(values)]


class _FakeAioModels:
    def __init__(self) -> None:
        self.generate_content = AsyncMock(return_value=_FakeResponse("ok"))
        self.embed_content = AsyncMock(return_value=_FakeEmbedResponse([0.1, 0.2]))

    async def generate_content_stream(self, **_kwargs) -> AsyncIterator[_FakeChunk]:
        yield _FakeChunk("a")
        yield _FakeChunk(None)
        yield _FakeChunk("b")


class _FakeClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.aio = types.SimpleNamespace(models=_FakeAioModels())


class _FakeTypes:
    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class EmbedContentConfig:
        def __init__(self, task_type: str):
            self.task_type = task_type

    class Part:
        @staticmethod
        def from_bytes(*, data: bytes, mime_type: str):
            return ("bytes", data, mime_type)

        @staticmethod
        def from_uri(*, file_uri: str, mime_type: str):
            return ("uri", file_uri, mime_type)


def _install_fake_google_modules() -> None:
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")

    genai.Client = _FakeClient
    types_mod.GenerateContentConfig = _FakeTypes.GenerateContentConfig
    types_mod.EmbedContentConfig = _FakeTypes.EmbedContentConfig
    types_mod.Part = _FakeTypes.Part

    genai.types = types_mod
    google.genai = genai

    sys.modules["google"] = google
    sys.modules["google.genai"] = genai
    sys.modules["google.genai.types"] = types_mod


class TestGeminiProviderInit:
    def test_missing_api_key_raises(self) -> None:
        with pytest.raises(gemini_provider.GeminiAuthError):
            gemini_provider.GeminiProvider({"model": "gemini-1.5-flash"})

    def test_missing_sdk_raises_helpful_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
        monkeypatch.delitem(sys.modules, "google.genai", raising=False)
        monkeypatch.delitem(sys.modules, "google.genai.types", raising=False)

        with pytest.raises(ImportError, match="google-genai"):
            gemini_provider.GeminiProvider({"model": "gemini-1.5-flash", "api_key": "k"})


class TestGeminiProviderGenerateAndStream:
    @pytest.fixture
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> gemini_provider.GeminiProvider:
        _install_fake_google_modules()
        return gemini_provider.GeminiProvider({"model": "gemini-1.5-flash", "api_key": "k"})

    @pytest.mark.asyncio
    async def test_generate_uses_max_tokens_alias(
        self, provider: gemini_provider.GeminiProvider
    ) -> None:
        result = await provider.generate(
            "hi",
            max_tokens=123,
            temperature=0.2,
            candidate_count=1,
        )
        assert result == "ok"

        client = provider._get_client()
        called_cfg = client.aio.models.generate_content.call_args.kwargs["config"]
        assert called_cfg.kwargs["max_output_tokens"] == 123
        assert called_cfg.kwargs["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_generate_wraps_unknown_errors(
        self, provider: gemini_provider.GeminiProvider
    ) -> None:
        client = provider._get_client()
        client.aio.models.generate_content.side_effect = RuntimeError("quota exceeded 429")

        with pytest.raises(gemini_provider.GeminiRateLimitError):
            await provider.generate("hi")

        client.aio.models.generate_content.side_effect = RuntimeError("API_KEY_INVALID")
        with pytest.raises(gemini_provider.GeminiAuthError):
            await provider.generate("hi")

        client.aio.models.generate_content.side_effect = RuntimeError("some detailed message")
        with pytest.raises(gemini_provider.GeminiError, match="Gemini API error"):
            await provider.generate("hi")

    @pytest.mark.asyncio
    async def test_stream_yields_only_text_chunks(
        self, provider: gemini_provider.GeminiProvider
    ) -> None:
        chunks = [c async for c in provider.stream("hi")]
        assert chunks == ["a", "b"]

    @pytest.mark.asyncio
    async def test_embed_returns_embedding_values(
        self, provider: gemini_provider.GeminiProvider
    ) -> None:
        values = await provider.embed("hello")
        assert values == [0.1, 0.2]

    def test_cost_estimation_unknown_model_falls_back(
        self, provider: gemini_provider.GeminiProvider
    ) -> None:
        cost = provider.estimate_cost(1_000_000, 2_000_000, model="unknown")
        assert cost["total_cost"] > 0
