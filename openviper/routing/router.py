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

import inspect
import itertools
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

try:
    import regex as re  # C extension drop-in for stdlib re (~2x faster matching)
except ImportError:
    import re

from openviper.exceptions import MethodNotAllowed, NotFound

log = logging.getLogger(__name__)

# ── Type aliases ──────────────────────────────────────────────

Handler = Callable[..., Awaitable[Any]]
Middleware = Callable[[Any, Any], Awaitable[Any]]

# ── Path converters ──────────────────────────────────────────

CONVERTERS: dict[str, tuple[str, Callable[[str], str | int | float]]] = {
    "str": (r"[^/]+", str),
    "int": (r"[0-9]{1,18}", int),
    "float": (r"[0-9]{1,18}(?:\.[0-9]{1,18})?", float),
    "path": (r"[^/](?:[^/]*(?:/[^/]+)*)?", str),
    "uuid": (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str),
    "slug": (r"[-a-zA-Z0-9_]+", str),
}

# ── Path normalization ───────────────────────────────────────

MULTI_SLASH_RE: re.Pattern[str] = re.compile(r"/{2,}")

# Matches {name} or {name:type} placeholders in a route path template.
PARAM_PLACEHOLDER_RE: re.Pattern[str] = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[a-zA-Z]+)?\}")

# Matches any {…} segment for validation in route paths.
ANY_PARAM_RE: re.Pattern[str] = re.compile(r"\{([^}]*)\}")

# Valid Python identifier pattern used to validate path parameter names.
VALID_PARAM_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Characters and patterns that must never appear in a request path.
NULL_BYTE_RE: re.Pattern[str] = re.compile(r"\x00")
TRAVERSAL_RE: re.Pattern[str] = re.compile(r"(?:^|/)\.\.(?:/|$)")
ENCODED_SLASH_RE: re.Pattern[str] = re.compile(r"%2[fF]|%5[cC]%2[fF]")

ANNOTATION_CONVERTERS: dict[object, str] = {
    int: "int",
    float: "float",
    str: "str",
    "int": "int",
    "float": "float",
    "str": "str",
}


class PathSecurityError(Exception):
    """Raised when a request path contains disallowed security-sensitive patterns."""


def normalize_path(path: str) -> str:
    """Normalize a path by collapsing consecutive slashes.

    Used for combining developer-defined route prefixes and paths during
    route registration.  Does **not** apply security checks since route
    templates are trusted input.

    - Collapses consecutive slashes (``//foo`` → ``/foo``).
    """
    if "//" not in path:
        return path  # fast-path: nothing to do
    return str(MULTI_SLASH_RE.sub("/", path))


def sanitize_request_path(path: str) -> str:
    """Sanitize and normalize a request path before routing.

    Applies security checks for malicious patterns and collapses
    consecutive slashes.  Must be called on all incoming request paths
    before route resolution.

    - Rejects null bytes (``\\x00``).
    - Rejects encoded slashes (``%2F``, ``%2f``, ``%5C%2F``).
    - Rejects directory traversal (``..`` segment).
    - Collapses consecutive slashes (``//foo`` → ``/foo``).

    Raises:
        PathSecurityError: If the path contains disallowed patterns.
    """
    if NULL_BYTE_RE.search(path):
        raise PathSecurityError(f"Null byte in path: {path!r}")

    if ENCODED_SLASH_RE.search(path):
        raise PathSecurityError(f"Encoded slash in path: {path!r}")

    if TRAVERSAL_RE.search(path):
        raise PathSecurityError(f"Directory traversal in path: {path!r}")

    if "//" not in path:
        return path
    return str(MULTI_SLASH_RE.sub("/", path))


def infer_view_method_path(path: str, method: Callable[..., Any]) -> str:
    """Append path parameters declared after ``request`` in a view method."""
    existing_names = {match.group(1) for match in PARAM_PLACEHOLDER_RE.finditer(path)}
    params = list(inspect.signature(method).parameters.values())
    suffix_parts: list[str] = []
    request_seen = False
    for param in params:
        if param.name == "self":
            continue
        if not request_seen:
            request_seen = param.name == "request"
            continue
        if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        if param.name in existing_names:
            continue
        converter = ANNOTATION_CONVERTERS.get(param.annotation, "str")
        suffix_parts.append(f"{{{param.name}:{converter}}}")

    if not suffix_parts:
        return path
    return f"{path.rstrip('/')}/{'/'.join(suffix_parts)}"


