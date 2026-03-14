from collections.abc import Callable

from openviper.routing.router import Route, Router


def create_router(prefix: str = "", middlewares: list[Callable] | None = None) -> Router:
    """Create a Router instance for testing."""
    return Router(prefix=prefix, middlewares=middlewares)


def create_route(
    path: str,
    methods: set[str],
    handler: Callable,
    name: str | None = None,
    middlewares: list[Callable] | None = None,
) -> Route:
    """Create a Route instance for testing."""
    return Route(
        path=path, methods=methods, handler=handler, name=name, middlewares=middlewares or []
    )
