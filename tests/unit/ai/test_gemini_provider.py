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
from openviper.ai.provider_utils import estimate_cost


class FakeChunk:
    def __init__(self, text: str | None):
        self.text = text


class FakeResponse:
    def __init__(self, text: str | None):
        self.text = text


class FakeEmbedding:
    def __init__(self, values: list[float]):
        self.values = values


class FakeEmbedResponse:
    def __init__(self, values: list[float]):
        self.embeddings = [FakeEmbedding(values)]


class FakeAioModels:
    def __init__(self) -> None:
        self.generate_content = AsyncMock(return_value=FakeResponse("ok"))
        self.embed_content = AsyncMock(return_value=FakeEmbedResponse([0.1, 0.2]))

    async def generate_content_stream(self, **_kwargs) -> AsyncIterator[FakeChunk]:
        yield FakeChunk("a")
        yield FakeChunk(None)
        yield FakeChunk("b")


class FakeClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.aio = types.SimpleNamespace(models=FakeAioModels())


class FakeTypes:
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


def install_fake_google_modules(monkeypatch: pytest.MonkeyPatch | None = None) -> None:
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")

    genai.Client = FakeClient
    types_mod.GenerateContentConfig = FakeTypes.GenerateContentConfig
    types_mod.EmbedContentConfig = FakeTypes.EmbedContentConfig
    types_mod.Part = FakeTypes.Part

    genai.types = types_mod
    google.genai = genai

    if monkeypatch is not None:
        monkeypatch.setitem(sys.modules, "google", google)
        monkeypatch.setitem(sys.modules, "google.genai", genai)
        monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    else:
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
        monkeypatch.setattr(gemini_provider, "google_genai", None)
        monkeypatch.setattr(gemini_provider, "google_genai_types", None)

        with pytest.raises(ImportError, match="google-genai"):
            gemini_provider.GeminiProvider({"model": "gemini-1.5-flash", "api_key": "k"})


class TestGeminiProviderGenerateAndStream:
    @pytest.fixture
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> gemini_provider.GeminiProvider:
        install_fake_google_modules(monkeypatch)
        monkeypatch.setattr(gemini_provider, "google_genai", sys.modules["google.genai"])
        monkeypatch.setattr(
            gemini_provider, "google_genai_types", sys.modules["google.genai.types"]
        )
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

        client = provider.get_client()
        called_cfg = client.aio.models.generate_content.call_args.kwargs["config"]
        assert called_cfg.kwargs["max_output_tokens"] == 123
        assert called_cfg.kwargs["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_generate_wraps_unknown_errors(
        self, provider: gemini_provider.GeminiProvider
    ) -> None:
        client = provider.get_client()
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
        cost = estimate_cost(
            1_000_000,
            2_000_000,
            gemini_provider.COST_TABLE,
            model="unknown",
            fallback_model="gemini-1.5-flash",
        )
        assert cost["total_cost"] > 0
