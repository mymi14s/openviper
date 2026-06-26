"""Class-based views for OpenViper.

Provides :class:`View` - a base class that dispatches incoming requests
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

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from openviper.conf import settings
from openviper.exceptions import MethodNotAllowed, PermissionDenied, TooManyRequests
from openviper.http.response import JSONResponse, Response
from openviper.utils.importlib import import_string

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from openviper.http.request import Request
    from openviper.http.types import AuthenticatorProtocol, PermissionProtocol, ThrottleProtocol
    from openviper.routing.router import Router

type HandlerCallable = Callable[..., Awaitable[object]]
type RouteCallable = Callable[..., Awaitable[Response]]


def resolve_component_list(
    sources: list[Any] | None,
    settings_attr: str,
) -> list[Any]:
    """Resolve a list of component sources to instantiated objects.

    Handles class types (instantiated), already-instantiated objects
    (passed through), and dotted-path strings (resolved via import_string).
    """
    if sources is None:
        sources = getattr(settings, settings_attr, [])
    resolved: list[Any] = []
    for entry in sources:
        if isinstance(entry, str):
            entry = import_string(entry)
        if isinstance(entry, type):
            resolved.append(entry())
        else:
            resolved.append(entry)
    return resolved


HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def action(
    methods: list[str] | None = None,
    detail: bool = False,
    url_path: str | None = None,
    name: str | None = None,
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Decorator to mark a View method as a custom action for automatic routing.

    Args:
        methods: List of HTTP methods (e.g., ["GET", "POST"]). Defaults to ["GET"].
        detail: If True, the action is for a single instance (member).
            If False, it's for the full collection.
        url_path: Optional override for the URL segment. Defaults to method name.
        name: Optional name for the route. Defaults to method name.
    """

    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        func.openviper_action = {
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
    serializer_class: type | None = None

    #: List of authentication classes to apply to this view.
    #: ``None`` inherits ``settings.DEFAULT_AUTHENTICATION_CLASSES``.
    #: Set to ``[]`` to explicitly disable per-view authentication.
    authentication_classes: (
        list[type[AuthenticatorProtocol] | AuthenticatorProtocol | str] | None
    ) = None

    #: List of permission classes to apply to this view.
    #: ``None`` inherits ``settings.DEFAULT_PERMISSION_CLASSES``.
    #: Framework default is empty; unspecified views are public
    #: unless the project configures a global permission policy.
    #: Set to ``[]`` to explicitly disable per-view permission checks.
    permission_classes: list[type[PermissionProtocol] | PermissionProtocol | str] | None = None

    #: List of throttle classes to apply to this view.
    #: ``None`` inherits ``settings.DEFAULT_THROTTLE_CLASSES`` when present.
    #: Set to ``[]`` to explicitly disable throttling.
    throttle_classes: list[type[ThrottleProtocol] | ThrottleProtocol | str] | None = None

    ALLOWED_KWARGS: frozenset[str] = frozenset()

    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            if key not in self.ALLOWED_KWARGS:
                raise TypeError(f"Invalid keyword argument {key!r}")
            setattr(self, key, value)

    # Core dispatch - authenticate, authorise, then delegate to handler.

    async def dispatch(self, request: Request, **kwargs: str) -> Response:
        """Route *request* to the appropriate handler method.

        If the HTTP method is not in :attr:`http_method_names` or if the
        subclass does not define a handler for it, return a 405 response.
        """
        method = request.method.lower()
        if method not in self.http_method_names:
            return cast("Response", self.http_method_not_allowed(request))

        # Authenticate, then check permissions, then check throttles.
        await self.perform_authentication(request)
        await self.check_permissions(request)
        await self.check_throttles(request)

        # Delegate HEAD to get() when no explicit head() handler is defined.
        if method == "head" and not hasattr(type(self), "head"):
            method = "get"

        handler = cast("HandlerCallable", getattr(self, method, self.http_method_not_allowed))
        result = await handler(request, **kwargs)
        if isinstance(result, (dict, list)):
            return JSONResponse(result)
        response = cast("Response", result)

        if request.method == "HEAD":
            response.body = b""
        return response

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
            except (ValueError, KeyError, TypeError):
                # Per-view auth failures are ignored unless
                # a permission class requires them.
                logger.debug("Authentication failed for %s", authenticator, exc_info=True)

    def get_authenticators(self) -> list[AuthenticatorProtocol]:
        """Load and instantiate the authentication classes."""
        return cast(
            "list[AuthenticatorProtocol]",
            resolve_component_list(self.authentication_classes, "DEFAULT_AUTHENTICATION_CLASSES"),
        )

    async def check_permissions(self, request: Request) -> None:
        """Check if the request should be permitted.

        Iterates through :attr:`permission_classes` and calls
        ``has_permission(request, self)`` on each.

        Args:
            request: The incoming request.

        Raises:
            PermissionDenied: If any permission check fails.
        """
        # Superusers bypass all view-level permission checks.
        if getattr(request.user, "is_superuser", False):
            return

        for permission in self.get_permissions():
            if not await permission.has_permission(request, self):
                self.permission_denied(request)

    async def check_object_permissions(self, request: Request, obj: object) -> None:
        """
        Check if the request should be permitted to access the given object.
        Raises PermissionDenied if any permission check fails.
        """
        # Superusers bypass all object-level permission checks.
        if getattr(request.user, "is_superuser", False):
            return

        for permission in self.get_permissions():
            if not await permission.has_object_permission(request, self, obj):
                self.permission_denied(request)

    def get_permissions(self) -> list[PermissionProtocol]:
        """Instantiate and return the list of permissions that this view requires."""
        return cast(
            "list[PermissionProtocol]",
            resolve_component_list(self.permission_classes, "DEFAULT_PERMISSION_CLASSES"),
        )

    def get_throttles(self) -> list[ThrottleProtocol]:
        """Instantiate and return the list of throttles that this view uses."""
        return cast(
            "list[ThrottleProtocol]",
            resolve_component_list(self.throttle_classes, "DEFAULT_THROTTLE_CLASSES"),
        )

    async def check_throttles(self, request: Request) -> None:
        """Check request against each configured throttle.

        Each throttle must expose an async ``allow_request(request, view) -> bool``
        method and a ``wait() -> float | None`` method returning seconds to retry.

        Raises:
            TooManyRequests: If any throttle does not permit the request.
        """
        for throttle in self.get_throttles():
            if not await throttle.allow_request(request, self):
                wait = throttle.wait() if callable(getattr(throttle, "wait", None)) else None
                retry_after = int(wait) if wait is not None else None
                raise TooManyRequests(retry_after=retry_after)

    def permission_denied(self, request: Request, message: str | None = None) -> None:
        """If request is not permitted, determine what kind of exception to raise."""
        raise PermissionDenied(detail=message)

    def http_method_not_allowed(self, request: Request, **kwargs: object) -> Response:
        """Return a 405 Method Not Allowed error."""
        allowed = self.allowed_methods()
        raise MethodNotAllowed(allowed)

    async def options(self, request: Request, **kwargs: str) -> Response:
        """Handle OPTIONS by returning allowed methods in the ``Allow`` header."""

        allowed = self.allowed_methods()
        return Response(
            status_code=204,
            headers={"Allow": ", ".join(allowed)},
        )

    def allowed_methods(self) -> list[str]:
        """Return sorted list of uppercase HTTP methods this view handles.

        Cached at the class level on first call - since handlers are class
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

    @classmethod
    def as_view(
        cls,
        _action_name: str | None = None,
        **initkwargs: object,
    ) -> RouteCallable:
        """Return an async callable suitable for use as a route handler.

        Any *initkwargs* are forwarded to the view's ``__init__`` and
        stored on every instance created per request.

        Example::

            router.get("/items")(ItemView.as_view())
        """
        for key in initkwargs:
            if key in HTTP_METHODS:
                raise TypeError(
                    f"as_view() received an invalid keyword {key!r}. "
                    f"{cls.__name__} must implement HTTP method handlers "
                    f"as methods, not constructor arguments."
                )

        async def view(request: Request, **kwargs: str) -> Response:
            self = cls(**initkwargs)
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

        view.__name__ = f"{cls.__name__}_{_action_name}" if _action_name else cls.__name__
        view.__qualname__ = (
            f"{cls.__qualname__}.{_action_name}" if _action_name else cls.__qualname__
        )
        view.__doc__ = getattr(cls, _action_name).__doc__ if _action_name else cls.__doc__
        view.view_class = cls
        view.view_action = _action_name
        view.view_initkwargs = initkwargs

        if not _action_name:
            actions = []
            for attr_name in dir(cls):
                attr = getattr(cls, attr_name, None)
                action_info = getattr(attr, "openviper_action", None)
                if action_info:
                    actions.append({**action_info, "method_name": attr_name})
            view.openviper_actions = actions

        return view

    @classmethod
    def register(
        cls,
        router: Router,
        path: str,
        *,
        name: str | None = None,
        **initkwargs: object,
    ) -> None:
        """Register this view on *router* at *path*.

        Automatically determines which HTTP methods are implemented and
        registers them.

        Example::

            UserView.register(router, "/users")
        """
        handler = cls.as_view(None, **initkwargs)
        router.add(path, handler, namespace=name or cls.__name__)
