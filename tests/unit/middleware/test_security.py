"""Unit tests for openviper.middleware.security — SecurityMiddleware."""

from unittest.mock import patch

import pytest

from openviper.middleware.security import SecurityMiddleware


def _make_scope(method="GET", path="/", scheme="https", host="example.com", headers=None):
    h = list(headers or [])
    if host:
        h.append((b"host", host.encode("latin-1")))
    return {"type": "http", "method": method, "path": path, "scheme": scheme, "headers": h}


def _mw(**kwargs):
    """Build a SecurityMiddleware with ALLOWED_HOSTS=["*"] and minimal settings."""
    with patch("openviper.middleware.security.settings") as ms:
        ms.ALLOWED_HOSTS = ["*"]
        ms.SECURE_BROWSER_XSS_FILTER = False
        ms.SECURE_CONTENT_SECURITY_POLICY = None
        return SecurityMiddleware(lambda *a: None, **kwargs)


async def _run(mw, scope):
    messages = []

    async def send(msg):
        messages.append(msg)

    async def app(s, r, snd):  # noqa: ARG001
        await snd({"type": "http.response.start", "status": 200, "headers": []})
        await snd({"type": "http.response.body", "body": b"ok"})

    # Rebuild with real app so headers flow through
    real_mw = SecurityMiddleware.__new__(SecurityMiddleware)
    real_mw.__dict__.update(mw.__dict__)
    real_mw.app = app
    await real_mw(scope, None, send)
    return messages


