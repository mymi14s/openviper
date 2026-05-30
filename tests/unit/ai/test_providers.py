"""Unit tests for AI provider implementations.

Tests SSRF prevention, URL validation, temperature clamping, cost estimation,
message building, error handling, and config parsing - all without hitting
real APIs.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openviper.ai import extension
from openviper.ai.base import AIProvider as BaseAIProvider
from openviper.ai.extension import (
    EXTENSION_API_VERSION,
)
from openviper.ai.extension import (
    AIProvider as ExtAIProvider,
)
from openviper.ai.extension import (
    provider_registry as ext_registry,
)
from openviper.ai.provider_utils import (
    clamp_temperature,
    count_tokens,
    estimate_cost,
    filter_kwargs,
)
from openviper.ai.providers.anthropic_provider import ALLOWED_KWARGS, AnthropicProvider
from openviper.ai.providers.gemini_provider import validate_image_url
from openviper.ai.providers.grok_provider import (
    GrokAuthError,
    GrokError,
    GrokProvider,
    GrokRateLimitError,
)
from openviper.ai.providers.grok_provider import (
    validate_base_url as grokvalidate_base_url,
)
from openviper.ai.providers.ollama_provider import OllamaProvider, validate_base_url
from openviper.ai.providers.openai_provider import ALLOWED_GENERATE_KWARGS, OpenAIProvider
from openviper.ai.registry import provider_registry as reg_registry

# ---------------------------------------------------------------------------
# Ollama - SSRF validation
# ---------------------------------------------------------------------------


class TestOllamaValidateBaseUrl:
    def test_localhost_http_allowed(self):
        validate_base_url("http://localhost:11434", allow_localhost=True)

    def test_127_http_allowed(self):
        validate_base_url("http://127.0.0.1:11434", allow_localhost=True)

    def test_ipv6_loopback_allowed(self):
        validate_base_url("http://[::1]:11434", allow_localhost=True)

    def test_non_localhost_http_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            validate_base_url("http://example.com:11434")

    def test_non_localhost_https_allowed(self):
        validate_base_url("https://ollama.example.com:11434")

    def test_private_10_network_rejected(self):
        with pytest.raises(ValueError, match="private"):
            validate_base_url("https://10.0.0.1:11434")

    def test_private_172_network_rejected(self):
        with pytest.raises(ValueError, match="private"):
            validate_base_url("https://172.16.0.1:11434")

    def test_private_192_network_rejected(self):
        with pytest.raises(ValueError, match="private"):
            validate_base_url("https://192.168.1.1:11434")

    def test_link_local_rejected(self):
        with pytest.raises(ValueError, match="private"):
            validate_base_url("https://169.254.169.254:11434")

    def test_hostname_allowed(self):
        validate_base_url("https://my-ollama.internal:11434")


class TestOllamaProvider:
    def test_default_base_url(self):
        p = OllamaProvider({"model": "llama3"})
        assert p.base_url == "http://localhost:11434"

    def test_custom_base_url(self):
        p = OllamaProvider({"model": "llama3", "base_url": "https://ollama.example.com"})
        assert p.base_url == "https://ollama.example.com"

    def test_model_set(self):
        p = OllamaProvider({"model": "llama3"})
        assert p.model == "llama3"

    def test_name(self):
        assert OllamaProvider.name == "ollama"

    def test_client_lazy_init(self):
        p = OllamaProvider({"model": "llama3"})
        assert p._client is None
        client = p._get_client()
        assert client is not None
        assert p._client is client


# ---------------------------------------------------------------------------
# Grok - SSRF, error handling, helpers
# ---------------------------------------------------------------------------


class TestGrokValidateBaseUrl:
    def test_https_allowed(self):
        grokvalidate_base_url("https://api.x.ai/v1")

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            grokvalidate_base_url("http://api.x.ai/v1")

    def test_private_ip_rejected(self):
        with pytest.raises(ValueError, match="private"):
            grokvalidate_base_url("https://10.0.0.1/v1")

    def test_hostname_allowed(self):
        grokvalidate_base_url("https://custom-grok.internal/v1")


class TestGrokProvider:
    def test_missing_api_key_raises(self):
        with pytest.raises(GrokAuthError, match="API key is required"):
            GrokProvider({"model": "grok-2-latest"})

    def test_name(self):
        assert GrokProvider.name == "grok"

    def test_clamp_temperature_none(self):
        assert clamp_temperature(None) is None

    def test_clamp_temperature_low(self):
        assert clamp_temperature(-1.0) == 0.0

    def test_clamp_temperature_high(self):
        assert clamp_temperature(5.0) == 2.0

    def test_clamp_temperature_invalid(self):
        assert clamp_temperature("bad") is None

    def test_clamp_temperature_normal(self):
        assert clamp_temperature(0.7) == 0.7

    def test_build_messages_text_only(self):
        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key"})
        msgs = p._build_messages("hello")
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_build_messages_with_url_image(self):
        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key"})
        msgs = p._build_messages("describe", images=[{"url": "https://example.com/img.jpg"}])
        assert msgs[0]["role"] == "user"
        content = msgs[0]["content"]
        assert content[0] == {"type": "text", "text": "describe"}
        assert content[1]["type"] == "image_url"

    def test_build_messages_with_base64_image(self):
        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key"})
        msgs = p._build_messages(
            "describe", images=[{"base64": "abc123", "mime_type": "image/png"}]
        )
        content = msgs[0]["content"]
        assert "data:image/png;base64,abc123" in content[1]["image_url"]["url"]

    def test_build_messages_with_raw_bytes(self):
        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key"})
        msgs = p._build_messages(
            "describe", images=[{"data": b"\x89PNG", "mime_type": "image/png"}]
        )
        content = msgs[0]["content"]
        assert content[1]["type"] == "image_url"

    def test_build_messages_skips_unknown_image_format(self):
        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key"})
        msgs = p._build_messages("describe", images=[{"unknown_key": "value"}])
        content = msgs[0]["content"]
        assert len(content) == 1  # only text, no image

    def test_build_payload(self):
        payload = GrokProvider._build_payload(
            [{"role": "user", "content": "hi"}],
            model="grok-2-latest",
            temperature=0.7,
            max_tokens=100,
            extra={"seed": 42},
        )
        assert payload["model"] == "grok-2-latest"
        assert payload["temperature"] == 0.7
        assert payload["max_tokens"] == 100
        assert payload["seed"] == 42

    def test_get_headers(self):
        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key-123"})
        headers = p._get_headers()
        assert headers["Authorization"] == "Bearer test-key-123"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_embed_raises_not_implemented(self):
        p = GrokProvider({"model": "grok-2-latest", "api_key": "test-key"})
        with pytest.raises(NotImplementedError, match="embeddings"):
            await p.embed("text")

    def test_count_tokens(self):
        assert count_tokens("hello world!") == 3  # 12 chars / 4

    def test_count_tokens_minimum_one(self):
        assert count_tokens("") == 1

    def test_estimate_cost(self):
        cost_table = {
            "grok-2-latest": {"input": 2.0, "output": 10.0},
        }
        cost = estimate_cost(1_000_000, 1_000_000, cost_table, "grok-2-latest")
        assert cost["input_cost"] == 2.0
        assert cost["output_cost"] == 10.0
        assert cost["total_cost"] == 12.0

    def test_estimate_cost_unknown_model_falls_back(self):
        cost_table = {
            "grok-2-latest": {"input": 2.0, "output": 10.0},
        }
        cost = estimate_cost(
            1_000_000,
            1_000_000,
            cost_table,
            "unknown-model",
            fallback_model="grok-2-latest",
        )
        assert cost["total_cost"] == 12.0


class TestGrokRaiseForStatus:
    def _make_response(self, status_code, json_body=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.is_success = 200 <= status_code < 300
        resp.json.return_value = json_body or {}
        return resp

    def test_success_no_raise(self):
        GrokProvider._raise_for_status(self._make_response(200))

    def test_401_raises_auth_error(self):
        with pytest.raises(GrokAuthError):
            GrokProvider._raise_for_status(self._make_response(401))

    def test_429_raises_rate_limit(self):
        with pytest.raises(GrokRateLimitError):
            GrokProvider._raise_for_status(self._make_response(429))

    def test_500_raises_grok_error(self):
        with pytest.raises(GrokError):
            GrokProvider._raise_for_status(
                self._make_response(500, {"error": {"message": "internal"}})
            )


class TestGrokBuildExtraParams:
    def _provider(self):
        return GrokProvider({"model": "grok-2-latest", "api_key": "k"})

    def test_reasoning_effort(self):
        p = self._provider()
        kw = {"reasoning_effort": "high"}
        extra = p._build_extra_params(kw)
        assert extra["reasoning_effort"] == "high"

    def test_search_enabled(self):
        p = self._provider()
        kw = {"search_enabled": True}
        extra = p._build_extra_params(kw)
        assert extra["search_parameters"] == {"mode": "auto"}

    def test_allowed_kwargs_forwarded(self):
        p = self._provider()
        kw = {"stop": ["END"], "seed": 42}
        extra = p._build_extra_params(kw)
        assert extra["stop"] == ["END"]
        assert extra["seed"] == 42

    def test_unknown_kwargs_ignored(self):
        p = self._provider()
        kw = {"unknown_param": "value"}
        extra = p._build_extra_params(kw)
        assert "unknown_param" not in extra


# ---------------------------------------------------------------------------
# Gemini - SSRF, error wrapping, cost estimation
# ---------------------------------------------------------------------------


class TestGeminiValidateImageUrl:
    def test_https_allowed(self):
        validate_image_url("https://example.com/image.jpg")

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            validate_image_url("http://example.com/image.jpg")

    def test_ftp_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            validate_image_url("ftp://example.com/image.jpg")

    def test_private_10_rejected(self):
        with pytest.raises(ValueError, match="private"):
            validate_image_url("https://10.0.0.1/img.jpg")

    def test_loopback_rejected(self):
        with pytest.raises(ValueError, match="private"):
            validate_image_url("https://127.0.0.1/img.jpg")

    def test_link_local_rejected(self):
        with pytest.raises(ValueError, match="private"):
            validate_image_url("https://169.254.169.254/latest/meta-data")

    def test_hostname_allowed(self):
        validate_image_url("https://images.example.com/photo.jpg")


# ---------------------------------------------------------------------------
# OpenAI - kwarg filtering, temperature clamping
# ---------------------------------------------------------------------------


class TestOpenAIFilterKwargs:
    def test_allowed_kwargs_pass_through(self):
        result = filter_kwargs(
            {"stop": ["\n"], "seed": 42}, ALLOWED_GENERATE_KWARGS, provider="OpenAIProvider"
        )
        assert result == {"stop": ["\n"], "seed": 42}

    def test_unknown_kwargs_filtered(self):
        result = filter_kwargs(
            {"stop": ["\n"], "custom_param": "x"},
            ALLOWED_GENERATE_KWARGS,
            provider="OpenAIProvider",
        )
        assert "custom_param" not in result
        assert result == {"stop": ["\n"]}

    def test_empty_kwargs(self):
        result = filter_kwargs({}, ALLOWED_GENERATE_KWARGS, provider="OpenAIProvider")
        assert result == {}


class TestOpenAIClampTemperature:
    def test_none_returns_none(self):
        assert clamp_temperature(None) is None

    def test_invalid_returns_none(self):
        assert clamp_temperature("abc") is None

    def test_clamp_high(self):
        assert clamp_temperature(5.0) == 2.0

    def test_clamp_low(self):
        assert clamp_temperature(-1.0) == 0.0

    def test_normal_value(self):
        assert clamp_temperature(0.7) == 0.7


class TestOpenAIProviderInit:
    def test_name(self):
        assert OpenAIProvider.name == "openai"

    def test_client_lazy(self):
        p = OpenAIProvider({"api_key": "test", "model": "gpt-4o"})
        assert p._client is None


# ---------------------------------------------------------------------------
# Anthropic - kwarg filtering, temperature clamping
# ---------------------------------------------------------------------------


class TestAnthropicClampTemperature:
    def test_none_returns_none(self):
        assert clamp_temperature(None, max_temp=1.0) is None

    def test_invalid_returns_none(self):
        assert clamp_temperature("abc", max_temp=1.0) is None

    def test_clamp_high(self):
        assert clamp_temperature(5.0, max_temp=1.0) == 1.0

    def test_clamp_low(self):
        assert clamp_temperature(-1.0, max_temp=1.0) == 0.0

    def test_normal_value(self):
        assert clamp_temperature(0.7, max_temp=1.0) == 0.7


class TestAnthropicFilterKwargs:
    def test_allowed_kwargs(self):
        result = filter_kwargs(
            {"system": "you are helpful", "top_p": 0.9},
            ALLOWED_KWARGS,
            provider="AnthropicProvider",
        )
        assert result == {"system": "you are helpful", "top_p": 0.9}

    def test_unknown_kwargs_filtered(self):
        result = filter_kwargs(
            {"system": "hi", "bad_param": True},
            ALLOWED_KWARGS,
            provider="AnthropicProvider",
        )
        assert "bad_param" not in result

    def test_name(self):
        assert AnthropicProvider.name == "anthropic"


# ---------------------------------------------------------------------------
# Extension module - public API surface
# ---------------------------------------------------------------------------


class TestExtensionModule:
    def test_version_tuple(self):
        assert EXTENSION_API_VERSION == (1, 0)

    def test_exports_ai_provider(self):
        assert ExtAIProvider is BaseAIProvider

    def test_exports_registry(self):
        assert ext_registry is reg_registry

    def test_exports_all_exceptions(self):
        for name in [
            "AIException",
            "ModelCollisionError",
            "ModelNotFoundError",
            "ModelUnavailableError",
            "ProviderNotAvailableError",
            "ProviderNotConfiguredError",
        ]:
            assert hasattr(extension, name)
