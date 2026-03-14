"""Unit tests for openviper/ai/base.py — AIProvider abstract base class."""

from __future__ import annotations

import json

import pytest

from openviper.ai.base import AIProvider

# ---------------------------------------------------------------------------
# Concrete stub for testing the ABC
# ---------------------------------------------------------------------------


class StubProvider(AIProvider):
    name = "stub"

    def __init__(self, config: dict | None = None, *, generate_response: str = "ok"):
        super().__init__(config or {})
        self._generate_response = generate_response

    async def generate(self, prompt: str, **kwargs) -> str:
        return self._generate_response


# ---------------------------------------------------------------------------
# Default model extraction
# ---------------------------------------------------------------------------


class TestDefaultModelExtraction:
    def test_model_as_string(self):
        p = StubProvider({"model": "gpt-4o"})
        assert p.default_model == "gpt-4o"

    def test_model_as_dict_with_default_key(self):
        p = StubProvider({"model": {"default": "gpt-4o", "fast": "gpt-3.5"}})
        assert p.default_model == "gpt-4o"

    def test_model_as_dict_without_default_key(self):
        p = StubProvider({"model": {"fast": "gpt-3.5", "smart": "gpt-4o"}})
        assert p.default_model == "gpt-3.5"

    def test_models_as_list(self):
        p = StubProvider({"models": ["llama3", "mistral"]})
        assert p.default_model == "llama3"

    def test_models_as_dict_with_default_key(self):
        p = StubProvider({"models": {"default": "llama3", "alt": "mistral"}})
        assert p.default_model == "llama3"

    def test_models_as_dict_without_default_key(self):
        p = StubProvider({"models": {"alt": "mistral", "big": "llama3"}})
        assert p.default_model == "mistral"

    def test_model_string_takes_precedence_over_models(self):
        p = StubProvider({"model": "gpt-4o", "models": ["llama3"]})
        assert p.default_model == "gpt-4o"

    def test_no_model_config_yields_none(self):
        p = StubProvider({})
        assert p.default_model is None

    def test_model_none_falls_through_to_models(self):
        p = StubProvider({"model": None, "models": ["llama3"]})
        assert p.default_model == "llama3"


# ---------------------------------------------------------------------------
# supported_models()
# ---------------------------------------------------------------------------


class TestSupportedModels:
    def test_models_dict(self):
        p = StubProvider({"models": {"a": "model-a", "b": "model-b"}})
        assert p.supported_models() == ["model-a", "model-b"]

    def test_models_list(self):
        p = StubProvider({"models": ["model-b", "model-a"]})
        assert p.supported_models() == ["model-a", "model-b"]

    def test_model_string(self):
        p = StubProvider({"model": "gpt-4o"})
        assert p.supported_models() == ["gpt-4o"]

    def test_model_dict_values(self):
        p = StubProvider({"model": {"default": "gpt-4o", "fast": "gpt-3.5"}})
        assert p.supported_models() == ["gpt-3.5", "gpt-4o"]

    def test_combined_model_and_models(self):
        p = StubProvider({"model": "gpt-4o", "models": {"a": "llama3"}})
        result = p.supported_models()
        assert "gpt-4o" in result
        assert "llama3" in result

    def test_empty_config(self):
        p = StubProvider({})
        assert p.supported_models() == []

    def test_deduplication(self):
        p = StubProvider({"model": "gpt-4o", "models": ["gpt-4o"]})
        assert p.supported_models() == ["gpt-4o"]


# ---------------------------------------------------------------------------
# provider_name()
# ---------------------------------------------------------------------------


class TestProviderName:
    def test_returns_class_name_attribute(self):
        p = StubProvider()
        assert p.provider_name() == "stub"


# ---------------------------------------------------------------------------
# stream() — default implementation
# ---------------------------------------------------------------------------


class TestDefaultStream:
    @pytest.mark.asyncio
    async def test_yields_full_generate_result(self):
        p = StubProvider(generate_response="hello world")
        chunks = [c async for c in p.stream("hi")]
        assert chunks == ["hello world"]


# ---------------------------------------------------------------------------
# embed() — default raises NotImplementedError
# ---------------------------------------------------------------------------


class TestEmbed:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        p = StubProvider()
        with pytest.raises(NotImplementedError, match="StubProvider"):
            await p.embed("text")


