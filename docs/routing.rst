.. _routing:

Routing
=======

The ``openviper.routing`` package provides a fast, regex-backed URL router
with support for typed path parameters, HTTP method filtering, sub-routers
(blueprints), and per-router middleware.

Overview
--------

:class:`~openviper.routing.router.Router` is the central class.  Register
handlers with method-specific decorators (``@router.get``, ``@router.post``,
etc.) or with the generic ``@router.route`` decorator.  Routers can be
composed hierarchically via ``include_router`` or the ``include()`` helper.

Path parameters are declared inside curly braces.  An optional type
specifier converts the value automatically:

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Syntax
     - Converter
     - Example
   * - ``{name}``
     - ``str`` (default)
     - ``/users/{username}``
   * - ``{id:int}``
     - ``int`` (1–18 digits)
     - ``/posts/{id:int}``
   * - ``{price:float}``
     - ``float``
     - ``/items/{price:float}``
   * - ``{key:uuid}``
     - ``str`` (UUID format validated)
     - ``/tokens/{key:uuid}``
   * - ``{slug:slug}``
     - ``str`` (``[-a-zA-Z0-9_]+``)
     - ``/blog/{slug:slug}``
   * - ``{rest:path}``
     - ``str`` (greedy, matches ``/`` too)
     - ``/files/{rest:path}``

The router resolves routes by specificity: paths with more literal segments
are tried before paths with parameters, so ``/users/me`` beats
``/users/{id:int}``.

Key Classes
-----------

.. py:class:: openviper.routing.router.Router(prefix="", middlewares=None, tags=None, namespace=None)

   URL router.

   .. py:method:: route(path, methods, name=None, middlewares=None)

      Register a handler for *path* + *methods*.  *middlewares* is an
      optional list of per-route ASGI middleware callables applied only to
      this route.

   .. py:method:: get(path, name=None, middlewares=None)
   .. py:method:: post(path, name=None, middlewares=None)
   .. py:method:: put(path, name=None, middlewares=None)
   .. py:method:: patch(path, name=None, middlewares=None)
   .. py:method:: delete(path, name=None, middlewares=None)
   .. py:method:: options(path, name=None, middlewares=None)

      Convenience decorators for the respective HTTP methods.

   .. py:method:: any(path, name=None, middlewares=None)

      Register a handler that matches ``GET``, ``POST``, ``PUT``,
      ``PATCH``, ``DELETE``, ``HEAD``, and ``OPTIONS``.

   .. py:method:: add(path, handler, methods=None, namespace=None, middlewares=None)

      Register a handler programmatically (non-decorator form).  When
      *handler* comes from ``View.as_view()`` and *methods* is omitted,
      class-view methods are discovered the same way as
      ``View.register(...)``.

   .. py:method:: include_router(router, prefix="", namespace=None)

      Mount a sub-router as a live reference.  Routes added to the
      sub-router later are automatically visible through this router.
      When *namespace* is given, all route names become
      ``"namespace:route_name"`` in this router's name index.

   .. py:method:: resolve(method, path) -> tuple[Route, dict[str, str | int | float]]

      Match *method* + *path* against registered routes.  Returns the
      matched :class:`Route` and a dict of extracted path parameters.
      Raises :class:`~openviper.exceptions.NotFound`,
      :class:`~openviper.exceptions.MethodNotAllowed`, or
      :class:`PathSecurityError` on failure.

   .. py:method:: url_for(name, **path_params) -> str

      Reverse-generate a URL from a named route.  *path_params* values
      must be ``str``, ``int``, or ``float``.  Values containing null
      bytes, ``..``, or ``/`` raise ``ValueError``.  Returns the path
      string with parameters filled in.  Raises ``KeyError`` if the
      name is not registered.

   .. py:attribute:: routes -> list[Route]

      All routes including sub-router routes, flattened and cached.
      Indices (dispatch, name, exact-match) are built lazily on first
      access and invalidated whenever routes or sub-routers change.

.. py:class:: openviper.routing.router.Route

   Dataclass representing a single route registration.

   .. py:attribute:: path
      :type: str

      URL path template (e.g. ``/users/{id:int}``).

   .. py:attribute:: methods
      :type: set[str]

      Allowed HTTP methods (uppercased).

   .. py:attribute:: handler
      :type: Handler

      Async callable that handles the request.

   .. py:attribute:: name
      :type: str | None

      Optional name for reverse URL generation.

   .. py:attribute:: middlewares
      :type: list[Middleware]

      Per-route middleware stack.

   .. py:attribute:: tags
      :type: list[str]

      OpenAPI tags for grouping this route in the schema.

   .. py:method:: match(path) -> dict[str, str | int | float] | None

      Return extracted path params if *path* matches, else ``None``.

