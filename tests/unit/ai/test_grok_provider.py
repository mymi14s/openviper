"""Unit tests for GrokProvider."""

from __future__ import annotations

import base64
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.ai.providers.grok_provider import (
    GrokAuthError,
    GrokError,
    GrokProvider,
    GrokRateLimitError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(config: dict[str, Any] | None = None) -> GrokProvider:
    base = {"api_key": "test-xai-key", "model": "grok-2-latest"}
    if config:
        base.update(config)
    return GrokProvider(base)


def _make_mock_response(
    *,
    status_code: int = 200,
    body: dict[str, Any] | None = None,
    text: str = "",
) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.is_success = status_code < 300
    if body is not None:
        mock_resp.json.return_value = body
        mock_resp.text = json.dumps(body)
    else:
        mock_resp.json.side_effect = Exception("not JSON")
        mock_resp.text = text
    return mock_resp


def _chat_response_body(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestGrokProviderInit:
    def test_init_with_api_key_in_config(self):
        p = _make_provider({"api_key": "key-from-config"})
        assert p._api_key == "key-from-config"

    def test_init_falls_back_to_env_var(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "key-from-env")
        p = GrokProvider({})  # no api_key in config
        assert p._api_key == "key-from-env"

    def test_init_raises_auth_error_when_no_key(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        with pytest.raises(GrokAuthError, match="xAI API key is required"):
            GrokProvider({})

    def test_init_default_model(self):
        p = _make_provider()
        assert p._default_model == "grok-2-latest"

    def test_init_custom_model(self):
        p = _make_provider({"model": "grok-3"})
        assert p._default_model == "grok-3"

    def test_init_default_base_url(self):
        p = _make_provider()
        assert p._base_url == "https://api.x.ai/v1"

    def test_init_custom_base_url(self):
        p = _make_provider({"base_url": "https://custom.url/v1/"})
        assert p._base_url == "https://custom.url/v1"  # trailing slash stripped

    def test_init_default_timeout(self):
        p = _make_provider()
        assert p._timeout == 60.0

    def test_init_custom_timeout(self):
        p = _make_provider({"timeout": 30})
        assert p._timeout == 30.0


# ---------------------------------------------------------------------------
# _headers property
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_headers_contain_auth(self):
        p = _make_provider({"api_key": "my-secret"})
        headers = p._headers
        assert headers["Authorization"] == "Bearer my-secret"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def test_text_only(self):
        p = _make_provider()
        msgs = p._build_messages("Hello")
        assert msgs == [{"role": "user", "content": "Hello"}]

    def test_with_url_image(self):
        p = _make_provider()
        msgs = p._build_messages("desc", images=[{"url": "https://example.com/pic.jpg"}])
        assert len(msgs) == 1
        content = msgs[0]["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "desc"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "https://example.com/pic.jpg"

    def test_with_base64_image(self):
        p = _make_provider()
        b64 = "abc123"
        msgs = p._build_messages("describe", images=[{"base64": b64, "mime_type": "image/png"}])
        content = msgs[0]["content"]
        expected_url = f"data:image/png;base64,{b64}"
        assert content[1]["image_url"]["url"] == expected_url

    def test_with_raw_bytes_image(self):
        p = _make_provider()
        raw = b"\x89PNG"
        expected_b64 = base64.b64encode(raw).decode()
        msgs = p._build_messages("png", images=[{"data": raw, "mime_type": "image/png"}])
        content = msgs[0]["content"]
        assert content[1]["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"

    def test_skips_images_without_valid_key(self):
        p = _make_provider()
        msgs = p._build_messages("text", images=[{"not_a_url": "nope"}])
        # The invalid image entry is skipped; content should have only text part
        content = msgs[0]["content"]
        assert len(content) == 1
        assert content[0] == {"type": "text", "text": "text"}

    def test_default_mime_type_for_base64(self):
        p = _make_provider()
        msgs = p._build_messages("x", images=[{"base64": "abc"}])
        content = msgs[0]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


# ---------------------------------------------------------------------------
# _build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_build_payload_non_stream(self):
        p = _make_provider()
        msgs = [{"role": "user", "content": "hi"}]
        payload = p._build_payload(msgs, "grok-2-latest", 0.7, 1024, {})
        assert payload["model"] == "grok-2-latest"
        assert payload["messages"] is msgs
        assert payload["temperature"] == 0.7
        assert payload["max_tokens"] == 1024
        assert payload["stream"] is False

    def test_build_payload_stream(self):
        p = _make_provider()
        payload = p._build_payload([], "grok-3", 1.0, 512, {}, stream=True)
        assert payload["stream"] is True

    def test_build_payload_merges_extra(self):
        p = _make_provider()
        extra = {"reasoning_effort": "high"}
        payload = p._build_payload([], "grok-3", 1.0, 512, extra)
        assert payload["reasoning_effort"] == "high"


# ---------------------------------------------------------------------------
# _build_extra_params
# ---------------------------------------------------------------------------


class TestBuildExtraParams:
    def test_reasoning_effort_from_kwargs(self):
        p = _make_provider()
        kwargs = {"reasoning_effort": "high"}
        extra = p._build_extra_params(kwargs)
        assert extra["reasoning_effort"] == "high"
        assert "reasoning_effort" not in kwargs  # popped

    def test_reasoning_effort_from_config(self):
        p = _make_provider({"reasoning_effort": "medium"})
        extra = p._build_extra_params({})
        assert extra["reasoning_effort"] == "medium"

    def test_search_enabled_from_kwargs(self):
        p = _make_provider()
        kwargs = {"search_enabled": True}
        extra = p._build_extra_params(kwargs)
        assert extra["search_parameters"] == {"mode": "auto"}
        assert "search_enabled" not in kwargs

    def test_search_enabled_from_config(self):
        p = _make_provider({"search_enabled": True})
        extra = p._build_extra_params({})
        assert extra["search_parameters"] == {"mode": "auto"}

    def test_no_extra_params(self):
        p = _make_provider()
        extra = p._build_extra_params({})
        assert extra == {}

    def test_search_disabled_not_added(self):
        p = _make_provider()
        extra = p._build_extra_params({"search_enabled": False})
        assert "search_parameters" not in extra


# ---------------------------------------------------------------------------
# _raise_for_status
# ---------------------------------------------------------------------------


class TestRaiseForStatus:
    def test_success_does_not_raise(self):
        resp = _make_mock_response(status_code=200)
        GrokProvider._raise_for_status(resp)  # no exception

    def test_401_raises_auth_error(self):
        resp = _make_mock_response(
            status_code=401,
            body={"error": {"message": "invalid key"}},
        )
        with pytest.raises(GrokAuthError, match="Grok authentication failed"):
            GrokProvider._raise_for_status(resp)

    def test_429_raises_rate_limit_error(self):
        resp = _make_mock_response(
            status_code=429,
            body={"error": {"message": "rate limit hit"}},
        )
        with pytest.raises(GrokRateLimitError, match="Grok rate limit exceeded"):
            GrokProvider._raise_for_status(resp)

    def test_500_raises_generic_error(self):
        resp = _make_mock_response(status_code=500, text="server error")
        with pytest.raises(GrokError, match="Grok API error 500"):
            GrokProvider._raise_for_status(resp)

    def test_non_json_body_uses_text(self):
        resp = _make_mock_response(status_code=503, text="service unavailable")
        with pytest.raises(GrokError) as exc_info:
            GrokProvider._raise_for_status(resp)
        assert "503" in str(exc_info.value)

    def test_json_with_no_error_key(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.is_success = False
        resp.json.return_value = {}  # no "error" key
        resp.text = "bad request"
        with pytest.raises(GrokError):
            GrokProvider._raise_for_status(resp)


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


class TestComplete:
    def _mock_httpx(self, response: MagicMock):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        return mock_client

    @pytest.mark.asyncio
    async def test_complete_success(self):
        p = _make_provider()
        resp = _make_mock_response(body=_chat_response_body("Hello from Grok!"))
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await p.complete("Say hi")

        assert result == "Hello from Grok!"

    @pytest.mark.asyncio
    async def test_complete_uses_default_model(self):
        p = _make_provider()
        resp = _make_mock_response(body=_chat_response_body("ok"))
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await p.complete("test")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["model"] == "grok-2-latest"

    @pytest.mark.asyncio
    async def test_complete_override_model(self):
        p = _make_provider()
        resp = _make_mock_response(body=_chat_response_body("ok"))
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await p.complete("test", model="grok-3")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["model"] == "grok-3"

    @pytest.mark.asyncio
    async def test_complete_handles_empty_content(self):
        p = _make_provider()
        resp = _make_mock_response(body=_chat_response_body(""))
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await p.complete("test")

        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_posts_to_correct_endpoint(self):
        p = _make_provider()
        resp = _make_mock_response(body=_chat_response_body("ok"))
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await p.complete("test")

        url = mock_client.post.call_args[0][0]
        assert url == "https://api.x.ai/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_complete_raises_auth_error_on_401(self):
        p = _make_provider()
        resp = _make_mock_response(
            status_code=401,
            body={"error": {"message": "bad key"}},
        )
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(GrokAuthError):
                await p.complete("test")

    @pytest.mark.asyncio
    async def test_complete_raises_rate_limit_error_on_429(self):
        p = _make_provider()
        resp = _make_mock_response(
            status_code=429,
            body={"error": {"message": "too many"}},
        )
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(GrokRateLimitError):
                await p.complete("test")

    @pytest.mark.asyncio
    async def test_complete_passes_temperature_and_max_tokens(self):
        p = _make_provider()
        resp = _make_mock_response(body=_chat_response_body("ok"))
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await p.complete("test", temperature=0.2, max_tokens=256)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 256

    @pytest.mark.asyncio
    async def test_complete_with_reasoning_effort(self):
        p = _make_provider()
        resp = _make_mock_response(body=_chat_response_body("reasoned"))
        mock_client = self._mock_httpx(resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await p.complete("test", reasoning_effort="high")

        payload = mock_client.post.call_args[1]["json"]
        assert payload.get("reasoning_effort") == "high"


# ---------------------------------------------------------------------------
# stream_complete()
# ---------------------------------------------------------------------------


class TestStreamComplete:
    def _mock_httpx_stream(self, lines: list[str], status_code: int = 200):
        """Return a mock httpx.AsyncClient whose .stream() yields given SSE lines."""

        async def fake_aiter_lines():
            for line in lines:
                yield line

        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.is_success = status_code < 300
        mock_response.aiter_lines = fake_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        return mock_client

    def _sse_line(self, content: str) -> str:
        data = json.dumps({"choices": [{"delta": {"content": content}}]})
        return f"data: {data}"

    @pytest.mark.asyncio
    async def test_stream_complete_yields_content(self):
        p = _make_provider()
        lines = [
            self._sse_line("Hello "),
            self._sse_line("world"),
            "data: [DONE]",
        ]
        mock_client = self._mock_httpx_stream(lines)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in p.stream_complete("hi"):
                chunks.append(chunk)

        assert chunks == ["Hello ", "world"]

    @pytest.mark.asyncio
    async def test_stream_complete_skips_non_data_lines(self):
        p = _make_provider()
        lines = [
            ": keep-alive",
            "event: message",
            self._sse_line("chunk"),
            "data: [DONE]",
        ]
        mock_client = self._mock_httpx_stream(lines)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in p.stream_complete("hi"):
                chunks.append(chunk)

        assert chunks == ["chunk"]

    @pytest.mark.asyncio
    async def test_stream_complete_stops_at_done(self):
        p = _make_provider()
        lines = [
            self._sse_line("before"),
            "data: [DONE]",
            self._sse_line("after"),  # should not be yielded
        ]
        mock_client = self._mock_httpx_stream(lines)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in p.stream_complete("hi"):
                chunks.append(chunk)

        assert chunks == ["before"]

    @pytest.mark.asyncio
    async def test_stream_complete_skips_malformed_json(self):
        p = _make_provider()
        lines = [
            "data: not-valid-json",
            self._sse_line("valid"),
            "data: [DONE]",
        ]
        mock_client = self._mock_httpx_stream(lines)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in p.stream_complete("hi"):
                chunks.append(chunk)

        assert chunks == ["valid"]

    @pytest.mark.asyncio
    async def test_stream_complete_skips_null_content(self):
        p = _make_provider()
        null_delta = json.dumps({"choices": [{"delta": {}}]})
        lines = [
            f"data: {null_delta}",
            self._sse_line("real"),
            "data: [DONE]",
        ]
        mock_client = self._mock_httpx_stream(lines)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in p.stream_complete("hi"):
                chunks.append(chunk)

        assert chunks == ["real"]

    @pytest.mark.asyncio
    async def test_stream_complete_raises_on_401(self):
        p = _make_provider()

        async def failing_aiter_lines():
            return
            yield  # pragma: no cover

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.is_success = False
        mock_response.json.return_value = {"error": {"message": "bad key"}}
        mock_response.text = "bad key"
        mock_response.aiter_lines = failing_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(GrokAuthError):
                async for _ in p.stream_complete("hi"):
                    pass

    @pytest.mark.asyncio
    async def test_stream_complete_sets_stream_true_in_payload(self):
        p = _make_provider()
        lines = ["data: [DONE]"]
        mock_client = self._mock_httpx_stream(lines)

        with patch("httpx.AsyncClient", return_value=mock_client):
            async for _ in p.stream_complete("hi"):
                pass

        payload = mock_client.stream.call_args[1]["json"]
        assert payload["stream"] is True


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


class TestEmbed:
    @pytest.mark.asyncio
    async def test_embed_raises_not_implemented(self):
        p = _make_provider()
        with pytest.raises(NotImplementedError, match="Grok"):
            await p.embed("text")


# ---------------------------------------------------------------------------
# count_tokens()
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_count_tokens_basic(self):
        p = _make_provider()
        assert p.count_tokens("a" * 40) == 10

    def test_count_tokens_minimum_one(self):
        p = _make_provider()
        assert p.count_tokens("") == 1

    def test_count_tokens_single_char(self):
        p = _make_provider()
        assert p.count_tokens("X") == 1


# ---------------------------------------------------------------------------
# estimate_cost()
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_estimate_cost_known_model(self):
        p = _make_provider()
        cost = p.estimate_cost(1_000_000, 1_000_000, model="grok-2-latest")
        assert cost["input_cost"] == pytest.approx(2.0)
        assert cost["output_cost"] == pytest.approx(10.0)
        assert cost["total_cost"] == pytest.approx(12.0)

    def test_estimate_cost_defaults_to_configured_model(self):
        p = _make_provider({"model": "grok-3"})
        cost = p.estimate_cost(1_000_000, 1_000_000)
        assert cost["input_cost"] == pytest.approx(3.0)
        assert cost["output_cost"] == pytest.approx(15.0)

    def test_estimate_cost_unknown_model_falls_back_to_grok2(self):
        p = _make_provider()
        cost = p.estimate_cost(1_000_000, 1_000_000, model="grok-99-ultra")
        # Falls back to grok-2-latest rates
        assert cost["input_cost"] == pytest.approx(2.0)

    def test_estimate_cost_zero_tokens(self):
        p = _make_provider()
        cost = p.estimate_cost(0, 0, model="grok-3")
        assert cost["total_cost"] == 0.0

    def test_estimate_cost_keys_present(self):
        p = _make_provider()
        cost = p.estimate_cost(100, 50)
        assert {"input_cost", "output_cost", "total_cost"} == set(cost.keys())

    def test_estimate_cost_fast_model(self):
        p = _make_provider()
        cost = p.estimate_cost(1_000_000, 1_000_000, model="grok-3-fast")
        assert cost["input_cost"] == pytest.approx(5.0)
        assert cost["output_cost"] == pytest.approx(25.0)
