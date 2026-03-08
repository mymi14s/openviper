"""Unit tests for openviper.ai.base.AIProvider.

Missing coverage lines:
  49-50 – stream_complete() body: result = await self.complete(); yield result
  74    – before_inference() body: return prompt, kwargs
  86    – after_inference() body: return response
"""

from __future__ import annotations

import pytest

from openviper.ai.base import AIProvider

# ── Concrete implementations used across tests ────────────────────────────────


class EchoProvider(AIProvider):
    """Returns the prompt prefixed with 'echo:' from generate()."""

    name = "echo"

    async def generate(self, prompt: str, **kwargs) -> str:
        return f"echo:{prompt}"


class ConstantProvider(AIProvider):
    """Always returns the same string from generate()."""

    name = "constant"

    async def generate(self, prompt: str, **kwargs) -> str:
        return "constant_response"


class KwargsRecordingProvider(AIProvider):
    """Records kwargs passed to generate() for inspection."""

    name = "kwargs_recorder"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.last_kwargs: dict = {}

    async def generate(self, prompt: str, **kwargs) -> str:
        self.last_kwargs = kwargs
        return f"done:{prompt}"


# ── Instantiation and config ──────────────────────────────────────────────────


def test_cannot_instantiate_abstract_provider_directly():
    with pytest.raises(TypeError):
        AIProvider({})  # type: ignore[abstract]


def test_init_stores_config_dict():
    config = {"model": "gpt-4", "temperature": 0.5}
    provider = EchoProvider(config)
    assert provider.config is config


def test_init_accepts_empty_config():
    provider = EchoProvider({})
    assert provider.config == {}


def test_init_stores_arbitrary_config_values():
    config = {"key": "value", "count": 42, "flag": True}
    provider = EchoProvider(config)
    assert provider.config["key"] == "value"
    assert provider.config["count"] == 42
    assert provider.config["flag"] is True


def test_name_class_attribute_accessible_on_instance():
    provider = EchoProvider({})
    assert provider.name == "echo"


def test_name_class_attribute_accessible_on_class():
    assert EchoProvider.name == "echo"


def test_base_name_is_base():
    assert AIProvider.name == "base"


# ── complete() (abstract contract) ───────────────────────────────────────────


async def test_complete_returns_string():
    provider = EchoProvider({})
    result = await provider.complete("hello")
    assert isinstance(result, str)


async def test_complete_uses_prompt():
    provider = EchoProvider({})
    assert await provider.complete("world") == "echo:world"


async def test_complete_passes_kwargs_to_subclass():
    provider = KwargsRecordingProvider({})
    await provider.complete("test", temperature=0.7, max_tokens=256)
    assert provider.last_kwargs["temperature"] == 0.7
    assert provider.last_kwargs["max_tokens"] == 256


# ── stream_complete()  ──────────────────────────────────────────


async def test_stream_complete_yields_at_least_one_chunk():
    provider = EchoProvider({})
    chunks = []
    async for chunk in provider.stream_complete("hi"):
        chunks.append(chunk)
    assert len(chunks) >= 1


async def test_stream_complete_default_yields_exactly_one_chunk():
    """Default implementation forwards complete() output as a single chunk."""
    provider = ConstantProvider({})
    chunks = []
    async for chunk in provider.stream_complete("anything"):
        chunks.append(chunk)
    assert len(chunks) == 1


async def test_stream_complete_chunk_matches_complete_output():
    provider = EchoProvider({})
    expected = await provider.complete("stream_test")
    chunks = []
    async for chunk in provider.stream_complete("stream_test"):
        chunks.append(chunk)
    assert chunks[0] == expected


async def test_stream_complete_yields_complete_result():
    provider = ConstantProvider({})
    chunks = []
    async for chunk in provider.stream_complete("prompt"):
        chunks.append(chunk)
    assert chunks == ["constant_response"]


