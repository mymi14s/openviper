"""Unit tests for openviper.middleware.csrf — token generation, validation, middleware."""

import json
from unittest.mock import patch

import pytest

from openviper.middleware.csrf import (
    CSRFMiddleware,
    _extract_cookie_value,
    _generate_csrf_token,
    _mask_csrf_token,
    _verify_csrf_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope(method="POST", path="/update", headers=None):
    return {"type": "http", "method": method, "path": path, "headers": list(headers or [])}


async def _collect_status(mw, scope):
    messages = []

    async def send(msg):
        messages.append(msg)

    await mw(scope, None, send)
    return messages[0]["status"] if messages else None


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------


class TestCSRFTokenGeneration:
    def test_generates_hex_string(self):
        token = _generate_csrf_token()
        assert len(token) == 64
        int(token, 16)

    def test_unique_tokens(self):
        tokens = {_generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100


# ---------------------------------------------------------------------------
# Masking / verification
# ---------------------------------------------------------------------------


class TestCSRFTokenMasking:
    def test_mask_produces_96_char_string(self):
        masked = _mask_csrf_token(_generate_csrf_token(), "secret")
        assert len(masked) == 96  # 32 hex (16 bytes salt) + 64 hex (SHA256)

    def test_verification_roundtrip(self):
        secret = "my-secret-key"
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, secret)
        assert _verify_csrf_token(token, masked, secret)

    def test_verification_fails_wrong_secret(self):
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, "correct-secret")
        assert not _verify_csrf_token(token, masked, "wrong-secret")

    def test_verification_fails_short_token(self):
        assert not _verify_csrf_token("cookie", "short", "secret")

    def test_verification_fails_wrong_token(self):
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, "secret")
        corrupted = masked[:16] + "0" * 64
        assert not _verify_csrf_token(token, corrupted, "secret")

    def test_verification_constant_time(self):
        """_verify_csrf_token must use compare_digest (not ==) — ensure it handles
        same-length but wrong-value inputs without short-circuiting."""
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, "secret")
        # Flip the last char of the signature portion
        wrong = masked[:-1] + ("0" if masked[-1] != "0" else "1")
        assert not _verify_csrf_token(token, wrong, "secret")

    def test_different_salts_same_token(self):
        """Two masks of the same token must produce different strings."""
        token = _generate_csrf_token()
        m1 = _mask_csrf_token(token, "secret")
        m2 = _mask_csrf_token(token, "secret")
        assert m1 != m2  # different random salt each time

    def test_mask_with_empty_secret_still_produces_96_chars(self):
        """Empty secret is allowed at generation time (secret enforcement is middleware's job)."""
        masked = _mask_csrf_token(_generate_csrf_token(), "")
        assert len(masked) == 96  # 32 hex (16 bytes salt) + 64 hex (SHA256)


# ---------------------------------------------------------------------------
# Cookie extraction
# ---------------------------------------------------------------------------


class TestCookieExtraction:
    def test_extracts_correct_cookie(self):
        assert (
            _extract_cookie_value("session=abc; csrftoken=xyz123; other=val", "csrftoken")
            == "xyz123"
        )

    def test_missing_cookie(self):
        assert _extract_cookie_value("session=abc; other=val", "csrftoken") == ""

    def test_empty_header(self):
        assert _extract_cookie_value("", "csrftoken") == ""

    def test_first_cookie(self):
        assert _extract_cookie_value("csrftoken=first; other=second", "csrftoken") == "first"

    def test_no_prefix_match(self):
        """'notcsrftoken=x' must not match 'csrftoken'."""
        assert _extract_cookie_value("notcsrftoken=x", "csrftoken") == ""

    def test_cookie_with_spaces_around_semicolon(self):
        assert _extract_cookie_value("a=1 ;  csrftoken=tok ; b=2", "csrftoken") == "tok"

    def test_only_matching_cookie(self):
        assert _extract_cookie_value("csrftoken=solo", "csrftoken") == "solo"


# ---------------------------------------------------------------------------
# Middleware: safe methods
# ---------------------------------------------------------------------------


