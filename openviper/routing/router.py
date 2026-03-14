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
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import regex as re  # C extension drop-in for stdlib re (~2x faster matching)

from openviper.exceptions import MethodNotAllowed, NotFound

log = logging.getLogger(__name__)

# ── Type aliases ─────────────────────────────────────────────────────────────

Handler = Callable[..., Awaitable[Any]]
Middleware = Callable[[Any, Any], Awaitable[Any]]

# ── Path converters ───────────────────────────────────────────────────────────

CONVERTERS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "str": (r"[^/]+", str),
    # Capped at 18 digits to prevent arbitrary-precision int allocation via URLs.
    "int": (r"[0-9]{1,18}", int),
    # Integer part capped at 18 digits; decimal part capped at 18 digits.
    "float": (r"[0-9]{1,18}(?:\.[0-9]{1,18})?", float),
    # .++ is a possessive quantifier (regex C extension): greedily consumes all
    # characters without releasing any back to the engine, preventing catastrophic
    # backtracking (ReDoS) when this converter appears before a fixed suffix.
    # NOTE: the `path` converter must always be the LAST segment in a route path.
    "path": (r".++", str),
    "uuid": (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str),
    "slug": (r"[-a-zA-Z0-9_]+", str),
}


# ── Path normalization ────────────────────────────────────────────────────────

_MULTI_SLASH_RE: re.Pattern[str] = re.compile(r"/{2,}")

# Matches {name} or {name:type} placeholders in a route path template.
_PARAM_PLACEHOLDER_RE: re.Pattern[str] = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[a-zA-Z]+)?\}")

# Matches any {…} segment (including invalid ones) for validation in route paths.
_ANY_PARAM_RE: re.Pattern[str] = re.compile(r"\{([^}]*)\}")


def _normalize_path(path: str) -> str:
    """Normalize a request path before routing.

    - Collapses consecutive slashes (``//foo`` → ``/foo``).
    - Does **not** decode percent-encoded characters; that is the ASGI
      server's responsibility and decoding here (especially ``%2F``) would
      silently change routing semantics.
    """
    if "//" not in path:
        return path  # fast-path: nothing to do
    return str(_MULTI_SLASH_RE.sub("/", path))


@lru_cache(maxsize=256)
def _compile_path(path: str) -> tuple[re.Pattern[str], dict[str, Callable[[str], Any]]]:
    """Convert a path template like ``/users/{id:int}`` to a compiled regex.

    Cached to avoid recompiling identical path patterns across multiple routes.
    """
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
    seg = stripped.partition("/")[0]  # partition is O(n) but avoids building a list
    return None if seg.startswith("{") else seg


