"""Shared fixtures for the OpenViper TestKit unit tests."""

from __future__ import annotations

import pytest

from openviper.app import OpenViper
from openviper.http.response import JSONResponse
from openviper.testing.settings import override_openviper_settings

# Hosts that the security middleware must allow during TestKit tests.
# The test base URL is http://testserver; api.test is used in custom-URL tests.
_ALLOWED_TEST_HOSTS: tuple[str, ...] = ("testserver", "api.test", "localhost", "127.0.0.1")


@pytest.fixture
def allowed_hosts() -> tuple[str, ...]:
    """Return the host whitelist used by TestKit client tests."""
    return _ALLOWED_TEST_HOSTS


@pytest.fixture
def minimal_app() -> OpenViper:
    """Return a minimal OpenViper app with a /status route and multi-method /m route."""
    app = OpenViper(title="TestKitApp")

    @app.get("/status")
    async def get_status(request: object) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.route("/m", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def multi_handler(request: object) -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


@pytest.fixture
def permissive_settings():
    """Context manager that relaxes ALLOWED_HOSTS for the duration of a test.

    Use as a fixture when the test exercises the test client and you want the
    security middleware to accept requests from ``testserver``.
    """
    return lambda: override_openviper_settings(ALLOWED_HOSTS=_ALLOWED_TEST_HOSTS)