.. py:class:: openviper.routing.router.PathSecurityError

   Raised when a request path contains disallowed security-sensitive
   patterns (null bytes, encoded slashes, or directory traversal).

.. py:function:: openviper.routing.router.include(router, prefix="", namespace=None) -> Router

   Return a copy of *router* with *prefix* prepended to every route
   path.  The original router is left unchanged.  When *namespace* is
   supplied, all route names become ``"namespace:route_name"`` in any
   parent router's name index.

Path Security
-------------

.. py:function:: openviper.routing.sanitize_request_path(path) -> str

   Sanitize and normalize a request path before routing.  Rejects null
   bytes, encoded slashes (``%2F``, ``%5C%2F``), and directory traversal
   (``..`` segments).  Collapses consecutive slashes.  Raises
   :class:`PathSecurityError` on malicious input.

.. py:function:: openviper.routing.router.normalize_path(path) -> str

   Collapse consecutive slashes in *path*.  Used for combining
   developer-defined route prefixes.  Does **not** apply security
   checks since route templates are trusted input.

Path Compilation
----------------

.. py:function:: openviper.routing.router.compile_path(path) -> tuple[Pattern, dict]

   Convert a path template (e.g. ``/users/{id:int}``) to a compiled
   regex and a dict of parameter converters.  Cached with
   ``@lru_cache(maxsize=256)``.

.. py:function:: openviper.routing.router.route_first_segment(path) -> str | None

   Return the first static path segment, or ``None`` if dynamic.
   Used to build the dispatch index.

.. py:function:: openviper.routing.router.route_specificity(path) -> tuple[int, int]

   Return ``(literal_count, total_count)`` for route sorting.  More
   specific routes (more literal segments) are tried first.

View Inference Helpers
----------------------

.. py:function:: openviper.routing.router.infer_view_method_path(path, method) -> str

   Append path parameters declared after ``request`` in a view method
   signature to the route path template.

.. py:function:: openviper.routing.router.inferred_route_name(base_name, base_path, inferred_path) -> str

   Return a stable distinct name for inferred parameterized view
   routes by appending parameter names to *base_name*.

Security Constants
------------------

.. py:data:: openviper.routing.router.NULL_BYTE_RE

   Compiled regex matching null bytes (``\\x00``) in request paths.

.. py:data:: openviper.routing.router.TRAVERSAL_RE

   Compiled regex matching directory traversal (``..``) segments.

.. py:data:: openviper.routing.router.ENCODED_SLASH_RE

   Compiled regex matching encoded slashes (``%2F``, ``%5C%2F``).

.. py:data:: openviper.routing.router.MULTI_SLASH_RE

   Compiled regex matching two or more consecutive slashes.

.. py:data:: openviper.routing.router.PARAM_PLACEHOLDER_RE

   Compiled regex matching ``{name}`` or ``{name:type}`` placeholders.

.. py:data:: openviper.routing.router.ANY_PARAM_RE

   Compiled regex matching any ``{…}`` segment for validation.

.. py:data:: openviper.routing.router.VALID_PARAM_RE

   Compiled regex validating path parameter names as Python
   identifiers.

.. py:data:: openviper.routing.router.ANNOTATION_CONVERTERS

   Mapping from Python type annotations to converter names
   (e.g. ``int`` → ``"int"``).

.. py:data:: openviper.routing.router.CONVERTERS

   Mapping of converter names to ``(regex, callable)`` pairs.

.. py:data:: openviper.routing.router.DYNAMIC

   Sentinel key (``"__dynamic__"``) in the dispatch index for routes
   whose first segment is a parameter.

Type Aliases
------------

.. py:data:: openviper.routing.router.Handler

   ``Callable[..., Awaitable[Any]]`` - async handler signature.

.. py:data:: openviper.routing.router.Middleware

   ``Callable[[Any, Any], Awaitable[Any]]`` - async middleware
   signature.

Example Usage
-------------

.. seealso::

   Working projects that demonstrate routing patterns:

   - `examples/flexible/ <https://github.com/mymi14s/openviper/tree/master/examples/flexible>`_ - decorator-based routing (``@app.get``, ``@app.post``)
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - ``Router`` class, class-based views, typed path params
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - multi-router mounting at ``/api``

