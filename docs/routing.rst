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

.. py:class:: openviper.routing.router.Router(prefix="", middlewares=None)

   URL router.

   .. py:method:: route(path, methods, name=None, middlewares=None)

      Register a handler for *path* + *methods*.  *middlewares* is an
      optional list of per-route ASGI middleware callables applied only to
      this route.

   .. py:method:: get(path, **kwargs)
   .. py:method:: post(path, **kwargs)
   .. py:method:: put(path, **kwargs)
   .. py:method:: patch(path, **kwargs)
   .. py:method:: delete(path, **kwargs)
   .. py:method:: options(path, **kwargs)

      Convenience decorators for the respective HTTP methods.
      All accept ``name=`` and ``middlewares=`` keyword arguments.

   .. py:method:: any(path, **kwargs)

      Register a handler that matches ``GET``, ``POST``, ``PUT``,
      ``PATCH``, ``DELETE``, ``HEAD``, and ``OPTIONS``.

   .. py:method:: add(path, handler, methods=None, namespace=None, middlewares=None)

      Register a handler programmatically (non-decorator form).

   .. py:method:: include_router(router)

      Merge all routes from another :class:`Router` into this one,
      applying this router's prefix.

   .. py:method:: resolve(method, path) -> tuple[Route, dict]

      Match *method* + *path* against registered routes.  Returns the
      matched :class:`Route` and a dict of extracted path parameters.
      Raises :class:`~openviper.exceptions.NotFound` or
      :class:`~openviper.exceptions.MethodNotAllowed` on failure.

   .. py:method:: url_for(name, **path_params) -> str

      Reverse-generate a URL from a named route.  Returns the path string
      with parameters filled in.  Raises ``KeyError`` if the name is not
      registered.

   .. py:attribute:: routes -> list[Route]

      All routes including sub-router routes, flattened and cached.

.. py:class:: openviper.routing.router.Route

   Immutable dataclass representing a single route registration.

   Attributes: ``path``, ``handler``, ``methods`` (set of uppercase strings),
   ``name``, ``middlewares``.

.. py:function:: openviper.routing.router.include(router, prefix="") -> Router

   Return a copy of *router* with *prefix* prepended to every route path.
   The original router is left unchanged.

Example Usage
-------------

.. seealso::

   Working projects that demonstrate routing patterns:

   - `examples/flexible/ <https://github.com/mymi14s/openviper/tree/master/examples/flexible>`_ — decorator-based routing (``@app.get``, ``@app.post``)
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — ``Router`` class, class-based views, typed path params
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — multi-router mounting at ``/api``

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
for the full ``View`` API.

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

    # Register all implemented HTTP methods automatically
    PostView.register(router, "/posts/{post_id:int}", name="post-detail")

    # Or manually
    router.route(
        "/posts/{post_id:int}",
        methods=["GET", "PUT", "DELETE"],
    )(PostView.as_view())

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
