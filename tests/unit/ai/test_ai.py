from typing import Any
from unittest.mock import patch

import pytest

from openviper.ai.base import AIProvider
from openviper.ai.devkit import SimpleProvider, StreamingAdapter, map_http_error, normalize_response
from openviper.ai.exceptions import AIError, ModelUnavailableError, ProviderNotAvailableError


class DummyProvider(AIProvider):
    name = "dummy"

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        return "dummy response"


# ── AIProvider Config Initialization ───────────────────────────────────────


def test_aiprovider_config_permutations():
    # 1. model as dict
    p1 = DummyProvider({"model": {"foo": "bar", "default": "gpt-4"}})
    assert p1.default_model == "gpt-4"

    p2 = DummyProvider({"model": {"only": "model-v1"}})
    assert p2.default_model == "model-v1"

    # 2. models as dict
    p3 = DummyProvider({"models": {"gpt-3": "id-3", "default": "gpt-3"}})
    assert p3.default_model == "gpt-3"

    # 3. models as list
    p4 = DummyProvider({"models": ["first-model", "second-model"]})
    assert p4.default_model == "first-model"


# ── Content Moderation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aiprovider_moderate_parsing():
    p = DummyProvider({})

    # Case 1: markdown json fence
    with patch.object(
        p,
        "generate",
        return_value='Here is the json: ```json\n{"classification": "hate", \
            "confidence": 0.9, "reason": "bad"}\n```',
    ):
        res = await p.moderate("some text")
        assert res["classification"] == "hate"
        assert res["confidence"] == 0.9
        assert not res["is_safe"]

    # Case 2: plain markdown fence
    with patch.object(
        p, "generate", return_value='```\n{"classification": "abusive", "confidence": 0.8}\n```'
    ):
        res = await p.moderate("some text")
        assert res["classification"] == "abusive"

    # Case 3: Parse error fallback
    with patch.object(p, "generate", return_value="Not JSON at all"):
        res = await p.moderate("some text")
        assert res["classification"] == "safe"
        assert res["reason"] == "Parse error — could not decode AI response."

    # Case 4: Invalid classification fallback
    with patch.object(p, "generate", return_value='{"classification": "invalid_type"}'):
        res = await p.moderate("some text")
        assert res["classification"] == "safe"

    # Case 5: Confidence float conversion error
    with patch.object(
        p, "generate", return_value='{"classification": "safe", "confidence": "high"}'
    ):
        res = await p.moderate("some text")
        # Should default to 0.5
        assert res["confidence"] == 0.5


# ── Supported Models ───────────────────────────────────────────────────────


def test_aiprovider_supported_models():
    # models as dict + model as dict
    p = DummyProvider({"models": {"A": "id-a", "B": "id-b"}, "model": {"C": "id-c"}})
    assert p.supported_models() == ["id-a", "id-b", "id-c"]

    # models as list + model as str
    p2 = DummyProvider({"models": ["list-1", "list-2"], "model": "str-model"})
    assert p2.supported_models() == ["list-1", "list-2", "str-model"]

    assert p2.provider_name() == "dummy"


# ── DevKit Helpers ─────────────────────────────────────────────────────────


def test_simple_provider_name_override():
    class MySimple(SimpleProvider):
        name = "orig"

        async def generate(self, prompt, **kwargs):
            return ""

    p = MySimple({}, name="overridden")
    assert p.provider_name() == "overridden"

    p2 = MySimple({})
    assert p2.provider_name() == "orig"


def test_normalize_response_blank_lines():
    raw = "Line 1\n\n\n\nLine 2"
    out = normalize_response(raw)
    assert out == "Line 1\n\nLine 2"


@pytest.mark.asyncio
async def test_streaming_adapter():
    def sync_gen():
        yield "token1"
        yield "token2"

    adapter = StreamingAdapter(sync_gen)
    tokens = []
    async for t in adapter:
        tokens.append(t)

    assert tokens == ["token1", "token2"]


# ── Final Trivial Coverage ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_base_provider_fallbacks_and_aliases():
    p = DummyProvider({})

    # Hooks
    assert await p.before_inference("p", {"k": 1}) == ("p", {"k": 1})
    assert await p.after_inference("p", "r") == "r"

    # Aliases
    assert await p.complete("p") == "dummy response"

    # stream_complete alias and stream default
    res = []
    async for chunk in p.stream_complete("p"):
        res.append(chunk)
    assert res == ["dummy response"]


def test_map_http_error_branches():

    # 401/403
    assert isinstance(map_http_error(401, provider="p"), ProviderNotAvailableError)
    # 429
    assert isinstance(map_http_error(429, provider="p"), ProviderNotAvailableError)
    # 404 with model
    err = map_http_error(404, "not found", provider="p", model="m")
    assert isinstance(err, ModelUnavailableError)
    # 500
    assert isinstance(map_http_error(500, provider="p"), ProviderNotAvailableError)
    # Generic
    assert isinstance(map_http_error(418, provider="p"), AIError)