def inferred_route_name(base_name: str, base_path: str, inferred_path: str) -> str:
    """Return a stable distinct name for inferred parameterized view routes."""
    if inferred_path == base_path:
        return base_name
    param_names = [match.group(1) for match in PARAM_PLACEHOLDER_RE.finditer(inferred_path)]
    suffix = "_".join(param_names) if param_names else "detail"
    return f"{base_name}_{suffix}"


@lru_cache(maxsize=256)
def compile_path(
    path: str,
) -> tuple[re.Pattern[str], dict[str, Callable[[str], str | int | float]]]:
    """Convert a path template like ``/users/{id:int}`` to a compiled regex.

    Cached to avoid recompiling identical path patterns across multiple routes.

    Raises:
        ValueError: If a converter type is not recognized.
    """
    pattern = "^"
    param_converters: dict[str, Callable[[str], str | int | float]] = {}
    last_end = 0
    for m in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z]+))?\}", path):
        pattern += re.escape(path[last_end : m.start()])
        name = m.group(1)
        conv_name = m.group(2) or "str"
        if conv_name not in CONVERTERS:
            raise ValueError(
                f"Unknown path converter {conv_name!r} in route {path!r}. "
                f"Available converters: {', '.join(sorted(CONVERTERS))}"
            )
        regex_pat, conv = CONVERTERS[conv_name]
        pattern += f"(?P<{name}>{regex_pat})"
        param_converters[name] = conv
        last_end = m.end()
    pattern += re.escape(path[last_end:]) + "$"
    return re.compile(pattern), param_converters


def route_first_segment(path: str) -> str | None:
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


def route_specificity(path: str) -> tuple[int, int]:
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


# ── Route ────────────────────────────────────────────────────


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
    _converters: dict[str, Callable[[str], str | int | float]] = field(init=False, repr=False)
    # Cached first segment for dispatch index
    _first_segment: str | None = field(init=False, repr=False)
    # Flag for paths without parameters (enables exact match fast path)
    _is_literal: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for m in ANY_PARAM_RE.finditer(self.path):
            raw = m.group(1)
            name = raw.split(":")[0]
            if not VALID_PARAM_RE.match(name):
                raise ValueError(
                    f"Invalid path parameter name {name!r} in route {self.path!r}. "
                    "Parameter names must be valid Python identifiers "
                    "(start with a letter or underscore, "
                    "contain only letters, digits, underscores)."
                )
        self._regex, self._converters = compile_path(self.path)
        self.methods = {m.upper() for m in self.methods}
        self._first_segment = route_first_segment(self.path)
        self._is_literal = "{" not in self.path

    def match(self, path: str) -> dict[str, str | int | float] | None:
        """Return path params dict if path matches, else None."""
        m = self._regex.match(path)
        if m is None:
            return None
        params: dict[str, str | int | float] = {}
        for name, conv in self._converters.items():
            params[name] = conv(m.group(name))
        return params

    def __repr__(self) -> str:
        return (
            f"Route({self.path!r}, methods={sorted(self.methods)}, "
            f"handler={self.handler.__name__!r})"
        )


# ── Router ───────────────────────────────────────────────────