# ---------------------------------------------------------------------------
# Hooks — before_inference / after_inference
# ---------------------------------------------------------------------------


class TestHooks:
    @pytest.mark.asyncio
    async def test_before_inference_passthrough(self):
        p = StubProvider()
        prompt, kwargs = await p.before_inference("hello", {"a": 1})
        assert prompt == "hello"
        assert kwargs == {"a": 1}

    @pytest.mark.asyncio
    async def test_after_inference_passthrough(self):
        p = StubProvider()
        result = await p.after_inference("hello", "world")
        assert result == "world"


# ---------------------------------------------------------------------------
# Backward-compatibility aliases
# ---------------------------------------------------------------------------


class TestBackwardCompatAliases:
    @pytest.mark.asyncio
    async def test_complete_delegates_to_generate(self):
        p = StubProvider(generate_response="from generate")
        result = await p.complete("hi")
        assert result == "from generate"

    @pytest.mark.asyncio
    async def test_stream_complete_delegates_to_stream(self):
        p = StubProvider(generate_response="streamed")
        chunks = [c async for c in p.stream_complete("hi")]
        assert chunks == ["streamed"]


# ---------------------------------------------------------------------------
# moderate() — JSON parsing, truncation, classification
# ---------------------------------------------------------------------------


class TestModerate:
    @pytest.mark.asyncio
    async def test_valid_json_response(self):
        response = json.dumps(
            {
                "classification": "spam",
                "confidence": 0.9,
                "reason": "looks like spam",
            }
        )

        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return response

        p = ModProvider()
        result = await p.moderate("buy now")
        assert result["classification"] == "spam"
        assert result["confidence"] == 0.9
        assert result["reason"] == "looks like spam"
        assert result["is_safe"] is False
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_markdown_fenced_json(self):
        raw = '```json\n{"classification": "safe", "confidence": 0.8, "reason": "ok"}\n```'

        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return raw

        p = ModProvider()
        result = await p.moderate("hello")
        assert result["classification"] == "safe"

    @pytest.mark.asyncio
    async def test_unparseable_response_returns_safe_fallback(self):
        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return "I cannot classify this"

        p = ModProvider()
        result = await p.moderate("hello")
        assert result["classification"] == "safe"
        assert result["confidence"] == 0.0
        assert result["is_safe"] is True
        assert "Parse error" in result["reason"]

    @pytest.mark.asyncio
    async def test_invalid_classification_normalized_to_safe(self):
        raw = json.dumps(
            {
                "classification": "unknown_class",
                "confidence": 0.5,
                "reason": "test",
            }
        )

        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return raw

        p = ModProvider()
        result = await p.moderate("test")
        assert result["classification"] == "safe"

    @pytest.mark.asyncio
    async def test_confidence_clamped(self):
        raw = json.dumps(
            {
                "classification": "hate",
                "confidence": 5.0,
                "reason": "test",
            }
        )

        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return raw

        p = ModProvider()
        result = await p.moderate("test")
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_low_confidence_hate_is_safe(self):
        raw = json.dumps(
            {
                "classification": "hate",
                "confidence": 0.3,
                "reason": "borderline",
            }
        )

        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return raw

        p = ModProvider()
        result = await p.moderate("test")
        assert result["is_safe"] is True

    @pytest.mark.asyncio
    async def test_truncation_flag_for_long_content(self):
        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return json.dumps(
                    {
                        "classification": "safe",
                        "confidence": 1.0,
                        "reason": "ok",
                    }
                )

        p = ModProvider()
        result = await p.moderate("x" * 3000)
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_no_truncation_for_short_content(self):
        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return json.dumps(
                    {
                        "classification": "safe",
                        "confidence": 1.0,
                        "reason": "ok",
                    }
                )

        p = ModProvider()
        result = await p.moderate("short")
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_invalid_confidence_defaults_to_0_5(self):
        raw = json.dumps(
            {
                "classification": "safe",
                "confidence": "not_a_number",
                "reason": "test",
            }
        )

        class ModProvider(StubProvider):
            async def generate(self, prompt, **kw):
                return raw

        p = ModProvider()
        result = await p.moderate("test")
        assert result["confidence"] == 0.5
