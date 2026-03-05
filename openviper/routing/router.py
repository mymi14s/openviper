"""URL routing engine for OpenViper.

Supports:
  - Literal path segments: ``/users``
  - String parameters: ``/users/{id}``
  - Typed parameters: ``/users/{id:int}``, ``/files/{path:path}``
  - HTTP method routing
  - Sub-routers (blueprints) with ``include()``
  - Middleware attachment per-router
"""

from __future__ import annotations

import itertools
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import regex as re  # C extension drop-in for stdlib re (~2x faster matching)

from openviper.exceptions import MethodNotAllowed, NotFound

# ── Type aliases ─────────────────────────────────────────────────────────────

Handler = Callable[..., Awaitable[Any]]
Middleware = Callable[[Any, Any], Awaitable[Any]]

# ── Path converters ───────────────────────────────────────────────────────────

CONVERTERS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "str": (r"[^/]+", str),
    "int": (r"[0-9]+", int),
    "float": (r"[0-9]+(?:\.[0-9]+)?", float),
    "path": (r".+", str),
    "uuid": (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str),
    "slug": (r"[-a-zA-Z0-9_]+", str),
}


def _compile_path(path: str) -> tuple[re.Pattern[str], dict[str, Callable[[str], Any]]]:
    """Convert a path template like ``/users/{id:int}`` to a compiled regex."""
    pattern = "^"
    param_converters: dict[str, Callable[[str], Any]] = {}
    last_end = 0
    for m in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z]+))?\}", path):
        pattern += re.escape(path[last_end : m.start()])
        name = m.group(1)
        conv_name = m.group(2) or "str"
        regex_pat, conv = CONVERTERS.get(conv_name, CONVERTERS["str"])
        pattern += f"(?P<{name}>{regex_pat})"
        param_converters[name] = conv
        last_end = m.end()
    pattern += re.escape(path[last_end:]) + "$"
    return re.compile(pattern), param_converters


def _route_first_segment(path: str) -> str | None:
    """Return the first *static* path segment of a route path, or None if dynamic.

    Used to build the dispatch index.  A dynamic first segment (``/{foo}``)
    returns None so the route lands in the wildcard bucket.

    Examples::

        /users/{id}   -> "users"
        /             -> ""
        /{username}   -> None
        /admin/sub    -> "admin"
    """
    stripped = path.lstrip("/")
    seg = stripped.split("/")[0]
    return None if seg.startswith("{") else seg


# ── Route ─────────────────────────────────────────────────────────────────────


