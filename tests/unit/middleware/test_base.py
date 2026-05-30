"""Unit tests for openviper.middleware.base."""

import pytest

from openviper.middleware.base import BaseMiddleware, build_middleware_stack


class TestBaseMiddleware:
    @pytest.mark.asyncio
    async def test_passthrough(self):
        """BaseMiddleware just calls the next app."""
        calls = []

        async def app(scope, receive, send):
            calls.append(scope)

        mw = BaseMiddleware(app)
        await mw({"type": "http"}, None, None)
        assert len(calls) == 1

    def test_repr(self):
        async def app(scope, receive, send):
            pass

        mw = BaseMiddleware(app)
        assert "BaseMiddleware" in repr(mw)

    def test_stores_app(self):
        async def app(scope, receive, send):
            pass

        mw = BaseMiddleware(app)
        assert mw.app is app


class TestBuildMiddlewareStack:
    @pytest.mark.asyncio
    async def test_wraps_in_order(self):
        """First middleware in the list is outermost (first to receive)."""
        order = []

        class MW1(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                order.append("mw1_before")
                await self.app(scope, receive, send)
                order.append("mw1_after")

        class MW2(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                order.append("mw2_before")
                await self.app(scope, receive, send)
                order.append("mw2_after")

        async def core_app(scope, receive, send):
            order.append("core")

        wrapped = build_middleware_stack(core_app, [MW1, MW2])
        await wrapped({"type": "http"}, None, None)
        assert order == ["mw1_before", "mw2_before", "core", "mw2_after", "mw1_after"]

    @pytest.mark.asyncio
    async def test_tuple_entries_with_kwargs(self):
        """Support (cls, kwargs) tuples in the middleware list."""

        class MW(BaseMiddleware):
            def __init__(self, app, custom="default"):
                super().__init__(app)
                self.custom = custom

            async def __call__(self, scope, receive, send):
                scope["custom"] = self.custom
                await self.app(scope, receive, send)

        result_scope = {}

        async def core_app(scope, receive, send):
            result_scope.update(scope)

        wrapped = build_middleware_stack(core_app, [(MW, {"custom": "hello"})])
        await wrapped({}, None, None)
        assert result_scope["custom"] == "hello"

    @pytest.mark.asyncio
    async def test_empty_stack(self):
        """Empty middleware list returns the app unchanged."""

        async def app(scope, receive, send):
            pass

        result = build_middleware_stack(app, [])
        assert result is app
