"""Base ASGI middleware infrastructure.

Each middleware wraps the next ASGI app and intercepts the
``scope``, ``receive``, ``send`` lifecycle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from openviper.http.types import ASGIReceive, ASGIScope, ASGISend

type ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]
type MiddlewareConfig = Mapping[str, object]
type MiddlewareEntry = type["BaseMiddleware"] | tuple[type["BaseMiddleware"], MiddlewareConfig]


class BaseMiddleware:
    """Base ASGI middleware class.

    Subclass this and implement ``__call__``.

    Args:
        app: The next ASGI application in the chain.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        await self.app(scope, receive, send)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(app={self.app!r})"


def build_middleware_stack(
    app: ASGIApp,
    middleware_classes: list[MiddlewareEntry],
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