# ---------------------------------------------------------------------------
# headers added
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_adds_security_headers(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = True
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        await mw(_make_scope(), None, send)
        keys = [h[0] for h in messages[0]["headers"]]
        assert b"x-content-type-options" in keys
        assert b"x-frame-options" in keys
        assert b"referrer-policy" in keys

    @pytest.mark.asyncio
    async def test_non_http_passthrough(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        await mw({"type": "websocket"}, None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_xss_filter_header_added(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, xss_filter=True)

        await mw(_make_scope(), None, send)
        keys = [h[0] for h in messages[0]["headers"]]
        assert b"x-xss-protection" in keys

    @pytest.mark.asyncio
    async def test_content_type_nosniff_can_be_disabled(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, content_type_nosniff=False)

        await mw(_make_scope(), None, send)
        keys = [h[0] for h in messages[0]["headers"]]
        assert b"x-content-type-options" not in keys

    @pytest.mark.asyncio
    async def test_x_frame_options_deny(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, x_frame_options="DENY")

        await mw(_make_scope(), None, send)
        hd = dict(messages[0]["headers"])
        assert hd[b"x-frame-options"] == b"DENY"

    @pytest.mark.asyncio
    async def test_x_frame_options_sameorigin(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, x_frame_options="SAMEORIGIN")

        await mw(_make_scope(), None, send)
        hd = dict(messages[0]["headers"])
        assert hd[b"x-frame-options"] == b"SAMEORIGIN"


# ---------------------------------------------------------------------------
# HSTS
# ---------------------------------------------------------------------------


class TestHSTS:
    @pytest.mark.asyncio
    async def test_hsts_header_added(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(
                app, hsts_seconds=31536000, hsts_include_subdomains=True, hsts_preload=True
            )

        await mw(_make_scope(), None, send)
        hd = dict(messages[0]["headers"])
        val = hd[b"strict-transport-security"].decode()
        assert "max-age=31536000" in val
        assert "includeSubDomains" in val
        assert "preload" in val

    @pytest.mark.asyncio
    async def test_hsts_not_added_when_zero(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, hsts_seconds=0)

        await mw(_make_scope(), None, send)
        keys = [h[0] for h in messages[0]["headers"]]
        assert b"strict-transport-security" not in keys

    @pytest.mark.asyncio
    async def test_hsts_no_subdomains_or_preload(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, hsts_seconds=3600)

        await mw(_make_scope(), None, send)
        hd = dict(messages[0]["headers"])
        val = hd[b"strict-transport-security"].decode()
        assert "includeSubDomains" not in val
        assert "preload" not in val


# ---------------------------------------------------------------------------
# CSP
# ---------------------------------------------------------------------------


class TestCSP:
    @pytest.mark.asyncio
    async def test_csp_string(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, csp="default-src 'self'")

        await mw(_make_scope(), None, send)
        hd = dict(messages[0]["headers"])
        assert hd[b"content-security-policy"] == b"default-src 'self'"

    @pytest.mark.asyncio
    async def test_csp_dict(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, csp={"default-src": "'self'"})

        await mw(_make_scope(), None, send)
        hd = dict(messages[0]["headers"])
        assert b"default-src" in hd[b"content-security-policy"]

    @pytest.mark.asyncio
    async def test_csp_not_added_when_none(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, csp=None)

        await mw(_make_scope(), None, send)
        keys = [h[0] for h in messages[0]["headers"]]
        assert b"content-security-policy" not in keys


# ---------------------------------------------------------------------------
# ALLOWED_HOSTS
# ---------------------------------------------------------------------------


class TestHostAllowed:
    @pytest.mark.asyncio
    async def test_wildcard_allows_all(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        await mw(_make_scope(host="anything.com"), None, send)
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_exact_host_allowed(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["example.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        await mw(_make_scope(host="example.com"), None, send)
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_disallowed_host_returns_400(self):
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["allowed.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None)

        await mw(_make_scope(host="evil.com"), None, send)
        assert messages[0]["status"] == 400

    @pytest.mark.asyncio
    async def test_wildcard_suffix_allowed(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = [".example.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        await mw(_make_scope(host="sub.example.com"), None, send)
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_wildcard_suffix_bare_domain_allowed(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = [".example.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        await mw(_make_scope(host="example.com"), None, send)
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_port_stripped_for_host_check(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["example.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        # Host header includes port number
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "https",
            "headers": [(b"host", b"example.com:8080")],
        }
        await mw(scope, None, send)
        assert messages[0]["status"] == 200


# ---------------------------------------------------------------------------
# SSL redirect
# ---------------------------------------------------------------------------


class TestSSLRedirect:
    @pytest.mark.asyncio
    async def test_redirects_http_to_https(self):
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None, ssl_redirect=True)

        await mw(_make_scope(scheme="http", host="example.com", path="/test"), None, send)
        assert messages[0]["status"] == 301
        location = dict(messages[0]["headers"]).get(b"location", b"").decode()
        assert location.startswith("https://")

    @pytest.mark.asyncio
    async def test_ssl_redirect_preserves_path(self):
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None, ssl_redirect=True)

        await mw(_make_scope(scheme="http", host="example.com", path="/my/page"), None, send)
        location = dict(messages[0]["headers"]).get(b"location", b"").decode()
        assert "/my/page" in location

    @pytest.mark.asyncio
    async def test_ssl_redirect_with_query_string(self):
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None, ssl_redirect=True)

        scope = _make_scope(scheme="http", host="example.com", path="/test")
        scope["query_string"] = b"page=1&sort=asc"
        await mw(scope, None, send)
        location = dict(messages[0]["headers"]).get(b"location", b"").decode()
        assert "page=1" in location
        assert location.startswith("https://")

    @pytest.mark.asyncio
    async def test_no_redirect_when_already_https(self):
        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app, ssl_redirect=True)

        await mw(_make_scope(scheme="https", host="example.com"), None, send)
        assert messages[0]["status"] == 200


# ---------------------------------------------------------------------------
# CRLF injection / header injection prevention
# ---------------------------------------------------------------------------


class TestCRLFRejection:
    @pytest.mark.asyncio
    async def test_crlf_in_host_header_returns_400(self):
        """CR/LF in Host must be rejected with 400 to prevent header injection."""
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None, ssl_redirect=True)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "headers": [(b"host", b"evil.com\r\nInjected: header")],
        }
        await mw(scope, None, send)
        assert messages[0]["status"] == 400

    @pytest.mark.asyncio
    async def test_lf_only_in_host_returns_400(self):
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None, ssl_redirect=True)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "headers": [(b"host", b"evil.com\nX-Injected: yes")],
        }
        await mw(scope, None, send)
        assert messages[0]["status"] == 400

    @pytest.mark.asyncio
    async def test_clean_host_ssl_redirect_succeeds(self):
        """A clean host during SSL redirect must produce 301, not 400."""
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None, ssl_redirect=True)

        await mw(_make_scope(scheme="http", host="example.com"), None, send)
        assert messages[0]["status"] == 301


# ---------------------------------------------------------------------------
# Host from server tuple fallback
# ---------------------------------------------------------------------------


class TestHostFromServer:
    @pytest.mark.asyncio
    async def test_host_from_server_tuple(self):
        """When no Host header, server tuple should be used for host resolution."""

        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["*"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "https",
            "headers": [],
            "server": ("localhost", 8000),
        }
        await mw(scope, None, send)
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_server_tuple_host_checked_against_allowed(self):
        """Server-tuple host must still pass ALLOWED_HOSTS check."""
        messages = []

        async def send(msg):
            messages.append(msg)

        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = ["allowed.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "https",
            "headers": [],
            "server": ("evil.com", 8000),
        }
        await mw(scope, None, send)
        assert messages[0]["status"] == 400


# ---------------------------------------------------------------------------
# _get_host helper (lines 127-134)
# ---------------------------------------------------------------------------


class TestGetHostHelper:
    def _make_mw(self, allowed_hosts=("*",)):
        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = list(allowed_hosts)
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            return SecurityMiddleware(lambda *a: None)

    def test_get_host_from_header(self):
        """_get_host extracts hostname from Host header (line 129-130)."""
        mw = self._make_mw()
        scope = {"headers": [(b"host", b"example.com:8080")]}
        assert mw._get_host(scope) == "example.com"

    def test_get_host_from_header_no_port(self):
        """_get_host extracts hostname from Host header without port."""
        mw = self._make_mw()
        scope = {"headers": [(b"host", b"example.com")]}
        assert mw._get_host(scope) == "example.com"

    def test_get_host_from_server_fallback(self):
        """_get_host falls back to server tuple when no host header (line 132-133)."""
        mw = self._make_mw()
        scope = {"headers": [], "server": ("myserver.com", 80)}
        assert mw._get_host(scope) == "myserver.com"

    def test_get_host_empty_string_fallback(self):
        """_get_host returns empty string when no header or server (line 134)."""
        mw = self._make_mw()
        scope = {"headers": []}
        assert mw._get_host(scope) == ""


# ---------------------------------------------------------------------------
# _is_host_allowed wildcard exact-domain match (line 121)
# ---------------------------------------------------------------------------


class TestIsHostAllowedWildcardExact:
    def test_wildcard_matches_bare_domain(self):
        """.example.com pattern matches bare example.com via pattern[1:] (line 121)."""
        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = [".example.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None)

        # pattern = ".example.com"; pattern[1:] = "example.com" == host_lower
        assert mw._is_host_allowed("example.com") is True

    def test_wildcard_matches_subdomain(self):
        """.example.com pattern matches sub.example.com via endswith check."""
        with patch("openviper.middleware.security.settings") as ms:
            ms.ALLOWED_HOSTS = [".example.com"]
            ms.SECURE_BROWSER_XSS_FILTER = False
            ms.SECURE_CONTENT_SECURITY_POLICY = None
            mw = SecurityMiddleware(lambda *a: None)

        assert mw._is_host_allowed("sub.example.com") is True