@dataclass
class Route:
    """A single registered route."""

    #: URL path template.
    path: str
    #: Allowed HTTP methods.
    methods: set[str]
    #: Async callable that handles the request.
    handler: Handler
    #: Optional name for reverse URL generation.
    name: str | None = None
    #: Per-route middleware stack.
    middlewares: list[Middleware] = field(default_factory=list)

    # Compiled
    _regex: re.Pattern[str] = field(init=False, repr=False)
    _converters: dict[str, Callable[[str], Any]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._regex, self._converters = _compile_path(self.path)
        self.methods = {m.upper() for m in self.methods}

    def match(self, path: str) -> dict[str, Any] | None:
        """Return path params dict if path matches, else None."""
        m = self._regex.match(path)
        if m is None:
            return None
        params: dict[str, Any] = {}
        for name, conv in self._converters.items():
            params[name] = conv(m.group(name))
        return params

    def __repr__(self) -> str:
        return (
            f"Route({self.path!r}, methods={sorted(self.methods)}, "
            f"handler={self.handler.__name__!r})"
        )


# ── Router ────────────────────────────────────────────────────────────────────

# Sentinel key in the dispatch index for routes whose first segment is dynamic.
_DYNAMIC = "__dynamic__"


class Router:
    """URL router that collects routes and resolves requests.

    Supports route groups (sub-routers) via ``include()``.

    Example:
        >>> router = Router(prefix="/api")
        >>> @router.get("/users")
        ... async def list_users(request): ...
    """

    def __init__(self, prefix: str = "", middlewares: list[Middleware] | None = None) -> None:
        self.prefix = prefix.rstrip("/")
        self.middlewares: list[Middleware] = middlewares or []
        self._routes: list[Route] = []
        self._sub_routers: list[Router] = []
        # Cache — invalidated whenever routes or sub-routers change.
        self._cached_routes: list[Route] | None = None
        # Dispatch index: first static segment -> candidate routes.
        # The _DYNAMIC bucket holds routes with a dynamic first segment.
        self._index: dict[str, list[Route]] | None = None

    # ── Cache management ───────────────────────────────────────────────────

    def _invalidate(self) -> None:
        """Mark the route cache and dispatch index stale."""
        self._cached_routes = None
        self._index = None

    def _build_index(self, routes: list[Route]) -> dict[str, list[Route]]:
        index: dict[str, list[Route]] = {}
        for route in routes:
            seg = _route_first_segment(route.path)
            key = seg if seg is not None else _DYNAMIC
            index.setdefault(key, []).append(route)
        return index

    # ── Route registration ─────────────────────────────────────────────────

    def route(
        self,
        path: str,
        methods: list[str],
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        """Decorator to register a handler for a path and methods."""

        def decorator(func: Handler) -> Handler:
            full_path = self.prefix + path
            self._routes.append(
                Route(
                    path=full_path,
                    methods=set(methods),
                    handler=func,
                    name=name or func.__name__,
                    middlewares=middlewares or [],
                )
            )
            self._invalidate()
            return func

        return decorator

    def get(self, path: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self.route(path, ["GET", "HEAD"], **kwargs)

    def post(self, path: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self.route(path, ["POST"], **kwargs)

    def put(self, path: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self.route(path, ["PUT"], **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self.route(path, ["PATCH"], **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self.route(path, ["DELETE"], **kwargs)

    def options(self, path: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self.route(path, ["OPTIONS"], **kwargs)

    def any(self, path: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self.route(
            path, ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], **kwargs
        )

    def add(
        self,
        path: str,
        handler: Handler,
        methods: list[str] | None = None,
        namespace: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> None:
        """Add a route directly without using decorators.

        Args:
            path: URL path pattern
            handler: Handler function
            methods: HTTP methods (default: ["GET"])
            namespace: Route name (default: handler.__name__)
            middlewares: Route-specific middlewares
        """
        methods = methods or ["GET"]
        name = namespace or handler.__name__
        full_path = self.prefix + path
        self._routes.append(
            Route(
                path=full_path,
                methods=set(methods),
                handler=handler,
                name=name,
                middlewares=middlewares or [],
            )
        )
        self._invalidate()

    # ── Sub-routers ────────────────────────────────────────────────────────

    def include_router(self, router: Router) -> None:
        """Mount a sub-router, prefixing all its routes with this router's prefix."""
        # Adjust prefix of sub-router routes
        adjusted = Router(
            prefix=self.prefix + router.prefix,
            middlewares=self.middlewares + router.middlewares,
        )
        adjusted._routes = [
            Route(
                path=self.prefix + route.path,
                methods=route.methods,
                handler=route.handler,
                name=route.name,
                middlewares=route.middlewares,
            )
            for route in router.routes
        ]
        for sub in router._sub_routers:
            adjusted._sub_routers.append(sub)
        self._sub_routers.append(adjusted)
        self._invalidate()

    # ── Route resolution ───────────────────────────────────────────────────

    @property
    def routes(self) -> list[Route]:
        """All routes including sub-router routes, flattened (cached)."""
        if self._cached_routes is None:
            all_routes: list[Route] = list(self._routes)
            for sub in self._sub_routers:
                all_routes.extend(sub.routes)
            self._cached_routes = all_routes
            self._index = self._build_index(all_routes)
        return self._cached_routes

    def _candidate_routes(self, path: str) -> Iterable[Route]:
        """Return only the routes that *could* match *path* using the dispatch index.

        This narrows the search from O(n) over all routes to O(k) where k is the
        number of routes sharing the same first path segment, plus dynamic-first
        routes.  The index is built lazily on first access and cached.
        """
        if self._index is None:
            _ = self.routes  # trigger lazy build
        index = self._index
        assert index is not None

        stripped = path.lstrip("/")
        seg = stripped.split("/")[0]
        static_bucket = index.get(seg, ())
        dynamic_bucket = index.get(_DYNAMIC, ())
        return itertools.chain(static_bucket, dynamic_bucket)

    def resolve(self, method: str, path: str) -> tuple[Route, dict[str, Any]]:
        """Find the matching route for a path and method.

        Returns:
            (route, path_params) tuple.

        Raises:
            NotFound: No route matched the path.
            MethodNotAllowed: Path matched but method not allowed.
        """
        method = method.upper()
        matched_route: Route | None = None
        allowed_methods: set[str] = set()
        params: dict[str, Any] = {}

        # Build candidate paths: always try the original path first, then
        # a slash-normalised alternative so that routes registered with a
        # trailing slash are reachable without one and vice-versa.
        #   /home/  → also try /home
        #   /admin  → also try /admin/
        #   /       → no alternative (root must stay as-is)
        if path == "" or path == "/":
            candidates: list[str] = ["/", ""]
        elif path.endswith("/"):
            candidates = [path, path.rstrip("/")]
        else:
            candidates = [path, path + "/"]

        for candidate in candidates:
            for route in self._candidate_routes(candidate):
                p = route.match(candidate)
                if p is not None:
                    allowed_methods.update(route.methods)
                    if method in route.methods:
                        matched_route = route
                        params = p
                        break
            if matched_route is not None:
                break

        if matched_route is None:
            if allowed_methods:
                raise MethodNotAllowed(sorted(allowed_methods))
            raise NotFound(f"No route found for '{path}'")

        return matched_route, params

    def url_for(self, name: str, **path_params: Any) -> str:
        """Reverse-resolve a URL by route name.

        Args:
            name: Route name as registered.
            **path_params: Values to fill in path parameters.

        Returns:
            URL string.

        Raises:
            KeyError: Route name not found.
        """
        for route in self.routes:
            if route.name == name:
                path = route.path
                for key, value in path_params.items():
                    # Replace {key} and {key:type}
                    path = re.sub(rf"\{{{key}(?::[a-zA-Z]+)?\}}", str(value), path)
                return path
        raise KeyError(f"No route named '{name}'")

    def __repr__(self) -> str:
        return f"Router(prefix={self.prefix!r}, routes={len(self.routes)})"


# ── Convenience helpers ───────────────────────────────────────────────────────


def include(router: Router, prefix: str = "") -> Router:
    """Helper to include a sub-router with an optional additional prefix.

    Creates a new router whose route paths are all prefixed with the given
    ``prefix``.  The original router is left unchanged.

    Example:
        >>> from myapp.routes import router as user_router
        >>> app.include_router(include(user_router, prefix="/api/v1"))
    """
    if prefix:
        adjusted = Router(prefix=prefix + router.prefix)
        # Re-create each route with the extra prefix prepended to its path.
        # (Route paths already contain the original router prefix.)
        adjusted._routes = [
            Route(
                path=prefix + route.path,
                methods=route.methods,
                handler=route.handler,
                name=route.name,
                middlewares=route.middlewares,
            )
            for route in router._routes
        ]
        # Recursively wrap sub-routers with the same prefix.
        adjusted._sub_routers = [include(sub, prefix=prefix) for sub in router._sub_routers]
        return adjusted
    return router
