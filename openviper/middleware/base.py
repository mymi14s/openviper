"""Base middleware infrastructure for OpenViper.

Middlewares are ASGI callables that wrap the application. Each middleware
receives the ``scope``, ``receive``, and ``send`` parameters from the ASGI
spec and can intercept, modify, or short-circuit the request/response cycle.

Example:
    .. code-block:: python

        from openviper.middleware.base import BaseMiddleware
        from openviper.http import Request, JSONResponse

        class MyMiddleware(BaseMiddleware):
            async def __call__(self, scope, receive, send):
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return
                request = Request(scope, receive)
                # ... do something before the view
                await self.app(scope, receive, send)
                # ... do something after the view (if needed)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ASGIApp = Callable[[dict[str, Any], Any, Any], Awaitable[None]]


class BaseMiddleware:
    """Base ASGI middleware class.

    Subclass this and implement ``__call__``.

    Args:
        app: The next ASGI application in the chain.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self.app(scope, receive, send)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(app={self.app!r})"


def build_middleware_stack(
    app: ASGIApp,
    middleware_classes: list[type[BaseMiddleware] | tuple[type[BaseMiddleware], dict[str, Any]]],
) -> ASGIApp:
    """Wrap app with a stack of ASGI middleware in order.

    Middlewares are applied inner-first: the first item in the list is the
    outermost wrapper (first to receive the request).

    Args:
        app: The core ASGI application.
        middleware_classes: Ordered list of middleware classes or
            ``(cls, kwargs)`` tuples.

    Returns:
        A wrapped ASGI app.
    """
    for entry in reversed(middleware_classes):
        if isinstance(entry, tuple):
            cls, kwargs = entry
            app = cls(app, **kwargs)
        else:
            app = entry(app)
    return app
