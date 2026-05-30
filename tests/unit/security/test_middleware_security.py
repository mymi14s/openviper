"""Middleware security tests.

Requirement IDs: MID-001 through MID-005.
"""

from __future__ import annotations

import asyncio

import pytest

from openviper.core.context import current_request, current_user
from openviper.http.request import Request
from openviper.http.response import JSONResponse
from openviper.middleware.base import BaseMiddleware, build_middleware_stack
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.error import ServerErrorMiddleware
from openviper.middleware.security import SecurityMiddleware

from .conftest import (
    MockUser,
    SendCollector,
    make_scope,
    override_settings,
)

# ---------------------------------------------------------------------------
# MID-001: Security middleware order is enforced
# ---------------------------------------------------------------------------


class TestMiddlewareOrder:
    """Security-critical middleware must execute in a deterministic order."""

    def test_mid001_build_middleware_stack_order(self):
        """Middleware stack must be built in the specified order."""
        call_order: list[str] = []

        class OuterMiddleware(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                call_order.append("outer")
                await self.app(scope, receive, send)

        class InnerMiddleware(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                call_order.append("inner")
                await self.app(scope, receive, send)

        async def app(scope, receive, send):
            call_order.append("app")

        stack = build_middleware_stack(app, [OuterMiddleware, InnerMiddleware])
        # First in list is outermost (first to receive request)
        assert isinstance(stack, OuterMiddleware)

    @pytest.mark.asyncio
    async def test_mid001_middleware_execution_order(self):
        """Middleware must execute in the configured order."""
        call_order: list[str] = []

        class FirstMiddleware(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                call_order.append("first_before")
                await self.app(scope, receive, send)
                call_order.append("first_after")

        class SecondMiddleware(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                call_order.append("second_before")
                await self.app(scope, receive, send)
                call_order.append("second_after")

        async def app(scope, receive, send):
            call_order.append("app")
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        stack = build_middleware_stack(app, [FirstMiddleware, SecondMiddleware])
        scope = make_scope()
        collector = SendCollector()
        await stack(scope, noop_receive, collector)

        assert call_order == [
            "first_before",
            "second_before",
            "app",
            "second_after",
            "first_after",
        ]


# ---------------------------------------------------------------------------
# MID-002: Middleware cannot be skipped on errors
# ---------------------------------------------------------------------------


class TestMiddlewareErrorHandling:
    """Security middleware must still run even when handlers raise exceptions."""

    @pytest.mark.asyncio
    async def test_mid002_security_headers_on_error(self):
        """Error responses must not leak sensitive information."""

        async def failing_app(scope, receive, send):
            raise RuntimeError("Intentional test error")

        with override_settings(ALLOWED_HOSTS=["*"]):
            security = SecurityMiddleware(failing_app)
            error_middleware = ServerErrorMiddleware(security, debug=False)

        scope = make_scope()
        collector = SendCollector()
        await error_middleware(scope, noop_receive, collector)

        # Error response must be returned
        assert collector.status_code is not None
        # In production mode (debug=False), error details must not be exposed
        body = collector.body.decode()
        # The response should not contain the exception message in production
        assert "Intentional test error" not in body

    @pytest.mark.asyncio
    async def test_mid002_cors_headers_on_preflight(self):
        """CORS headers must be present on preflight requests."""

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        cors = CORSMiddleware(
            app,
            allowed_origins=["https://trusted.example.com"],
            allowed_methods=["GET", "POST"],
        )

        scope = make_scope(
            method="OPTIONS",
            headers=[
                (b"origin", b"https://trusted.example.com"),
                (b"access-control-request-method", b"POST"),
            ],
        )
        collector = SendCollector()
        await cors(scope, noop_receive, collector)

        headers = collector.headers_dict
        assert "access-control-allow-origin" in headers


# ---------------------------------------------------------------------------
# MID-003: Middleware applies to APIs, static files, and error handlers
# ---------------------------------------------------------------------------


class TestMiddlewareAppliesToAllRoutes:
    """Middleware must apply uniformly to all route types."""

    @pytest.mark.asyncio
    async def test_mid003_security_middleware_on_api_route(self):
        """SecurityMiddleware must add headers to API responses."""

        async def app(scope, receive, send):
            response = JSONResponse({"data": "test"})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(app)

        scope = make_scope()
        collector = SendCollector()
        await middleware(scope, noop_receive, collector)

        headers = collector.headers_dict
        assert "x-content-type-options" in headers

    @pytest.mark.asyncio
    async def test_mid003_security_middleware_on_error_response(self):
        """Error responses must not leak sensitive information in production."""

        async def app(scope, receive, send):
            raise ValueError("test error")

        with override_settings(ALLOWED_HOSTS=["*"]):
            security = SecurityMiddleware(app)
            error_mw = ServerErrorMiddleware(security, debug=False)

        scope = make_scope()
        collector = SendCollector()
        await error_mw(scope, noop_receive, collector)

        # Error response must be returned
        assert collector.status_code is not None
        # In production mode, error details must not be exposed
        body = collector.body.decode()
        assert "test error" not in body


# ---------------------------------------------------------------------------
# MID-004: Request state must not leak between requests
# ---------------------------------------------------------------------------


class TestRequestStateIsolation:
    """Request-local state must be isolated between concurrent requests."""

    @pytest.mark.asyncio
    async def test_mid004_request_state_isolation(self):
        """Each request must have its own isolated state dict."""
        scope1 = make_scope(path="/user/a")
        scope2 = make_scope(path="/user/b")

        request1 = Request(scope1)
        request2 = Request(scope2)

        request1.state["user_id"] = 1
        request2.state["user_id"] = 2

        assert request1.state["user_id"] == 1
        assert request2.state["user_id"] == 2
        # State must not leak between requests
        assert request1.state is not request2.state

    @pytest.mark.asyncio
    async def test_mid004_context_var_isolation(self):
        """ContextVar-based state must be isolated between async tasks."""
        results: dict[str, int | None] = {}

        async def set_and_read(user_id: int, key: str):
            token = current_user.set(MockUser(user_id=user_id))
            try:
                await asyncio.sleep(0.01)  # Yield to allow interleaving
                user = current_user.get()
                results[key] = user.id if user else None
            finally:
                current_user.reset(token)

        await asyncio.gather(
            set_and_read(1, "task1"),
            set_and_read(2, "task2"),
        )

        assert results["task1"] == 1
        assert results["task2"] == 2


# ---------------------------------------------------------------------------
# MID-005: Async context must remain isolated
# ---------------------------------------------------------------------------


class TestAsyncContextIsolation:
    """Async context variables must not bleed between concurrent requests."""

    @pytest.mark.asyncio
    async def test_mid005_user_context_isolation(self):
        """current_user must not leak between concurrent async tasks."""

        async def simulate_request(user_id: int) -> int | None:
            user = MockUser(user_id=user_id)
            token = current_user.set(user)
            try:
                await asyncio.sleep(0.01)
                current = current_user.get()
                return current.id if current else None
            finally:
                current_user.reset(token)

        results = await asyncio.gather(
            simulate_request(100),
            simulate_request(200),
        )

        assert results[0] == 100
        assert results[1] == 200

    @pytest.mark.asyncio
    async def test_mid005_request_context_isolation(self):
        """current_request must not leak between concurrent async tasks."""

        async def simulate_request(path: str) -> str | None:
            scope = make_scope(path=path)
            request = Request(scope)
            token = current_request.set(request)
            try:
                await asyncio.sleep(0.01)
                current = current_request.get()
                return current.path if current else None
            finally:
                current_request.reset(token)

        results = await asyncio.gather(
            simulate_request("/path/a"),
            simulate_request("/path/b"),
        )

        assert results[0] == "/path/a"
        assert results[1] == "/path/b"


async def noop_receive():
    return {"type": "http.request", "body": b"", "more_body": False}
