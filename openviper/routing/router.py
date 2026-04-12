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
    "int": (r"[0-9]{1,18}", int),
    "float": (r"[0-9]{1,18}(?:\.[0-9]{1,18})?", float),
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

# Valid Python identifier pattern used to validate path parameter names.
_VALID_PARAM_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


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
    #: OpenAPI tags used to group this route in the schema.
    tags: list[str] = field(default_factory=list)

    # Compiled
    _regex: re.Pattern[str] = field(init=False, repr=False)
    _converters: dict[str, Callable[[str], Any]] = field(init=False, repr=False)
    # Cached first segment for dispatch index
    _first_segment: str | None = field(init=False, repr=False)
    # Flag for paths without parameters (enables exact match fast path)
    _is_literal: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for m in _ANY_PARAM_RE.finditer(self.path):
            raw = m.group(1)
            name = raw.split(":")[0]
            if not _VALID_PARAM_RE.match(name):
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

    def __init__(
        self,
        prefix: str = "",
        middlewares: list[Middleware] | None = None,
        tags: list[str] | None = None,
        namespace: str | None = None,
    ) -> None:
        self.prefix = prefix.rstrip("/") if len(prefix) > 1 else prefix
        self.middlewares: list[Middleware] = middlewares or []
        self.tags: list[str] = tags or []
        self.namespace: str | None = namespace
        self._routes: list[Route] = []
        self._sub_routers: list[tuple[str, Router]] = []
        self._parents: set[Router] = set()
        # Cache — invalidated whenever routes or sub-routers change.
        self._cached_routes: list[Route] | None = None
        # Dispatch index: first static segment -> candidate routes.
        # The _DYNAMIC bucket holds routes with a dynamic first segment.
        self._index: dict[str, list[Route]] | None = None
        # Name index: route name -> route (for O(1) url_for lookups)
        self._name_index: dict[str, Route] | None = None
        # Exact match index: literal path -> candidate routes (fast path for literal routes).
        # Stores all routes sharing the same literal path to support multi-method fast-path.
        self._exact_index: dict[str, list[Route]] | None = None

    # ── Cache management ───────────────────────────────────────────────────

    def _invalidate(self) -> None:
        """Mark the route cache and dispatch index stale.

        Propagates invalidation up to all parent routers.
        """
        self._cached_routes = None
        self._index = None
        self._name_index = None
        self._exact_index = None

        for parent in self._parents:
            parent._invalidate()

    def _build_index(self, routes: list[Route]) -> dict[str, list[Route]]:
        """Build dispatch index by first path segment, pre-sorted by specificity."""
        index: dict[str, list[Route]] = {}
        for route in routes:
            seg = route._first_segment
            key = seg if seg is not None else _DYNAMIC
            index.setdefault(key, []).append(route)
        for bucket in index.values():
            bucket.sort(key=lambda r: _route_specificity(r.path), reverse=True)
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

    def _build_exact_index(self, routes: list[Route]) -> dict[str, list[Route]]:
        """Build exact match index grouping all routes by literal path.

        Groups all routes that share the same literal path so every registered
        method is reachable via the O(1) fast path.
        """
        exact_index: dict[str, list[Route]] = {}
        for route in routes:
            # Routes passed here are already absolute (from self.routes).
            if route._is_literal:
                exact_index.setdefault(route.path, []).append(route)
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
            # Store path exactly as provided.
            self._routes.append(
                Route(
                    path=path,
                    methods=set(methods),
                    handler=func,
                    name=name or func.__name__,
                    middlewares=middlewares or [],
                    tags=list(self.tags),
                )
            )
            self._invalidate()
            self._register_actions(path, func)
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
        # Store path exactly as provided (it will be prefixed by this router's prefix
        # and any parent prefixes during flattening in the .routes property).
        self._routes.append(
            Route(
                path=path,
                methods=set(methods),
                handler=handler,
                name=name,
                middlewares=middlewares or [],
                tags=list(self.tags),
            )
        )
        self._invalidate()
        self._register_actions(path, handler)

    def _register_actions(self, path: str, handler: Handler) -> None:
        """Discover and register custom actions attached to a handler.

        This allows class-based views to automatically register @action
        methods when the main view is mounted.
        """
        actions = getattr(handler, "_openviper_actions", [])
        view_class = getattr(handler, "view_class", None)
        if not (actions and view_class):
            return

        base_path = path.rstrip("/")
        for action_info in actions:
            # Build sub-path
            # - Collection action (detail=False): prefix/custom_path
            # - Member action (detail=True): prefix/{id}/custom_path
            if action_info["detail"]:
                if "{id}" in base_path or "{pk}" in base_path:
                    action_path = f"{base_path}/{action_info['url_path']}"
                else:
                    action_path = f"{base_path}/{{id}}/{action_info['url_path']}"
            else:
                action_path = f"{base_path}/{action_info['url_path']}"

            # Create a specialized as_view handler for this specific action
            action_handler = view_class.as_view(
                _action_name=action_info["method_name"],
                **getattr(handler, "view_initkwargs", {}),
            )

            # Register it on this router instance
            self.add(
                action_path,
                action_handler,
                methods=action_info["methods"],
                namespace=f"{handler.__name__.lower()}_{action_info['name']}",
            )

    # ── Sub-routers ────────────────────────────────────────────────────────

    def include_router(
        self, router: Router, prefix: str = "", namespace: str | None = None
    ) -> None:
        """Mount a sub-router as a live reference.

        Any routes added to the sub-router later will automatically be visible
        through this router's prefix.

        Args:
            router: Sub-router to mount.
            prefix: Additional URL prefix to apply at the mount point.
            namespace: Override the sub-router's namespace.  When given,
                all route names from the sub-router become
                ``"namespace:route_name"`` in this router's name index.
        """
        if namespace is not None:
            router.namespace = namespace
        # Track parent for invalidation propagation
        router._parents.add(self)

        # We store the base prefix to apply during flattening
        self._sub_routers.append((prefix, router))
        self._invalidate()

    # ── Route resolution ───────────────────────────────────────────────────

    @property
    def routes(self) -> list[Route]:
        """All routes including sub-router routes, flattened and absolute (cached)."""
        if self._cached_routes is None:

            def _get_absolute(router: Router, current_abs: str, ns_prefix: str = "") -> list[Route]:
                base = _normalize_path(current_abs.rstrip("/") + router.prefix)

                # Accumulate the namespace chain: parent_ns + this_router_ns
                if router.namespace:
                    ns_sep = f"{ns_prefix}{router.namespace}:"
                    branch_ns = ns_sep if ns_prefix else f"{router.namespace}:"
                else:
                    branch_ns = ns_prefix

                res = []

                # Accumulate local routes
                for r in router._routes:
                    ns_name = f"{branch_ns}{r.name}" if r.name and branch_ns else r.name
                    res.append(
                        Route(
                            path=_normalize_path(base + r.path),
                            methods=r.methods,
                            handler=r.handler,
                            name=ns_name,
                            middlewares=r.middlewares + router.middlewares,
                            tags=r.tags,
                        )
                    )

                # Accumulate sub-router routes recursively
                for extra_prefix, sub in router._sub_routers:
                    res.extend(_get_absolute(sub, base + (extra_prefix or ""), branch_ns))

                return res

            all_routes = _get_absolute(self, "")
            self._cached_routes = all_routes

            # Build indices
            self._index = self._build_index(all_routes)
            self._name_index = self._build_name_index(all_routes)
            self._exact_index = self._build_exact_index(all_routes)

        return self._cached_routes

    def _all_relative_routes(self) -> list[Route]:
        """Return all local and sub-router routes relative to THIS router's root.

        This includes sub-router routes prefixed with their respective mount points.
        It does NOT include this router's own prefix.
        """
        res = list(self._routes)
        for extra_prefix, sub in self._sub_routers:
            mount = (extra_prefix or "").rstrip("/")
            for r in sub._all_relative_routes():
                res.append(
                    Route(
                        path=_normalize_path(mount + r.path),
                        methods=r.methods,
                        handler=r.handler,
                        name=r.name,
                        middlewares=r.middlewares + sub.middlewares,
                        tags=r.tags,
                    )
                )
        return res

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
        method = method.upper()
        path = _normalize_path(path)

        # Trigger lazy build of indices if needed
        if self._exact_index is None:
            _ = self.routes

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
            exact_routes = self._exact_index.get(candidate)  # type: ignore[union-attr]
            if exact_routes:
                for exact_route in exact_routes:
                    allowed_methods.update(exact_route.methods)
                    if method in exact_route.methods:
                        return exact_route, {}

            for route in self._candidate_routes(candidate):
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
            **path_params: Values to fill in path parameters.  Any placeholder
                whose key is absent from *path_params* is left as-is in the
                returned URL (e.g. ``{y:int}``).

        Returns:
            URL string.

        Raises:
            KeyError: Route name not found.
        """
        if self._name_index is None:
            _ = self.routes

        route = self._name_index.get(name)  # type: ignore[union-attr]
        if route is None:
            raise KeyError(f"No route named '{name}'")

        def _replace(m: re.Match[str]) -> str:
            key = m.group(1)
            if key not in path_params:
                # If key is missing, preserve the original placeholder {key} or {key:type}
                return m.group(0)
            return str(path_params[key])

        return str(_PARAM_PLACEHOLDER_RE.sub(_replace, route.path))

    def __repr__(self) -> str:
        return f"Router(prefix={self.prefix!r}, routes={len(self.routes)})"


# ── Convenience helpers ───────────────────────────────────────────────────────


def include(router: Router, prefix: str = "", namespace: str | None = None) -> Router:
    """Helper to include a sub-router with an optional additional prefix and namespace.

    Creates a new router whose route paths are all prefixed with the given
    ``prefix``.  The original router is left unchanged.  When *namespace* is
    supplied, all route names from the sub-router become
    ``"namespace:route_name"`` in any parent router's name index.

    Example:
        >>> from myapp.routes import router as user_router
        >>> app.include_router(include(user_router, prefix="/api/v1", namespace="users"))
    """
    if namespace is not None:
        router.namespace = namespace
    if prefix:
        wrapper = Router(prefix=_normalize_path(prefix + router.prefix))
        wrapper._routes = list(router._routes)
        wrapper._sub_routers = list(router._sub_routers)
        wrapper.middlewares = router.middlewares
        wrapper.tags = list(router.tags)
        wrapper.namespace = router.namespace
        router._parents.add(wrapper)
        return wrapper
    return router