# Sentinel for dispatch index routes with a dynamic first segment.
DYNAMIC = "__dynamic__"


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
        # Cache - invalidated whenever routes or sub-routers change.
        self._cached_routes: list[Route] | None = None
        # Dispatch index: first static segment -> candidate routes.
        # The DYNAMIC bucket holds routes with a dynamic first segment.
        self._index: dict[str, list[Route]] | None = None
        # Name index: route name -> route (for O(1) url_for lookups)
        self._name_index: dict[str, Route] | None = None
        # Exact match index: literal path -> candidate routes.
        # Groups routes by literal path for multi-method fast-path.
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
            key = seg if seg is not None else DYNAMIC
            index.setdefault(key, []).append(route)
        for bucket in index.values():
            bucket.sort(key=lambda r: route_specificity(r.path), reverse=True)
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

    def get(
        self,
        path: str,
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        return self.route(path, ["GET", "HEAD"], name=name, middlewares=middlewares)

    def post(
        self,
        path: str,
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        return self.route(path, ["POST"], name=name, middlewares=middlewares)

    def put(
        self,
        path: str,
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        return self.route(path, ["PUT"], name=name, middlewares=middlewares)

    def patch(
        self,
        path: str,
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        return self.route(path, ["PATCH"], name=name, middlewares=middlewares)

    def delete(
        self,
        path: str,
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        return self.route(path, ["DELETE"], name=name, middlewares=middlewares)

    def options(
        self,
        path: str,
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        return self.route(path, ["OPTIONS"], name=name, middlewares=middlewares)

    def any(
        self,
        path: str,
        name: str | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> Callable[[Handler], Handler]:
        return self.route(
            path,
            ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
            name=name,
            middlewares=middlewares,
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
        if methods is None:
            view_class = getattr(handler, "view_class", None)
            if view_class is not None:
                self._add_inferred_view_routes(
                    path,
                    handler,
                    view_class,
                    namespace=namespace,
                    middlewares=middlewares,
                )
                return
            methods = ["GET"]
        name = namespace or handler.__name__
        # Path is prefixed by this router's prefix and
        # parent prefixes during flattening in .routes.
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

    def _add_inferred_view_routes(
        self,
        path: str,
        handler: Handler,
        view_class: type,
        *,
        namespace: str | None,
        middlewares: list[Middleware] | None,
    ) -> None:
        """Register standard class-view methods on inferred URL paths."""
        route_methods: dict[str, list[str]] = {}
        for method in getattr(view_class, "http_method_names", []):
            if method == "options" or not hasattr(view_class, method):
                continue
            inferred_path = infer_view_method_path(path, getattr(view_class, method))
            route_methods.setdefault(inferred_path, []).append(method.upper())

        base_name = namespace or handler.__name__
        for inferred_path, inferred_methods in route_methods.items():
            methods = [*inferred_methods, "OPTIONS"]
            self._routes.append(
                Route(
                    path=inferred_path,
                    methods=set(methods),
                    handler=handler,
                    name=inferred_route_name(base_name, path, inferred_path),
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
                base = normalize_path(current_abs.rstrip("/") + router.prefix)

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
                            path=normalize_path(base + r.path),
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
                        path=normalize_path(mount + r.path),
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
        dynamic_bucket = self._index.get(DYNAMIC, ())  # type: ignore[union-attr]
        return itertools.chain(static_bucket, dynamic_bucket)

    def resolve(self, method: str, path: str) -> tuple[Route, dict[str, str | int | float]]:
        """Find the matching route for a path and method.

        Returns:
            (route, path_params) tuple.

        Raises:
            NotFound: No route matched the path.
            MethodNotAllowed: Path matched but method not allowed.
            PathSecurityError: Path contains null bytes, traversal, or encoded slashes.
        """
        method = method.upper()
        path = sanitize_request_path(path)  # raises PathSecurityError on malicious input

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
        params: dict[str, str | int | float] = {}

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

    def url_for(self, name: str, **path_params: str | int | float) -> str:
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
            ValueError: A path parameter value contains disallowed characters.
        """
        if self._name_index is None:
            _ = self.routes

        route = self._name_index.get(name)  # type: ignore[union-attr]
        if route is None:
            raise KeyError(f"No route named '{name}'")

        def _replace(m: re.Match[str]) -> str:
            key = m.group(1)
            if key not in path_params:
                # Preserve placeholder when key is absent.
                return str(m.group(0))
            value = str(path_params[key])
            # Reject values that could manipulate routing or file paths.
            if "\x00" in value or ".." in value or "/" in value:
                raise ValueError(
                    f"Path parameter {key!r} value {value!r} contains "
                    "disallowed characters (null byte, '..', or '/')."
                )
            return value

        return str(PARAM_PLACEHOLDER_RE.sub(_replace, route.path))

    def __repr__(self) -> str:
        return f"Router(prefix={self.prefix!r}, routes={len(self.routes)})"


# ── Convenience helpers ──────────────────────────────────────


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
        wrapper = Router(prefix=normalize_path(prefix + router.prefix))
        wrapper._routes = list(router._routes)
        wrapper._sub_routers = list(router._sub_routers)
        wrapper.middlewares = router.middlewares
        wrapper.tags = list(router.tags)
        wrapper.namespace = router.namespace
        router._parents.add(wrapper)
        return wrapper
    return router