async def test_stream_complete_forwards_kwargs_to_complete():
    provider = KwargsRecordingProvider({})
    chunks = []
    async for chunk in provider.stream_complete("p", temperature=0.9):
        chunks.append(chunk)
    assert provider.last_kwargs["temperature"] == 0.9


async def test_stream_complete_result_is_string():
    provider = EchoProvider({})
    async for chunk in provider.stream_complete("test"):
        assert isinstance(chunk, str)


async def test_stream_complete_returns_async_iterator():
    provider = EchoProvider({})
    gen = provider.stream_complete("test")
    # An async generator supports __aiter__ and __anext__
    assert hasattr(gen, "__aiter__")
    assert hasattr(gen, "__anext__")
    # Consume it to avoid resource warnings
    async for _ in gen:
        pass


# ── embed() (NotImplementedError — excluded from coverage but tested) ─────────


async def test_embed_raises_not_implemented_error():
    provider = EchoProvider({})
    with pytest.raises(NotImplementedError):
        await provider.embed("some text")


async def test_embed_error_message_contains_class_name():
    provider = EchoProvider({})
    with pytest.raises(NotImplementedError, match="EchoProvider"):
        await provider.embed("text")


async def test_embed_error_message_mentions_embeddings():
    provider = EchoProvider({})
    with pytest.raises(NotImplementedError, match="embeddings"):
        await provider.embed("text")


# ── before_inference()  ─────────────────────────────────────────────


async def test_before_inference_returns_tuple():
    provider = EchoProvider({})
    result = await provider.before_inference("prompt", {})
    assert isinstance(result, tuple)
    assert len(result) == 2


async def test_before_inference_returns_prompt_unchanged():
    provider = EchoProvider({})
    prompt = "my specific prompt"
    returned_prompt, _ = await provider.before_inference(prompt, {})
    assert returned_prompt == prompt


async def test_before_inference_returns_kwargs_unchanged():
    provider = EchoProvider({})
    kwargs = {"temperature": 0.5, "max_tokens": 512}
    _, returned_kwargs = await provider.before_inference("p", kwargs)
    assert returned_kwargs == kwargs


async def test_before_inference_returns_same_prompt_object():
    provider = EchoProvider({})
    prompt = "identity test"
    p, _ = await provider.before_inference(prompt, {})
    assert p is prompt


async def test_before_inference_returns_same_kwargs_object():
    provider = EchoProvider({})
    kwargs: dict = {}
    _, k = await provider.before_inference("p", kwargs)
    assert k is kwargs


async def test_before_inference_with_populated_kwargs():
    provider = EchoProvider({})
    kwargs = {"a": 1, "b": 2}
    p, k = await provider.before_inference("q", kwargs)
    assert p == "q"
    assert k == {"a": 1, "b": 2}


async def test_before_inference_with_empty_prompt():
    provider = EchoProvider({})
    p, k = await provider.before_inference("", {})
    assert p == ""
    assert k == {}


# ── after_inference()  ──────────────────────────────────────────────


async def test_after_inference_returns_response():
    provider = EchoProvider({})
    response = "the generated text"
    result = await provider.after_inference("original prompt", response)
    assert result == response


async def test_after_inference_returns_same_object():
    provider = EchoProvider({})
    response = "identity test"
    result = await provider.after_inference("prompt", response)
    assert result is response


async def test_after_inference_does_not_use_prompt():
    provider = EchoProvider({})
    response = "response text"
    result1 = await provider.after_inference("prompt A", response)
    result2 = await provider.after_inference("prompt B", response)
    assert result1 == result2


async def test_after_inference_with_empty_response():
    provider = EchoProvider({})
    result = await provider.after_inference("prompt", "")
    assert result == ""


async def test_after_inference_with_multiline_response():
    provider = EchoProvider({})
    response = "line one\nline two\nline three"
    result = await provider.after_inference("p", response)
    assert result == response
