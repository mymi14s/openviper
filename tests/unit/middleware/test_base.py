import pytest

from openviper.middleware.base import BaseMiddleware, build_middleware_stack


@pytest.mark.asyncio
async def test_base_middleware():
    calls = []

    async def dummy_app(scope, receive, send):
        calls.append("app_called")

    mw = BaseMiddleware(dummy_app)
    await mw({"type": "http"}, None, None)

    assert calls == ["app_called"]
    assert "BaseMiddleware" in repr(mw)


@pytest.mark.asyncio
async def test_build_middleware_stack():
    class MW1(BaseMiddleware):
        async def __call__(self, scope, receive, send):
            scope["trace"].append("mw1_start")
            await self.app(scope, receive, send)
            scope["trace"].append("mw1_end")

    class MW2(BaseMiddleware):
        def __init__(self, app, custom_val=None):
            super().__init__(app)
            self.custom_val = custom_val

        async def __call__(self, scope, receive, send):
            scope["trace"].append(f"mw2_start_{self.custom_val}")
            await self.app(scope, receive, send)
            scope["trace"].append(f"mw2_end_{self.custom_val}")

    async def dummy_app(scope, receive, send):
        scope["trace"].append("app")

    stack = build_middleware_stack(
        dummy_app, [MW1, (MW2, {"custom_val": "abc"})]  # outermost  # inner
    )

    scope = {"type": "http", "trace": []}
    await stack(scope, None, None)

    assert scope["trace"] == ["mw1_start", "mw2_start_abc", "app", "mw2_end_abc", "mw1_end"]
