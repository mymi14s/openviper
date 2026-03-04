import json

import pytest

from openviper.middleware.csrf import (
    CSRFMiddleware,
    _generate_csrf_token,
    _mask_csrf_token,
    _verify_csrf_token,
)


def test_csrf_crypto_utils():
    token = _generate_csrf_token()
    assert len(token) == 64

    secret = "my-secret-key"
    masked = _mask_csrf_token(token, secret)
    assert len(masked) == 80  # 16 salt + 64 sig

    assert _verify_csrf_token(token, masked, secret) is True

    # Tampered validation
    assert _verify_csrf_token(token, masked[:-1] + "0", secret) is False
    assert _verify_csrf_token("other_token", masked, secret) is False
    assert _verify_csrf_token(token, "too_short", secret) is False


@pytest.mark.asyncio
async def test_csrf_middleware_pass_safe():
    calls = []

    async def dummy_app(scope, receive, send):
        calls.append("passed")

    mw = CSRFMiddleware(dummy_app, secret="sec")

    # Non-http
    await mw({"type": "websocket"}, None, None)
    assert len(calls) == 1

    # Safe method
    await mw({"type": "http", "method": "GET", "path": "/"}, None, None)
    assert len(calls) == 2

    # Exempt path
    mw._exempt_paths = {"/api/webhook"}
    await mw({"type": "http", "method": "POST", "path": "/api/webhook"}, None, None)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_csrf_middleware_block_missing():
    mw = CSRFMiddleware(None, secret="sec")

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    # Missing cookie and header
    await mw({"type": "http", "method": "POST"}, None, fake_send)
    assert sends[0]["status"] == 403
    body = json.loads(sends[1]["body"].decode("utf-8"))
    assert body["detail"] == "CSRF verification failed."


@pytest.mark.asyncio
async def test_csrf_middleware_success():
    calls = []

    async def dummy_app(scope, receive, send):
        calls.append("passed")

    mw = CSRFMiddleware(dummy_app, secret="my-secret")
    token = _generate_csrf_token()
    masked = _mask_csrf_token(token, "my-secret")

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (b"cookie", f"csrftoken={token}".encode("latin-1")),
            (b"x-csrftoken", masked.encode("latin-1")),
        ],
    }

    await mw(scope, None, None)
    assert calls == ["passed"]


def test_csrf_middleware_secret_fallback():
    class MockSettings:
        SECRET_KEY = "settings-secret"

    import sys
    from unittest.mock import patch

    mw = CSRFMiddleware(None)
    with patch("openviper.middleware.csrf.settings", MockSettings):
        assert mw._get_secret() == "settings-secret"

    with patch("openviper.middleware.csrf.settings", None):
        assert mw._get_secret() == "fallback-secret"