Basic Route Registration
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.routing.router import Router
    from openviper.http.request import Request
    from openviper.http.response import JSONResponse

    router = Router()

    @router.get("/")
    async def index(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @router.get("/users/{user_id:int}")
    async def get_user(request: Request, user_id: int) -> JSONResponse:
        user = await User.objects.get(id=user_id)
        return JSONResponse(user._to_dict())

    @router.post("/users")
    async def create_user(request: Request) -> JSONResponse:
        data = await request.json()
        user = await User.objects.create(**data)
        return JSONResponse(user._to_dict(), status_code=201)

Named Routes and URL Reversal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @router.get("/posts/{post_id:int}", name="post-detail")
    async def post_detail(request: Request, post_id: int) -> JSONResponse: ...

    # Reverse the URL
    url = router.url_for("post-detail", post_id=42)   # "/posts/42"

    # Slug-based route
    @router.get("/blog/{slug:slug}", name="blog-post")
    async def blog_post(request: Request, slug: str) -> JSONResponse: ...

    url = router.url_for("blog-post", slug="my-first-post")

Non-Decorator Registration
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def my_handler(request: Request) -> JSONResponse:
        return JSONResponse({"hello": "world"})

    router.add("/hello", my_handler, methods=["GET", "POST"], namespace="hello")

Sub-Router / Blueprint Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.routing.router import Router, include

    api_v1 = Router(prefix="/api/v1")

    blog_router = Router()

    @blog_router.get("/posts")
    async def list_posts(request: Request) -> JSONResponse: ...

    @blog_router.get("/posts/{post_id:int}")
    async def get_post(request: Request, post_id: int) -> JSONResponse: ...

    api_v1.include_router(include(blog_router, prefix="/blog"))
    # Routes now at /api/v1/blog/posts and /api/v1/blog/posts/{post_id:int}

Router-level Middleware
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.middleware.ratelimit import RateLimitMiddleware

    # Attach middleware to the entire sub-router
    api_router = Router(prefix="/api", middlewares=[my_auth_middleware])

    @api_router.get("/data")
    async def get_data(request: Request) -> JSONResponse: ...

Per-Route Middleware
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.middleware.ratelimit import rate_limit

    @router.get(
        "/expensive",
        middlewares=[some_custom_middleware],
    )
    async def expensive_view(request: Request) -> JSONResponse: ...

Class-Based Views
~~~~~~~~~~~~~~~~~

Use :class:`~openviper.http.views.View` with the router.  See :ref:`http`
for the full ``View`` API.  Parameters declared after ``request`` on standard
HTTP handlers are appended to the registered path automatically.

.. code-block:: python

    from openviper.http.views import View
    from openviper.http.response import JSONResponse

    class PostView(View):
        async def get(self, request: Request, post_id: int) -> JSONResponse:
            post = await Post.objects.get(id=post_id)
            return JSONResponse(post._to_dict())

        async def put(self, request: Request, post_id: int) -> JSONResponse:
            post = await Post.objects.get(id=post_id)
            data = await request.json()
            for k, v in data.items():
                setattr(post, k, v)
            await post.save()
            return JSONResponse(post._to_dict())

        async def delete(self, request: Request, post_id: int) -> JSONResponse:
            post = await Post.objects.get(id=post_id)
            await post.delete()
            return JSONResponse({"deleted": True})

    # Register all implemented HTTP methods automatically.
    # These handlers are mounted at /posts/{post_id:int}.
    PostView.register(router, "/posts", name="post-detail")

    # Equivalent shorthand when methods= is omitted:
    router.add("/posts", PostView.as_view(), namespace="post-detail")

Collection and detail routes may be generated from one view class when the
method signatures differ:

.. code-block:: python

    class PostView(View):
        async def post(self, request: Request) -> JSONResponse:
            data = await request.json()
            return JSONResponse(data, status_code=201)

        async def get(self, request: Request, post_id: int) -> JSONResponse:
            post = await Post.objects.get(id=post_id)
            return JSONResponse(post._to_dict())

        async def put(self, request: Request, post_id: int) -> JSONResponse:
            data = await request.json()
            post = await Post.objects.get(id=post_id)
            for key, value in data.items():
                setattr(post, key, value)
            await post.save()
            return JSONResponse(post._to_dict())

    PostView.register(router, "/posts")

This registers ``POST /posts`` plus ``GET`` and ``PUT`` at
``/posts/{post_id:int}``.  ``OPTIONS`` remains available at runtime for
class views, but it is omitted from generated OpenAPI operation lists.

Mounting in the Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # settings.py or app setup
    from openviper.routing.router import Router
    from myapp.views import router as app_router

    main_router = Router()
    main_router.include_router(app_router)

    # routes.py (used by OpenViper app discovery)
    route_paths = [
        ("/", main_router),
    ]
