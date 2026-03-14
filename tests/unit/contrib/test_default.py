"""Unit tests for openviper/contrib/default/middleware.py and landing.py."""

from __future__ import annotations

import pytest

from openviper.contrib.default.landing import LANDING_HTML
from openviper.contrib.default.middleware import (
    _404_RESPONSE,
    DefaultLandingMiddleware,
)
from tests.factories import collect_send, echo_app, make_scope

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_landing_middleware(
    debug: bool = True,
    version: str = "1.0.0",
    has_custom_root: bool = False,
) -> DefaultLandingMiddleware:
    return DefaultLandingMiddleware(
        echo_app(),
        debug=debug,
        version=version,
        has_custom_root=has_custom_root,
    )


async def noop_receive():
    return {"type": "http.disconnect"}


# ---------------------------------------------------------------------------
# LANDING_HTML
# ---------------------------------------------------------------------------


class TestLandingHTML:
    def test_is_string(self):
        assert isinstance(LANDING_HTML, str)

    def test_contains_version_placeholder(self):
        assert "{version}" in LANDING_HTML

    def test_contains_doctype(self):
        assert "<!DOCTYPE html>" in LANDING_HTML

    def test_version_replace(self):
        html = LANDING_HTML.replace("{version}", "2.0.0")
        assert "2.0.0" in html
        assert "{version}" not in html


# ---------------------------------------------------------------------------
# DefaultLandingMiddleware
# ---------------------------------------------------------------------------


class TestDefaultLandingMiddleware:
    @pytest.mark.asyncio
    async def test_serves_landing_on_root_get_in_debug(self):
        mw = make_landing_middleware(debug=True, has_custom_root=False)
        scope = make_scope(path="/", method="GET")
        messages = await collect_send(scope, noop_receive, mw)
        starts = [m for m in messages if m["type"] == "http.response.start"]
        assert starts[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_serves_404_on_root_get_in_production(self):
        mw = make_landing_middleware(debug=False, has_custom_root=False)
        scope = make_scope(path="/", method="GET")
        messages = await collect_send(scope, noop_receive, mw)
        starts = [m for m in messages if m["type"] == "http.response.start"]
        assert starts[0]["status"] == 404

    @pytest.mark.asyncio
    async def test_passes_through_when_has_custom_root(self):
        inner_called = []

        async def inner_app(scope, receive, send):
            inner_called.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"custom"})

        mw = DefaultLandingMiddleware(inner_app, debug=True, has_custom_root=True)
        scope = make_scope(path="/", method="GET")
        await collect_send(scope, noop_receive, mw)
        assert inner_called

    @pytest.mark.asyncio
    async def test_passes_through_non_root_path(self):
        inner_called = []

        async def inner_app(scope, receive, send):
            inner_called.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = DefaultLandingMiddleware(inner_app, debug=True, has_custom_root=False)
        scope = make_scope(path="/about", method="GET")
        await collect_send(scope, noop_receive, mw)
        assert inner_called

    @pytest.mark.asyncio
    async def test_passes_through_non_get_at_root(self):
        inner_called = []

        async def inner_app(scope, receive, send):
            inner_called.append(True)
            await send({"type": "http.response.start", "status": 405, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = DefaultLandingMiddleware(inner_app, debug=True, has_custom_root=False)
        scope = make_scope(path="/", method="POST")
        await collect_send(scope, noop_receive, mw)
        assert inner_called

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self):
        inner_called = []

        async def inner_app(scope, receive, send):
            inner_called.append(True)

        mw = DefaultLandingMiddleware(inner_app, debug=True, has_custom_root=False)
        scope = {"type": "lifespan"}
        await mw(scope, noop_receive, lambda m: None)
        assert inner_called


# ---------------------------------------------------------------------------
# Caching — landing response is pre-rendered at init
# ---------------------------------------------------------------------------


class TestLandingResponseCaching:
    def test_landing_response_cached_at_init(self):
        mw = make_landing_middleware(debug=True, version="1.2.3")
        assert mw._landing_response is not None

    def test_landing_response_none_in_production(self):
        mw = make_landing_middleware(debug=False)
        assert mw._landing_response is None

    def test_landing_response_none_when_custom_root(self):
        mw = make_landing_middleware(debug=True, has_custom_root=True)
        assert mw._landing_response is None

    def test_version_embedded_in_cached_html(self):
        mw = make_landing_middleware(debug=True, version="9.9.9")
        body = mw._landing_response.body.decode()
        assert "9.9.9" in body
        assert "{version}" not in body

    @pytest.mark.asyncio
    async def test_same_response_object_served_on_repeated_requests(self):
        mw = make_landing_middleware(debug=True)
        cached = mw._landing_response
        scope = make_scope(path="/", method="GET")
        await collect_send(scope, noop_receive, mw)
        assert mw._landing_response is cached

    def test_404_response_is_module_level_singleton(self):
        assert _404_RESPONSE.status_code == 404


# ---------------------------------------------------------------------------
# XSS — version string is HTML-escaped
# ---------------------------------------------------------------------------


class TestVersionEscaping:
    def test_script_tag_escaped(self):
        mw = make_landing_middleware(debug=True, version='<script>alert("xss")</script>')
        body = mw._landing_response.body.decode()
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

    def test_html_entities_escaped(self):
        mw = make_landing_middleware(debug=True, version='a&b<c>"d')
        body = mw._landing_response.body.decode()
        assert "&amp;" in body
        assert "&lt;" in body
        assert "&gt;" in body
        assert "&quot;" in body

    def test_safe_version_unchanged(self):
        mw = make_landing_middleware(debug=True, version="1.0.0-beta.2")
        body = mw._landing_response.body.decode()
        assert "1.0.0-beta.2" in body
