"""Class-based views for OpenViper.

Provides :class:`View` — a base class that dispatches incoming requests
to handler methods named after the HTTP verb (``get``, ``post``, ``put``,
``patch``, ``delete``, ``head``, ``options``) or custom methods
decorated with :func:`action`.

Usage with a router::

    from openviper.http.views import View, action

    class UserView(View):
        async def get(self, request):
            # dict/list return values are automatically wrapped in JSONResponse
            return {"users": []}

        @action(detail=False)
        async def me(self, request):
            # Use 'Request:' and 'Example Response:' tags in the docstring
            '''Get current user info.

            Request: UserSerializer
            Example Response: {"id": 1, "username": "admin"}
            '''
            return request.user.to_dict()

    # Mounting the view automatically registers all actions
    router.add("/users", UserView.as_view())
    # OR use explicitly:
    # UserView.register(router, "/users")

OpenAPI Integration:
    The schema generator automatically detects request metadata from docstrings:
    - ``Request: <SerializerName>``: Link a serializer to the request body.
    - ``Example Request: { ... }``: Provide a sample JSON payload for the request.
    - ``Example Response: { ... }``: Provide a sample JSON payload for the 200 response.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from openviper.conf import settings
from openviper.exceptions import MethodNotAllowed, PermissionDenied
from openviper.http.response import JSONResponse, Response
from openviper.utils.importlib import import_string

if TYPE_CHECKING:
    from openviper.http.request import Request
    from openviper.routing.router import Router

# HTTP methods that View can dispatch to.
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def action(
    methods: list[str] | None = None,
    detail: bool = False,
    url_path: str | None = None,
    name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to mark a View method as a custom action for automatic routing.

    Args:
        methods: List of HTTP methods (e.g., ["GET", "POST"]). Defaults to ["GET"].
        detail: If True, the action is for a single instance (member).
            If False, it's for the full collection.
        url_path: Optional override for the URL segment. Defaults to method name.
        name: Optional name for the route. Defaults to method name.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func._openviper_action = {
            "methods": [m.upper() for m in methods or ["GET"]],
            "detail": detail,
            "url_path": url_path or func.__name__,
            "name": name or func.__name__,
        }
        return func

    return decorator


class View:
    """Base class-based view.

    Subclass and implement one or more HTTP-verb methods (``get``,
    ``post``, etc.).  Unimplemented methods return *405 Method Not
    Allowed*.

    Class attributes:
        http_method_names: Iterable of lowercase method names this view
            is willing to handle.  Defaults to all standard methods but
            can be overridden per-subclass.
    """

    http_method_names: list[str] = [
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
    ]

    #: Optional Pydantic serializer class for request body schema.
    #: When set, the OpenAPI schema generator uses it to produce the
    #: ``requestBody`` entry so that Swagger UI displays input fields.
    serializer_class: list[Any] = []

    #: List of authentication classes to apply to this view.
    #: When ``None``, falls back to ``settings.DEFAULT_AUTHENTICATION_CLASSES``.
    #: Set to ``[]`` to explicitly disable per-view authentication.
    authentication_classes: list[Any] = []

    #: List of permission classes to apply to this view.
    #: When ``None``, falls back to ``settings.DEFAULT_PERMISSION_CLASSES``.
    #: Set to ``[]`` to explicitly disable per-view permission checks.
    permission_classes: list[Any] = []

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    # ── Core dispatch ─────────────────────────────────────────────────────

    async def dispatch(self, request: Request, **kwargs: Any) -> Response:
        """Route *request* to the appropriate handler method.

        If the HTTP method is not in :attr:`http_method_names` or if the
        subclass does not define a handler for it, return a 405 response.
        """
        method = request.method.lower()
        if method not in self.http_method_names:
            return cast("Response", self.http_method_not_allowed(request))

        # Perform authentication and check permissions before dispatching
        await self.perform_authentication(request)
        await self.check_permissions(request)

        handler = getattr(self, method, self.http_method_not_allowed)
        result = await handler(request, **kwargs)
        if isinstance(result, (dict, list)):
            return JSONResponse(result)
        return cast("Response", result)

    async def perform_authentication(self, request: Request) -> None:
        """
        Attempt to authenticate the request using the configured
        authentication classes.
        """
        for authenticator in self.get_authenticators():
            try:
                result = await authenticator.authenticate(request)
                if result is not None:
                    request.user, request.auth = result
                    return
            except Exception:
                # Authentication failures in per-view auth are ignored
                # unless explicitly required by a permission class.
                pass

    def get_authenticators(self) -> list[Any]:
        """Load and instantiate the authentication classes."""
        authenticators = []
        auth_classes = self.authentication_classes
        if auth_classes is None:
            auth_classes = settings.DEFAULT_AUTHENTICATION_CLASSES

        for auth_class in auth_classes:
            if isinstance(auth_class, str):
                auth_class = import_string(auth_class)
            authenticators.append(auth_class())
        return authenticators

    async def check_permissions(self, request: Request) -> None:
        """Check if the request should be permitted.

        Iterates through :attr:`permission_classes` and calls
        ``has_permission(request, self)`` on each.

        Args:
            request: The incoming request.

        Raises:
            PermissionDenied: If any permission check fails.
        """
        for permission in self.get_permissions():
            if not await permission.has_permission(request, self):
                self.permission_denied(request)

    async def check_object_permissions(self, request: Request, obj: Any) -> None:
        """Check if the request should be permitted to access the given object.

        Raises PermissionDenied if any permission check fails.
        """
        for permission in self.get_permissions():
            if not await permission.has_object_permission(request, self, obj):
                self.permission_denied(request)

    def get_permissions(self) -> list[Any]:
        """Instantiate and return the list of permissions that this view requires.

        Handles permission classes (types), already-instantiated permissions,
        dotted-path strings (from settings), and ``OperandHolder`` composites.
        """
        perm_sources = self.permission_classes
        if perm_sources is None:
            perm_sources = settings.DEFAULT_PERMISSION_CLASSES

        permissions: list[Any] = []
        for entry in perm_sources:
            if isinstance(entry, str):
                entry = import_string(entry)
            # callable but not a type covers OperandHolder
            if isinstance(entry, type) or callable(entry) and not hasattr(entry, "has_permission"):
                permissions.append(entry())
            else:
                permissions.append(entry)
        return permissions

    def permission_denied(self, request: Request, message: str | None = None) -> None:
        """If request is not permitted, determine what kind of exception to raise."""
        raise PermissionDenied(detail=message)

    def http_method_not_allowed(self, request: Request, **kwargs: Any) -> Any:
        """Return a 405 Method Not Allowed error."""
        allowed = self._allowed_methods()
        raise MethodNotAllowed(allowed)

    # ── Default OPTIONS implementation ────────────────────────────────────

    async def options(self, request: Request, **kwargs: Any) -> Response:
        """Handle OPTIONS by returning allowed methods in the ``Allow`` header."""

        allowed = self._allowed_methods()
        return Response(
            status_code=204,
            headers={"Allow": ", ".join(allowed)},
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    def _allowed_methods(self) -> list[str]:
        """Return sorted list of uppercase HTTP methods this view handles.

        Cached at the class level on first call — since handlers are class
        attributes, the result is the same for every instance of a given
        subclass.  Using ``cls.__dict__`` ensures each subclass gets its own
        cache entry without inheriting a parent's cached value.
        """
        cls = type(self)
        _key = "_view_allowed_methods_cache"
        cached: list[str] | None = cls.__dict__.get(_key)
        if cached is None:
            cached = sorted(m.upper() for m in self.http_method_names if hasattr(cls, m))
            setattr(cls, _key, cached)
        return cached

    # ── Integration with Router ───────────────────────────────────────────

    @classmethod
    def as_view(cls, _action_name: str | None = None, **initkwargs: Any) -> Any:
        """Return an async callable suitable for use as a route handler.

        Any *initkwargs* are forwarded to the view's ``__init__`` and
        stored on every instance created per request.

        Example::

            router.get("/items")(ItemView.as_view())
        """
        # Validate that initkwargs don't clash with HTTP methods
        for key in initkwargs:
            if key in _HTTP_METHODS:
                raise TypeError(
                    f"as_view() received an invalid keyword {key!r}. "
                    f"{cls.__name__} must implement HTTP method handlers "
                    f"as methods, not constructor arguments."
                )

        async def view(request: Request, **kwargs: Any) -> Response:
            self = cls(**initkwargs)
            # If an explicit action name was provided (via register()), skip dispatch
            # and call that specific method directly.
            if _action_name:
                await self.perform_authentication(request)
                await self.check_permissions(request)
                handler = getattr(self, _action_name)
                result = await handler(request, **kwargs)
            else:
                result = await self.dispatch(request, **kwargs)

            if isinstance(result, (dict, list)) and not isinstance(result, Response):
                return JSONResponse(result)
            return cast("Response", result)

        # Preserve metadata for introspection / debugging
        view.__name__ = f"{cls.__name__}_{_action_name}" if _action_name else cls.__name__
        view.__qualname__ = (
            f"{cls.__qualname__}.{_action_name}" if _action_name else cls.__qualname__
        )
        view.__doc__ = getattr(cls, _action_name).__doc__ if _action_name else cls.__doc__
        view.view_class = cls  # type: ignore[attr-defined]
        view.view_action = _action_name  # type: ignore[attr-defined]
        view.view_initkwargs = initkwargs  # type: ignore[attr-defined]

        # ── Discover custom @action methods ───────────────────────────────
        if not _action_name:
            actions = []
            for attr_name in dir(cls):
                attr = getattr(cls, attr_name, None)
                action_info = getattr(attr, "_openviper_action", None)
                if action_info:
                    actions.append({**action_info, "method_name": attr_name})
            view._openviper_actions = actions  # type: ignore[attr-defined]

        return view

    @classmethod
    def register(
        cls,
        router: Router,
        path: str,
        *,
        name: str | None = None,
        **initkwargs: Any,
    ) -> None:
        """Register this view on *router* at *path*.

        Automatically determines which HTTP methods are implemented and
        registers them.

        Example::

            UserView.register(router, "/users")
        """
        methods = [
            m.upper()
            for m in cls.http_method_names
            if m != "options" and hasattr(cls, m) and m in _HTTP_METHODS
        ]
        # OPTIONS is always allowed when at least one method is defined.
        if methods:
            methods.append("OPTIONS")

        handler = cls.as_view(**initkwargs)
        router.add(path, handler, methods=methods, namespace=name or cls.__name__)
