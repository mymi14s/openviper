"""Unit tests for GeminiProvider."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import openviper.ai.providers.gemini_provider as gmod
from openviper.ai.providers.gemini_provider import (
    GeminiAuthError,
    GeminiError,
    GeminiProvider,
    GeminiRateLimitError,
)

# ---------------------------------------------------------------------------
# Helpers: build a mock google-genai environment and a provider instance
# ---------------------------------------------------------------------------


def _make_google_mocks() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (mock_google_module, mock_genai, mock_types)."""
    mock_types = MagicMock()
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    return mock_google, mock_genai, mock_types


def _make_provider(config: dict[str, Any] | None = None):
    """Instantiate GeminiProvider with google SDK mocked."""
    mock_google, mock_genai, mock_types = _make_google_mocks()
    extra = {
        "api_key": "test-key",
        "model": "gemini-1.5-flash",
        "temperature": 1.0,
        "max_output_tokens": 2048,
        "candidate_count": 1,
        "embed_model": "models/text-embedding-004",
    }
    if config:
        extra.update(config)

    with patch.dict(
        sys.modules,
        {
            "google": mock_google,
            "google.genai": mock_genai,
            "google.genai.types": mock_types,
        },
    ):
        provider = GeminiProvider(extra)

    # After __init__, the module globals genai/types are set. Override them so
    # method calls later in tests use our mocks.
    # test internal fallback

    gmod.genai = mock_genai
    gmod.types = mock_types

    return provider, mock_genai, mock_types


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestGeminiProviderInit:
    def test_init_with_apk_key_in_config(self):
        provider, _, _ = _make_provider({"api_key": "my-key"})
        assert provider._api_key == "my-key"

    def test_init_falls_back_to_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        mock_google, mock_genai, mock_types = _make_google_mocks()
        with patch.dict(
            sys.modules,
            {
                "google": mock_google,
                "google.genai": mock_genai,
                "google.genai.types": mock_types,
            },
        ):
            with monkeypatch.context():
                provider = GeminiProvider({})  # no api_key in config
        assert provider._api_key == "env-key"

    def test_init_raises_auth_error_when_no_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_google, mock_genai, mock_types = _make_google_mocks()
        with patch.dict(
            sys.modules,
            {
                "google": mock_google,
                "google.genai": mock_genai,
                "google.genai.types": mock_types,
            },
        ):
            with monkeypatch.context():
                with pytest.raises(GeminiAuthError, match="Gemini API key is required"):
                    GeminiProvider({})

    def test_init_default_model(self):
        provider, _, _ = _make_provider()
        assert provider._default_model == "gemini-1.5-flash"

    def test_init_custom_model(self):
        provider, _, _ = _make_provider({"model": "gemini-2.0-flash"})
        assert provider._default_model == "gemini-2.0-flash"

    def test_init_client_is_none_after_init(self):
        provider, _, _ = _make_provider()
        # _client is initially None (lazy init)
        assert provider._client is None


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    def test_get_client_creates_client_lazily(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        client = provider._get_client()

        mock_genai.Client.assert_called_once_with(api_key="test-key")
        assert client is mock_client

    def test_get_client_caches_client(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        c1 = provider._get_client()
        c2 = provider._get_client()

        assert c1 is c2
        # Client constructor called only once
        mock_genai.Client.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_client_refreshes_on_new_event_loop(self):
        """When called inside an event loop, the client is created fresh."""
        provider, mock_genai, _ = _make_provider()
        mock_client1 = MagicMock(name="client1")
        mock_client2 = MagicMock(name="client2")
        mock_genai.Client.side_effect = [mock_client1, mock_client2]

        # First call: no client yet → create one
        c1 = provider._get_client()
        assert c1 is mock_client1

        # Simulate a loop change by resetting _client_loop to force recreation
        provider._client_loop = None
        c2 = provider._get_client()
        assert c2 is mock_client2


# ---------------------------------------------------------------------------
# _make_config
# ---------------------------------------------------------------------------


class TestMakeConfig:
    def test_make_config_defaults(self):
        provider, _, mock_types = _make_provider()
        provider._make_config({})
        mock_types.GenerateContentConfig.assert_called_once()
        call_kwargs = mock_types.GenerateContentConfig.call_args[1]
        assert call_kwargs["temperature"] == 1.0
        assert call_kwargs["max_output_tokens"] == 2048
        assert call_kwargs["candidate_count"] == 1

    def test_make_config_reads_from_config(self):
        provider, _, mock_types = _make_provider(
            {
                "temperature": 0.5,
                "max_output_tokens": 512,
                "top_p": 0.9,
                "top_k": 40,
            }
        )
        provider._make_config({})
        call_kwargs = mock_types.GenerateContentConfig.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_output_tokens"] == 512
        assert call_kwargs["top_p"] == 0.9
        assert call_kwargs["top_k"] == 40

    def test_make_config_overrides_take_precedence(self):
        provider, _, mock_types = _make_provider()
        provider._make_config({"temperature": 0.1})
        call_kwargs = mock_types.GenerateContentConfig.call_args[1]
        assert call_kwargs["temperature"] == 0.1


# ---------------------------------------------------------------------------
# _build_contents
# ---------------------------------------------------------------------------


class TestBuildContents:
    def test_build_contents_text_only(self):
        _, _, mock_types = _make_provider()
        contents = GeminiProvider._build_contents("hello")
        assert contents == ["hello"]

    def test_build_contents_with_data_image(self):
        _, _, mock_types = _make_provider()
        raw = b"\xff\xd8\xff"
        contents = GeminiProvider._build_contents(
            "describe", images=[{"data": raw, "mime_type": "image/jpeg"}]
        )
        assert len(contents) == 2
        assert contents[0] == "describe"
        mock_types.Part.from_bytes.assert_called_once_with(data=raw, mime_type="image/jpeg")

    def test_build_contents_with_url_image(self):
        _, _, mock_types = _make_provider()
        contents = GeminiProvider._build_contents(
            "describe",
            images=[{"url": "https://img.example.com/photo.jpg", "mime_type": "image/jpeg"}],
        )
        assert len(contents) == 2
        mock_types.Part.from_uri.assert_called_once_with(
            file_uri="https://img.example.com/photo.jpg", mime_type="image/jpeg"
        )

    def test_build_contents_defaults_mime_type(self):
        _, _, mock_types = _make_provider()
        # No mime_type in image dict; should default to image/jpeg
        GeminiProvider._build_contents("x", images=[{"data": b"bytes"}])
        mock_types.Part.from_bytes.assert_called_once_with(data=b"bytes", mime_type="image/jpeg")


# ---------------------------------------------------------------------------
# _wrap_error
# ---------------------------------------------------------------------------


class TestWrapError:
    def _get_wrap_error(self):
        return (
            GeminiProvider._wrap_error,
            GeminiAuthError,
            GeminiRateLimitError,
            GeminiError,
        )

    def test_wrap_error_api_key_invalid(self):
        wrap, GeminiAuthError, _, _ = self._get_wrap_error()
        err = wrap(Exception("API_KEY_INVALID detected"))
        assert isinstance(err, GeminiAuthError)

    def test_wrap_error_401(self):
        wrap, GeminiAuthError, _, _ = self._get_wrap_error()
        err = wrap(Exception("HTTP 401 Unauthorized"))
        assert isinstance(err, GeminiAuthError)

    def test_wrap_error_403(self):
        wrap, GeminiAuthError, _, _ = self._get_wrap_error()
        err = wrap(Exception("403 Forbidden"))
        assert isinstance(err, GeminiAuthError)

    def test_wrap_error_rate_limit_429(self):
        wrap, _, GeminiRateLimitError, _ = self._get_wrap_error()
        err = wrap(Exception("429 Too Many"))
        assert isinstance(err, GeminiRateLimitError)

    def test_wrap_error_resource_exhausted(self):
        wrap, _, GeminiRateLimitError, _ = self._get_wrap_error()
        err = wrap(Exception("RESOURCE_EXHAUSTED quota exceeded"))
        assert isinstance(err, GeminiRateLimitError)

    def test_wrap_error_quota_lowercase(self):
        wrap, _, GeminiRateLimitError, _ = self._get_wrap_error()
        err = wrap(Exception("quota limit reached"))
        assert isinstance(err, GeminiRateLimitError)

    def test_wrap_error_generic(self):
        wrap, _, _, GeminiError = self._get_wrap_error()
        err = wrap(Exception("Something else went wrong"))
        assert isinstance(err, GeminiError)
        assert "Gemini API error" in str(err)


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        provider, mock_genai, mock_types = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "Paris"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await provider.complete("What is the capital of France?")

        assert result == "Paris"
        mock_client.aio.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_uses_default_model(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "result"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        await provider.complete("test")

        call_kwargs = mock_client.aio.models.generate_content.call_args[1]
        assert call_kwargs["model"] == "gemini-1.5-flash"

    @pytest.mark.asyncio
    async def test_complete_overrides_model(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "result"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        await provider.complete("test", model="gemini-2.0-flash")

        call_kwargs = mock_client.aio.models.generate_content.call_args[1]
        assert call_kwargs["model"] == "gemini-2.0-flash"

    @pytest.mark.asyncio
    async def test_complete_handles_none_text(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await provider.complete("test")
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_wraps_auth_error(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API_KEY_INVALID")
        )

        with pytest.raises(GeminiAuthError):
            await provider.complete("test")

    @pytest.mark.asyncio
    async def test_complete_wraps_rate_limit_error(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("429 quota exceeded")
        )

        with pytest.raises(GeminiRateLimitError):
            await provider.complete("test")

    @pytest.mark.asyncio
    async def test_complete_wraps_generic_error(self):

        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("network timeout")
        )

        with pytest.raises(GeminiError):
            await provider.complete("test")

    @pytest.mark.asyncio
    async def test_complete_with_images(self):
        provider, mock_genai, mock_types = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "a cat"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await provider.complete(
            "What is this?",
            images=[{"url": "https://example.com/cat.jpg"}],
        )
        assert result == "a cat"


# ---------------------------------------------------------------------------
# stream_complete()
# ---------------------------------------------------------------------------


class TestStreamComplete:
    @pytest.mark.asyncio
    async def test_stream_complete_yields_chunks(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        async def fake_stream(**kwargs):
            for text in ["Hello ", "world"]:
                chunk = MagicMock()
                chunk.text = text
                yield chunk

        mock_client.aio.models.generate_content_stream = MagicMock(return_value=fake_stream())

        chunks = []
        async for chunk in provider.stream_complete("hi"):
            chunks.append(chunk)

        assert chunks == ["Hello ", "world"]

    @pytest.mark.asyncio
    async def test_stream_complete_skips_empty_chunks(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        async def fake_stream(**kwargs):
            for text in ["chunk", None, "", "end"]:
                chunk = MagicMock()
                chunk.text = text
                yield chunk

        mock_client.aio.models.generate_content_stream = MagicMock(return_value=fake_stream())

        chunks = []
        async for chunk in provider.stream_complete("hi"):
            chunks.append(chunk)

        assert chunks == ["chunk", "end"]

    @pytest.mark.asyncio
    async def test_stream_complete_wraps_error(self):

        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        async def failing_stream(**kwargs):
            raise Exception("API_KEY_INVALID")
            yield  # make it an async generator

        mock_client.aio.models.generate_content_stream = MagicMock(return_value=failing_stream())

        with pytest.raises(GeminiAuthError):
            async for _ in provider.stream_complete("test"):
                pass

    @pytest.mark.asyncio
    async def test_stream_complete_uses_model_kwarg(self):
        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        async def fake_stream(**kwargs):
            chunk = MagicMock()
            chunk.text = "x"
            yield chunk

        mock_client.aio.models.generate_content_stream = MagicMock(
            side_effect=lambda **kw: fake_stream()
        )

        chunks = []
        async for c in provider.stream_complete("hi", model="gemini-2.0-flash"):
            chunks.append(c)

        call_kwargs = mock_client.aio.models.generate_content_stream.call_args[1]
        assert call_kwargs["model"] == "gemini-2.0-flash"


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


class TestEmbed:
    @pytest.mark.asyncio
    async def test_embed_returns_vector(self):
        provider, mock_genai, mock_types = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        embedding_values = [0.1, 0.2, 0.3]
        mock_embedding = MagicMock()
        mock_embedding.values = embedding_values
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]
        mock_client.aio.models.embed_content = AsyncMock(return_value=mock_response)

        result = await provider.embed("hello world")
        assert result == embedding_values

    @pytest.mark.asyncio
    async def test_embed_uses_default_model(self):
        provider, mock_genai, mock_types = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.values = [0.5]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]
        mock_client.aio.models.embed_content = AsyncMock(return_value=mock_response)

        await provider.embed("text")

        call_kwargs = mock_client.aio.models.embed_content.call_args[1]
        assert call_kwargs["model"] == "models/text-embedding-004"

    @pytest.mark.asyncio
    async def test_embed_uses_custom_model_from_config(self):
        provider, mock_genai, mock_types = _make_provider({"embed_model": "models/custom-embed-v1"})
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.values = []
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]
        mock_client.aio.models.embed_content = AsyncMock(return_value=mock_response)

        await provider.embed("text")

        call_kwargs = mock_client.aio.models.embed_content.call_args[1]
        assert call_kwargs["model"] == "models/custom-embed-v1"

    @pytest.mark.asyncio
    async def test_embed_uses_model_kwarg(self):
        provider, mock_genai, mock_types = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.values = []
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]
        mock_client.aio.models.embed_content = AsyncMock(return_value=mock_response)

        await provider.embed("text", model="models/text-embedding-002")

        call_kwargs = mock_client.aio.models.embed_content.call_args[1]
        assert call_kwargs["model"] == "models/text-embedding-002"

    @pytest.mark.asyncio
    async def test_embed_wraps_error(self):

        provider, mock_genai, _ = _make_provider()
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.aio.models.embed_content = AsyncMock(side_effect=Exception("embed failed"))

        with pytest.raises(GeminiError):
            await provider.embed("text")


# ---------------------------------------------------------------------------
# count_tokens()
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_count_tokens_basic(self):
        provider, _, _ = _make_provider()
        # 40 chars / 4 = 10 tokens
        assert provider.count_tokens("a" * 40) == 10

    def test_count_tokens_minimum_one(self):
        provider, _, _ = _make_provider()
        assert provider.count_tokens("") == 1

    def test_count_tokens_short_string(self):
        provider, _, _ = _make_provider()
        assert provider.count_tokens("hi") == 1  # max(1, round(2/4)) = max(1,1)


# ---------------------------------------------------------------------------
# estimate_cost()
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_estimate_cost_known_model(self):
        provider, _, _ = _make_provider()
        cost = provider.estimate_cost(1_000_000, 1_000_000, model="gemini-1.5-flash")
        assert cost["input_cost"] == pytest.approx(0.075)
        assert cost["output_cost"] == pytest.approx(0.30)
        assert cost["total_cost"] == pytest.approx(0.375)

    def test_estimate_cost_defaults_to_configured_model(self):
        provider, _, _ = _make_provider({"model": "gemini-1.5-pro"})
        cost = provider.estimate_cost(1_000_000, 1_000_000)
        assert cost["input_cost"] == pytest.approx(3.50)
        assert cost["output_cost"] == pytest.approx(10.50)

    def test_estimate_cost_unknown_model_falls_back_to_pro(self):
        provider, _, _ = _make_provider()
        # Unknown model should fall back to gemini-1.5-pro rates
        cost = provider.estimate_cost(1_000_000, 1_000_000, model="gemini-unknown-9000")
        assert cost["input_cost"] == pytest.approx(3.50)
        assert cost["output_cost"] == pytest.approx(10.50)

    def test_estimate_cost_latest_suffix_stripped(self):
        """gemini-1.5-pro-latest should resolve to gemini-1.5-pro rates."""
        provider, _, _ = _make_provider()
        cost_latest = provider.estimate_cost(1_000_000, 0, model="gemini-1.5-pro-latest")
        cost_base = provider.estimate_cost(1_000_000, 0, model="gemini-1.5-pro")
        assert cost_latest["input_cost"] == cost_base["input_cost"]

    def test_estimate_cost_free_model(self):
        provider, _, _ = _make_provider()
        cost = provider.estimate_cost(1_000_000, 1_000_000, model="gemini-2.0-flash-thinking")
        assert cost["total_cost"] == 0.0

    def test_estimate_cost_small_amounts(self):
        provider, _, _ = _make_provider()
        cost = provider.estimate_cost(100, 50, model="gemini-2.0-flash")
        assert cost["input_cost"] >= 0.0
        assert cost["output_cost"] >= 0.0
        assert cost["total_cost"] == pytest.approx(cost["input_cost"] + cost["output_cost"])

    def test_estimate_cost_keys_present(self):
        provider, _, _ = _make_provider()
        cost = provider.estimate_cost(1000, 500)
        assert {"input_cost", "output_cost", "total_cost"} == set(cost.keys())
