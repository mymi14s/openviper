"""Class-based views for OpenViper.

Provides :class:`View` — a base class that dispatches incoming requests
to handler methods named after the HTTP verb (``get``, ``post``, ``put``,
``patch``, ``delete``, ``head``, ``options``).

Usage with a router::

    from openviper.http.views import View
    from openviper.http.response import JSONResponse

    class UserListView(View):
        async def get(self, request):
            users = await User.objects.all()
            return JSONResponse([u._to_dict() for u in users])

        async def post(self, request):
            data = await request.json()
            user = await User.objects.create(**data)
            return JSONResponse(user._to_dict(), status_code=201)

    router.route("/users", methods=["GET", "POST"])(UserListView.as_view())
    # — or use the shorthand —
    UserListView.register(router, "/users")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from openviper.exceptions import MethodNotAllowed
from openviper.http.response import Response

if TYPE_CHECKING:
    from openviper.http.request import Request
    from openviper.routing.router import Router

# HTTP methods that View can dispatch to.
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


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
    serializer_class: Any = None

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
        handler = getattr(self, method, self.http_method_not_allowed)
        return cast("Response", await handler(request, **kwargs))

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
    def as_view(cls, **initkwargs: Any) -> Any:
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
            return await self.dispatch(request, **kwargs)

        # Preserve metadata for introspection / debugging
        view.__name__ = cls.__name__
        view.__qualname__ = cls.__qualname__
        view.__doc__ = cls.__doc__
        view.view_class = cls  # type: ignore[attr-defined]
        view.view_initkwargs = initkwargs  # type: ignore[attr-defined]
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
        router.route(path, methods=methods, name=name or cls.__name__)(handler)