class TestCSRFMiddlewareSafeMethods:
    @pytest.mark.asyncio
    async def test_get_passes_through(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append(scope["method"])

        mw = CSRFMiddleware(app, secret="s")
        await mw(_make_scope(method="GET"), None, None)
        assert "GET" in calls

    @pytest.mark.asyncio
    async def test_head_passes_through(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CSRFMiddleware(app, secret="s")
        await mw(_make_scope(method="HEAD"), None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_options_passes_through(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CSRFMiddleware(app, secret="s")
        await mw(_make_scope(method="OPTIONS"), None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_trace_requires_csrf(self):
        """TRACE is no longer a safe method - it requires CSRF validation."""

        async def mock_send(message):
            pass

        mw = CSRFMiddleware(lambda s, r, se: None, secret="s")
        # Without CSRF cookie/header, TRACE should fail
        response_sent = []

        async def capture_send(message):
            response_sent.append(message)

        await mw(_make_scope(method="TRACE"), None, capture_send)
        # Should send a 403 response
        assert any(r.get("status") == 403 for r in response_sent if isinstance(r, dict))

    @pytest.mark.asyncio
    async def test_non_http_passes_through(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CSRFMiddleware(app, secret="s")
        await mw({"type": "websocket"}, None, None)
        assert "app" in calls


# ---------------------------------------------------------------------------
# Middleware: exempt paths
# ---------------------------------------------------------------------------


class TestCSRFExemptPaths:
    @pytest.mark.asyncio
    async def test_exempt_path_skips_validation(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        mw = CSRFMiddleware(app, secret="s", exempt_paths=["/api/webhook"])
        await mw(_make_scope(path="/api/webhook"), None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_non_exempt_path_requires_token(self):
        status = await _collect_status(
            CSRFMiddleware(lambda *a: None, secret="s", exempt_paths=["/api/webhook"]),
            _make_scope(path="/other"),
        )
        assert status == 403

    @pytest.mark.asyncio
    async def test_multiple_exempt_paths(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append(scope["path"])

        mw = CSRFMiddleware(app, secret="s", exempt_paths=["/a", "/b"])
        for path in ("/a", "/b"):
            await mw(_make_scope(path=path), None, None)
        assert "/a" in calls
        assert "/b" in calls


# ---------------------------------------------------------------------------
# Middleware: POST without token → 403
# ---------------------------------------------------------------------------


class TestCSRFMiddlewareValidation:
    @pytest.mark.asyncio
    async def test_post_without_csrf_returns_403(self):
        status = await _collect_status(
            CSRFMiddleware(lambda *a: None, secret="s"),
            _make_scope(headers=[]),
        )
        assert status == 403

    @pytest.mark.asyncio
    async def test_post_with_cookie_only_returns_403(self):
        token = _generate_csrf_token()
        scope = _make_scope(headers=[(b"cookie", f"csrftoken={token}".encode())])
        status = await _collect_status(CSRFMiddleware(lambda *a: None, secret="s"), scope)
        assert status == 403

    @pytest.mark.asyncio
    async def test_post_with_header_only_returns_403(self):
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, "s")
        scope = _make_scope(headers=[(b"x-csrftoken", masked.encode())])
        status = await _collect_status(CSRFMiddleware(lambda *a: None, secret="s"), scope)
        assert status == 403

    @pytest.mark.asyncio
    async def test_valid_csrf_passes_through(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        secret = "test-secret"
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, secret)
        scope = _make_scope(
            headers=[
                (b"cookie", f"csrftoken={token}".encode()),
                (b"x-csrftoken", masked.encode()),
            ]
        )
        await CSRFMiddleware(app, secret=secret)(scope, None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_403(self):
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, "other-secret")
        scope = _make_scope(
            headers=[
                (b"cookie", f"csrftoken={token}".encode()),
                (b"x-csrftoken", masked.encode()),
            ]
        )
        status = await _collect_status(
            CSRFMiddleware(lambda *a: None, secret="correct-secret"), scope
        )
        assert status == 403

    @pytest.mark.asyncio
    async def test_put_requires_token(self):
        status = await _collect_status(
            CSRFMiddleware(lambda *a: None, secret="s"),
            _make_scope(method="PUT"),
        )
        assert status == 403

    @pytest.mark.asyncio
    async def test_delete_requires_token(self):
        status = await _collect_status(
            CSRFMiddleware(lambda *a: None, secret="s"),
            _make_scope(method="DELETE"),
        )
        assert status == 403

    @pytest.mark.asyncio
    async def test_patch_requires_token(self):
        status = await _collect_status(
            CSRFMiddleware(lambda *a: None, secret="s"),
            _make_scope(method="PATCH"),
        )
        assert status == 403


# ---------------------------------------------------------------------------
# Header case-insensitivity
# ---------------------------------------------------------------------------


class TestCSRFHeaderCaseInsensitivity:
    @pytest.mark.asyncio
    async def test_mixed_case_header_accepted(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        secret = "s"
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, secret)
        scope = _make_scope(
            headers=[
                (b"Cookie", f"csrftoken={token}".encode()),
                (b"X-CSRFToken", masked.encode()),
            ]
        )
        await CSRFMiddleware(app, secret=secret)(scope, None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_uppercase_header_accepted(self):
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("app")

        secret = "s"
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, secret)
        scope = _make_scope(
            headers=[
                (b"COOKIE", f"csrftoken={token}".encode()),
                (b"X-CSRFTOKEN", masked.encode()),
            ]
        )
        await CSRFMiddleware(app, secret=secret)(scope, None, None)
        assert "app" in calls


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------


class TestCSRFSecretFallback:
    @pytest.mark.asyncio
    async def test_custom_secret_accepted(self):
        """Middleware configured with explicit secret must process valid tokens."""
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("ok")

        secret = "custom-secret"
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, secret)
        scope = _make_scope(
            headers=[
                (b"cookie", f"csrftoken={token}".encode()),
                (b"x-csrftoken", masked.encode()),
            ]
        )
        await CSRFMiddleware(app, secret=secret)(scope, None, None)
        assert "ok" in calls

    @pytest.mark.asyncio
    async def test_missing_settings_secret_key_returns_500(self):
        """When settings has no SECRET_KEY and no explicit secret, middleware raises."""
        messages = []

        async def send(msg):
            messages.append(msg)

        async def app(scope, receive, send):  # noqa: ARG001
            pass

        mw = CSRFMiddleware(app, secret="")
        scope = _make_scope(headers=[])

        mock_settings = patch("openviper.middleware.csrf.settings")
        with mock_settings as ms:
            del ms.SECRET_KEY
            with pytest.raises(RuntimeError, match="requires settings.SECRET_KEY"):
                await mw(scope, None, send)

    @pytest.mark.asyncio
    async def test_empty_settings_secret_key_raises(self):
        """Empty SECRET_KEY with no explicit secret must raise RuntimeError."""

        async def app(scope, receive, send):  # noqa: ARG001
            pass

        mw = CSRFMiddleware(app, secret="")
        scope = _make_scope(headers=[])

        with patch("openviper.middleware.csrf.settings") as ms:
            ms.SECRET_KEY = ""
            with pytest.raises(RuntimeError, match="non-empty SECRET_KEY"):
                await mw(scope, None, None)

    @pytest.mark.asyncio
    async def test_settings_secret_key_used_when_no_explicit_secret(self):
        """settings.SECRET_KEY must be used when no explicit secret is given."""
        calls = []

        async def app(scope, receive, send):  # noqa: ARG001
            calls.append("ok")

        secret = "from-settings"
        token = _generate_csrf_token()
        masked = _mask_csrf_token(token, secret)
        scope = _make_scope(
            headers=[
                (b"cookie", f"csrftoken={token}".encode()),
                (b"x-csrftoken", masked.encode()),
            ]
        )
        with patch("openviper.middleware.csrf.settings") as ms:
            ms.SECRET_KEY = secret
            await CSRFMiddleware(app, secret="")(scope, None, None)
        assert "ok" in calls


# ---------------------------------------------------------------------------
# 403 response body
# ---------------------------------------------------------------------------


class TestCSRFDeniedResponse:
    @pytest.mark.asyncio
    async def test_403_body_is_json(self):
        messages = []

        async def send(msg):
            messages.append(msg)

        mw = CSRFMiddleware(lambda *a: None, secret="s")
        await mw(_make_scope(), None, send)

        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        data = json.loads(body)
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_403_content_type_is_json(self):
        messages = []

        async def send(msg):
            messages.append(msg)

        mw = CSRFMiddleware(lambda *a: None, secret="s")
        await mw(_make_scope(), None, send)

        hd = dict(messages[0]["headers"])
        assert b"application/json" in hd.get(b"content-type", b"")