def _route_specificity(path: str) -> tuple[int, int]:
    """Calculate route specificity for sorting.

    More specific routes (with more literal segments) should be tried first.
    Returns (literal_segment_count, total_segment_count) in descending order
    for sorting purposes.

    Examples::
        /users/{id}                          -> (1, 2)
        /users/{id}/fk-search                -> (2, 3)
        /admin/models/{app}/{model}/fk-search -> (2, 5)
    """
    segments = [s for s in path.split("/") if s]  # split and filter empty
    literal_count = sum(1 for seg in segments if not seg.startswith("{"))
    return (literal_count, len(segments))


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
    # Cached first segment for dispatch index
    _first_segment: str | None = field(init=False, repr=False)
    # Flag for paths without parameters (enables exact match fast path)
    _is_literal: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Validate parameter names before compiling — invalid names (e.g. {123:int},
        # {a-b}) register silently but never match, which is confusing.
        _valid_param = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
        for m in _ANY_PARAM_RE.finditer(self.path):
            raw = m.group(1)
            name = raw.split(":")[0]
            if not _valid_param.match(name):
                raise ValueError(
                    f"Invalid path parameter name {name!r} in route {self.path!r}. "
                    "Parameter names must be valid Python identifiers "
                    "(start with a letter or underscore, "
                    "contain only letters, digits, underscores)."
                )
        self._regex, self._converters = _compile_path(self.path)
        self.methods = {m.upper() for m in self.methods}
        self._first_segment = _route_first_segment(self.path)
        self._is_literal = "{" not in self.path

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
        # Name index: route name -> route (for O(1) url_for lookups)
        self._name_index: dict[str, Route] | None = None
        # Exact match index: literal path -> route (fast path for parameterless routes)
        self._exact_index: dict[str, Route] | None = None

    # ── Cache management ───────────────────────────────────────────────────

    def _invalidate(self) -> None:
        """Mark the route cache and dispatch index stale."""
        self._cached_routes = None
        self._index = None
        self._name_index = None
        self._exact_index = None

    def _build_index(self, routes: list[Route]) -> dict[str, list[Route]]:
        """Build dispatch index by first path segment."""
        index: dict[str, list[Route]] = {}
        for route in routes:
            seg = route._first_segment
            key = seg if seg is not None else _DYNAMIC
            index.setdefault(key, []).append(route)
        return index

    def _build_name_index(self, routes: list[Route]) -> dict[str, Route]:
        """Build name index for O(1) url_for() lookup."""
        name_index: dict[str, Route] = {}
        for route in routes:
            if route.name:
                if route.name in name_index:
                    log.warning(
                        "Duplicate route name %r: %r will shadow %r. "
                        "url_for(%r) will resolve to the later route.",
                        route.name,
                        route.path,
                        name_index[route.name].path,
                        route.name,
                    )
                name_index[route.name] = route
        return name_index

    def _build_exact_index(self, routes: list[Route]) -> dict[str, Route]:
        """Build exact match index for literal paths (fast path)."""
        exact_index: dict[str, Route] = {}
        for route in routes:
            if route._is_literal:
                exact_index[route.path] = route
        return exact_index

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
        # We use the include() helper to create a version of the router tree
        # adjusted for this router's prefix. This avoids the duplication bug
        # where routes were both flattened into _routes AND kept in _sub_routers.
        self._sub_routers.append(include(router, prefix=self.prefix))
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
            # Build all indices once
            self._index = self._build_index(all_routes)
            self._name_index = self._build_name_index(all_routes)
            self._exact_index = self._build_exact_index(all_routes)
        return self._cached_routes

    def _candidate_routes(self, path: str) -> Iterable[Route]:
        """Return only the routes that *could* match *path* using the dispatch index.

        This narrows the search from O(n) over all routes to O(k) where k is the
        number of routes sharing the same first path segment, plus dynamic-first
        routes.  The index is built lazily on first access and cached.
        """
        if self._index is None:
            _ = self.routes  # trigger lazy build
        # _index is guaranteed non-None after self.routes is accessed above
        stripped = path.lstrip("/")
        seg = stripped.partition("/")[0]
        static_bucket = self._index.get(seg, ())  # type: ignore[union-attr]
        dynamic_bucket = self._index.get(_DYNAMIC, ())  # type: ignore[union-attr]
        return itertools.chain(static_bucket, dynamic_bucket)

    def resolve(self, method: str, path: str) -> tuple[Route, dict[str, Any]]:
        """Find the matching route for a path and method.

        Returns:
            (route, path_params) tuple.

        Raises:
            NotFound: No route matched the path.
            MethodNotAllowed: Path matched but method not allowed.
        """
        # ASGI spec already uppercases method, but just in case
        method = method.upper()
        # Collapse consecutive slashes before any index or regex lookup
        path = _normalize_path(path)

        # Trigger lazy build of indices if needed
        if self._exact_index is None:
            _ = self.routes

        # Fast path: try exact match for literal paths first
        exact_route = self._exact_index.get(path)  # type: ignore[union-attr]
        if exact_route and method in exact_route.methods:
            return exact_route, {}

        # Build candidate paths: always try the original path first, then
        # a slash-normalised alternative so that routes registered with a
        # trailing slash are reachable without one and vice-versa.
        #   /home/  → also try /home
        #   /admin  → also try /admin/
        #   /       → no alternative (root must stay as-is)
        candidates: list[str] = [path]
        if path not in ("", "/"):
            if path.endswith("/"):
                candidates.append(path.rstrip("/"))
            else:
                candidates.append(path + "/")

        matched_route: Route | None = None
        allowed_methods: set[str] = set()
        params: dict[str, Any] = {}

        for candidate in candidates:
            # Try exact match first for this candidate
            exact_route = self._exact_index.get(candidate)  # type: ignore[union-attr]
            if exact_route:
                allowed_methods.update(exact_route.methods)
                if method in exact_route.methods:
                    return exact_route, {}

            # Fall back to regex matching
            # Sort candidate routes by specificity: more specific (more literal
            # segments) first. This ensures /path/literal matches before /path/{param}.
            sorted_routes = sorted(
                self._candidate_routes(candidate),
                key=lambda r: _route_specificity(r.path),
                reverse=True,
            )
            for route in sorted_routes:
                p = route.match(candidate)
                if p is not None:
                    allowed_methods.update(route.methods)
                    if method in route.methods:
                        matched_route = route
                        params = p
                        # Early exit: stop searching once we find a match
                        break

            # Early exit: stop trying candidates once we find a match
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
        # Trigger lazy build of indices if needed
        if self._name_index is None:
            _ = self.routes

        # O(1) lookup via name index
        route = self._name_index.get(name)  # type: ignore[union-attr]
        if route is None:
            raise KeyError(f"No route named '{name}'")

        # Single-pass replacement: _PARAM_PLACEHOLDER_RE matches both
        # {name} and {name:type} in one scan, avoiding the previous O(n*k)
        # nested loop (n params × k converter names).
        def _replace(m: re.Match[str]) -> str:
            key = m.group(1)
            return str(path_params[key]) if key in path_params else m.group(0)

        return str(_PARAM_PLACEHOLDER_RE.sub(_replace, route.path))

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
