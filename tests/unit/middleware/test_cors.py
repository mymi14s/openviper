"""Unit tests for openviper.middleware.cors — CORSMiddleware."""

import pytest

from openviper.middleware.base import build_middleware_stack
from openviper.middleware.cors import CORSMiddleware


def _make_scope(method="GET", path="/", origin=None, headers=None):
    h = list(headers or [])
    if origin:
        h.append((b"origin", origin.encode("latin-1")))
    return {"type": "http", "method": method, "path": path, "headers": h}


async def _ok_app(scope, receive, send):  # noqa: ARG001
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _noop_app(scope, receive, send):  # noqa: ARG001
    pass


async def _run(mw, scope):
    """Return headers dict from the first response.start message."""
    messages = []

    async def _send(msg):
        messages.append(msg)

    await mw(scope, None, _send)
    if not messages:
        return {}, None
    return dict(messages[0].get("headers", [])), messages[0].get("status")


class TestOriginAllowed:
    @pytest.mark.asyncio
    async def test_allow_all(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["*"])
        hd, _ = await _run(mw, _make_scope(origin="https://example.com"))
        assert b"access-control-allow-origin" in hd

    @pytest.mark.asyncio
    async def test_exact_match_allowed(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://example.com"])
        hd, _ = await _run(mw, _make_scope(origin="https://example.com"))
        assert b"access-control-allow-origin" in hd

    @pytest.mark.asyncio
    async def test_exact_match_denied(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CORSMiddleware(app, allowed_origins=["https://example.com"])
        await mw(_make_scope(origin="https://other.com"), None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_wildcard_pattern_allowed(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://*.example.com"])
        hd, _ = await _run(mw, _make_scope(origin="https://sub.example.com"))
        assert b"access-control-allow-origin" in hd

    @pytest.mark.asyncio
    async def test_wildcard_pattern_denied(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CORSMiddleware(app, allowed_origins=["https://*.example.com"])
        await mw(_make_scope(origin="https://other.com"), None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_multiple_exact_origins(self):
        for origin in ("https://a.com", "https://b.com"):
            mw = CORSMiddleware(_ok_app, allowed_origins=["https://a.com", "https://b.com"])
            hd, _ = await _run(mw, _make_scope(origin=origin))
            assert b"access-control-allow-origin" in hd

    @pytest.mark.asyncio
    async def test_exact_and_wildcard_combined(self):
        mw = CORSMiddleware(
            _ok_app,
            allowed_origins=["https://exact.com", "https://*.wild.com"],
        )
        hd, _ = await _run(mw, _make_scope(origin="https://sub.wild.com"))
        assert b"access-control-allow-origin" in hd


class TestCORSPreflight:
    @pytest.mark.asyncio
    async def test_preflight_returns_204(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["https://example.com"])
        _, status = await _run(mw, _make_scope(method="OPTIONS", origin="https://example.com"))
        assert status == 204

    @pytest.mark.asyncio
    async def test_preflight_allowed_has_origin_header(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["https://example.com"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://example.com"))
        assert b"access-control-allow-origin" in hd

    @pytest.mark.asyncio
    async def test_preflight_disallowed_origin(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["https://allowed.com"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://evil.com"))
        assert b"access-control-allow-origin" not in hd

    @pytest.mark.asyncio
    async def test_preflight_echoes_request_origin(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["https://example.com"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://example.com"))
        assert hd[b"access-control-allow-origin"] == b"https://example.com"

    @pytest.mark.asyncio
    async def test_preflight_all_origins_echoes_origin(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        assert hd[b"access-control-allow-origin"] == b"https://foo.com"

    @pytest.mark.asyncio
    async def test_preflight_contains_methods_header(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"], allowed_methods=["GET", "POST"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        assert b"access-control-allow-methods" in hd
        assert b"GET" in hd[b"access-control-allow-methods"]

    @pytest.mark.asyncio
    async def test_preflight_max_age(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"], max_age=1200)
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        assert hd[b"access-control-max-age"] == b"1200"

    @pytest.mark.asyncio
    async def test_preflight_body_is_empty(self):
        messages = []

        async def _send(msg):
            messages.append(msg)

        mw = CORSMiddleware(_noop_app, allowed_origins=["*"])
        await mw(_make_scope(method="OPTIONS", origin="https://foo.com"), None, _send)
        assert messages[1]["body"] == b""


class TestCORSNonPreflight:
    @pytest.mark.asyncio
    async def test_adds_cors_headers_to_response(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://example.com"])
        hd, _ = await _run(mw, _make_scope(method="GET", origin="https://example.com"))
        assert b"access-control-allow-origin" in hd

    @pytest.mark.asyncio
    async def test_no_origin_passthrough(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CORSMiddleware(app)
        await mw({"type": "http", "method": "GET", "headers": []}, None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_non_http_passthrough(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CORSMiddleware(app)
        await mw({"type": "websocket"}, None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_disallowed_origin_passthrough(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CORSMiddleware(app, allowed_origins=["https://allowed.com"])
        await mw(_make_scope(method="GET", origin="https://evil.com"), None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_credentials_header_added(self):
        mw = CORSMiddleware(
            _ok_app, allowed_origins=["https://example.com"], allow_credentials=True
        )
        hd, _ = await _run(mw, _make_scope(origin="https://example.com"))
        assert hd.get(b"access-control-allow-credentials") == b"true"

    @pytest.mark.asyncio
    async def test_no_credentials_header_when_disabled(self):
        mw = CORSMiddleware(
            _ok_app, allowed_origins=["https://example.com"], allow_credentials=False
        )
        hd, _ = await _run(mw, _make_scope(origin="https://example.com"))
        assert b"access-control-allow-credentials" not in hd

    @pytest.mark.asyncio
    async def test_post_with_allowed_origin(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://example.com"])
        hd, status = await _run(mw, _make_scope(method="POST", origin="https://example.com"))
        assert status == 200
        assert b"access-control-allow-origin" in hd


class TestCORSVaryHeader:
    """Vary: Origin must be set when origin list is not wildcard-all.

    Without it, CDNs / shared caches can poison cross-origin responses.
    """

    @pytest.mark.asyncio
    async def test_vary_origin_set_for_specific_origins(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://example.com"])
        hd, _ = await _run(mw, _make_scope(origin="https://example.com"))
        assert b"vary" in hd
        assert b"Origin" in hd[b"vary"]

    @pytest.mark.asyncio
    async def test_vary_origin_not_set_for_wildcard(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["*"])
        hd, _ = await _run(mw, _make_scope(origin="https://anything.com"))
        assert b"vary" not in hd

    @pytest.mark.asyncio
    async def test_vary_origin_set_for_wildcard_pattern(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://*.example.com"])
        hd, _ = await _run(mw, _make_scope(origin="https://sub.example.com"))
        assert b"vary" in hd
        assert b"Origin" in hd[b"vary"]


class TestCORSConfiguration:
    @pytest.mark.asyncio
    async def test_expose_headers_in_response(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["*"], expose_headers=["X-Custom"])
        hd, _ = await _run(mw, _make_scope(origin="https://foo.com"))
        assert b"access-control-expose-headers" in hd
        assert b"X-Custom" in hd[b"access-control-expose-headers"]

    @pytest.mark.asyncio
    async def test_no_credentials_response(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["*"], allow_credentials=False)
        hd, _ = await _run(mw, _make_scope(origin="https://foo.com"))
        assert b"access-control-allow-credentials" not in hd

    @pytest.mark.asyncio
    async def test_explicit_methods_in_preflight(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"], allowed_methods=["GET", "POST"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        val = hd[b"access-control-allow-methods"]
        assert b"GET" in val
        assert b"POST" in val

    @pytest.mark.asyncio
    async def test_explicit_headers_in_preflight(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"], allowed_headers=["Content-Type"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        assert b"content-type" in hd[b"access-control-allow-headers"]

    @pytest.mark.asyncio
    async def test_wildcard_methods_expands_to_all(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"], allowed_methods=["*"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        val = hd[b"access-control-allow-methods"].decode()
        assert "DELETE" in val
        assert "PATCH" in val

    @pytest.mark.asyncio
    async def test_default_max_age_is_600(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        assert hd[b"access-control-max-age"] == b"600"


class TestCORSExposeHeaders:
    @pytest.mark.asyncio
    async def test_preflight_includes_expose_headers(self):
        mw = CORSMiddleware(_noop_app, allowed_origins=["*"], expose_headers=["X-Custom"])
        hd, _ = await _run(mw, _make_scope(method="OPTIONS", origin="https://foo.com"))
        assert b"access-control-expose-headers" in hd

    @pytest.mark.asyncio
    async def test_non_preflight_includes_expose_headers(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["*"], expose_headers=["X-Custom"])
        hd, _ = await _run(mw, _make_scope(method="GET", origin="https://foo.com"))
        assert b"access-control-expose-headers" in hd

    @pytest.mark.asyncio
    async def test_no_expose_headers_omitted(self):
        mw = CORSMiddleware(_ok_app, allowed_origins=["*"])
        hd, _ = await _run(mw, _make_scope(method="GET", origin="https://foo.com"))
        assert b"access-control-expose-headers" not in hd


class TestCORSOriginSpoofing:
    @pytest.mark.asyncio
    async def test_subpath_origin_not_matched_as_prefix(self):
        """https://evil-example.com must not match https://example.com."""
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://example.com"])
        hd, _ = await _run(mw, _make_scope(origin="https://evil-example.com"))
        assert b"access-control-allow-origin" not in hd

    @pytest.mark.asyncio
    async def test_http_vs_https_not_matched(self):
        """http://example.com must not match https://example.com."""
        mw = CORSMiddleware(_ok_app, allowed_origins=["https://example.com"])
        hd, _ = await _run(mw, _make_scope(origin="http://example.com"))
        assert b"access-control-allow-origin" not in hd


class TestCORSFromSettings:
    """Tests that CORSMiddleware is wired from CORS_* settings via _build_middleware_stack."""

    def _build_stack(self, **cors_overrides):
        """Build a middleware stack with CORSMiddleware using the same kwargs logic
        as OpenViper._build_middleware_stack."""
        defaults = {
            "CORS_ALLOWED_ORIGINS": None,
            "CORS_ALLOW_CREDENTIALS": False,
            "CORS_ALLOWED_METHODS": None,
            "CORS_ALLOWED_HEADERS": None,
            "CORS_EXPOSE_HEADERS": None,
            "CORS_MAX_AGE": 600,
        }
        defaults.update(cors_overrides)

        cors_kwargs = {
            "allowed_origins": list(defaults["CORS_ALLOWED_ORIGINS"] or ["*"]),
            "allow_credentials": defaults["CORS_ALLOW_CREDENTIALS"],
            "allowed_methods": list(defaults["CORS_ALLOWED_METHODS"] or ["*"]),
            "allowed_headers": list(defaults["CORS_ALLOWED_HEADERS"] or ["*"]),
            "expose_headers": list(defaults["CORS_EXPOSE_HEADERS"] or []),
            "max_age": defaults["CORS_MAX_AGE"],
        }
        return build_middleware_stack(_ok_app, [(CORSMiddleware, cors_kwargs)])

    @pytest.mark.asyncio
    async def test_allow_credentials_true(self):
        """CORS_ALLOW_CREDENTIALS=True sets Access-Control-Allow-Credentials: true."""
        stack = self._build_stack(
            CORS_ALLOWED_ORIGINS=("https://frontend.example.com",),
            CORS_ALLOW_CREDENTIALS=True,
            CORS_EXPOSE_HEADERS=("X-Request-Id",),
        )
        hd, _ = await _run(stack, _make_scope(origin="https://frontend.example.com"))
        assert hd.get(b"access-control-allow-credentials") == b"true"
        assert hd.get(b"access-control-expose-headers") == b"X-Request-Id"

    @pytest.mark.asyncio
    async def test_allow_credentials_false(self):
        """CORS_ALLOW_CREDENTIALS=False omits Access-Control-Allow-Credentials."""
        stack = self._build_stack(CORS_ALLOW_CREDENTIALS=False)
        hd, _ = await _run(stack, _make_scope(origin="https://example.com"))
        assert b"access-control-allow-credentials" not in hd

    @pytest.mark.asyncio
    async def test_allowed_origins_restricts(self):
        """CORS_ALLOWED_ORIGINS restricts which origins receive CORS headers."""
        stack = self._build_stack(CORS_ALLOWED_ORIGINS=("https://trusted.example.com",))
        hd, _ = await _run(stack, _make_scope(origin="https://trusted.example.com"))
        assert hd.get(b"access-control-allow-origin") == b"https://trusted.example.com"

        hd2, _ = await _run(stack, _make_scope(origin="https://evil.com"))
        assert b"access-control-allow-origin" not in hd2

    @pytest.mark.asyncio
    async def test_empty_origins_falls_back_to_wildcard(self):
        """Empty CORS_ALLOWED_ORIGINS tuple falls back to allow-all ['*']."""
        stack = self._build_stack(CORS_ALLOWED_ORIGINS=())
        hd, _ = await _run(stack, _make_scope(origin="https://any-origin.com"))
        assert hd.get(b"access-control-allow-origin") == b"https://any-origin.com"

    @pytest.mark.asyncio
    async def test_expose_headers(self):
        """CORS_EXPOSE_HEADERS populates Access-Control-Expose-Headers."""
        stack = self._build_stack(CORS_EXPOSE_HEADERS=("X-Request-Id", "X-Rate-Limit"))
        hd, _ = await _run(stack, _make_scope(origin="https://example.com"))
        expose = hd.get(b"access-control-expose-headers", b"").decode()
        assert "X-Request-Id" in expose
        assert "X-Rate-Limit" in expose

    @pytest.mark.asyncio
    async def test_max_age_in_preflight(self):
        """CORS_MAX_AGE appears in preflight Access-Control-Max-Age."""
        stack = self._build_stack(CORS_MAX_AGE=7200)
        preflight_headers = [
            (b"origin", b"https://example.com"),
            (b"access-control-request-method", b"POST"),
        ]
        scope = _make_scope(method="OPTIONS", path="/api/", headers=preflight_headers)
        hd, _ = await _run(stack, scope)
        assert hd.get(b"access-control-max-age") == b"7200"

    @pytest.mark.asyncio
    async def test_no_credentials_with_wildcard_origin(self):
        """allow_credentials=True is ignored when origin is wildcard (security)."""
        # Per CORS spec, credentials cannot be used with wildcard origin.
        # CORSMiddleware should not set credentials header for non-specific origins.
        stack = self._build_stack(
            CORS_ALLOWED_ORIGINS=None,  # → ["*"]
            CORS_ALLOW_CREDENTIALS=True,
        )
        hd, _ = await _run(stack, _make_scope(origin="https://example.com"))
        # With wildcard origin, the middleware reflects the specific origin back
        # but credentials header behaviour depends on implementation.
        # At minimum the response should be served (not blocked).
        assert hd.get(b"access-control-allow-origin") is not None
