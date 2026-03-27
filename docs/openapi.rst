.. _openapi:

OpenAPI & Swagger UI
====================

The ``openviper.openapi`` package auto-generates an OpenAPI 3.1.0 schema from
registered routes and their Python type hints, and serves interactive
Swagger UI and ReDoc documentation pages.

Overview
--------

The framework inspects every registered route's handler signature and, where
present, its ``serializer_class`` attribute to build a complete OpenAPI schema.
The schema is served as JSON at ``/open-api/schema.json`` and two interactive
UI pages are mounted at ``/open-api/docs`` (Swagger UI) and
``/open-api/redoc`` (ReDoc) by default.

No extra code or decorator is required — the schema is generated automatically
from route registration and type annotations.

Key Functions
-------------

``openviper.openapi.schema``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: generate_openapi_schema(routes, title, version, description="") -> dict

   Generate an OpenAPI 3.1.0 schema dict from a list of
   :class:`~openviper.routing.router.Route` objects.

   - Path parameters (e.g. ``{id:int}``) are included as ``parameters``.
   - Return type annotations that are Pydantic models are reflected into
     ``responses["200"]["content"]``.
   - When a ``serializer_class`` is set on a class-based view, it is used to
     produce the ``requestBody`` schema.
   - Python built-in types are mapped to JSON Schema types automatically.

.. py:function:: reset_openapi_cache() -> None

   Clear the generated schema cache.  Useful after dynamic route registration
   in tests.

``openviper.openapi.ui``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: get_swagger_html(title, openapi_url) -> str

   Generate the Swagger UI HTML page that loads the schema from *openapi_url*.

.. py:function:: get_redoc_html(title, openapi_url) -> str

   Generate the ReDoc HTML page.

Example Usage
-------------

Automatic Schema (Zero Configuration)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper import OpenViper

    app = OpenViper(
        title="Blog API",
        version="1.0.0",
    )
    # Schema available at /open-api/schema.json
    # Swagger UI at /open-api/docs
    # ReDoc at /open-api/redoc

Richer Schema via Pydantic Serializers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Attach a ``serializer_class`` to a class-based view to give Swagger UI an
input form for the request body:

.. code-block:: python

    from openviper.http.views import View
    from openviper.serializers import Serializer
    from openviper.http.response import JSONResponse

    class CreatePostSerializer(Serializer):
        title: str
        body: str
        tags: list[str] = []

    class PostCreateView(View):
        serializer_class = CreatePostSerializer

        async def post(self, request) -> JSONResponse:
            data = CreatePostSerializer.validate(await request.json())
            post = await Post.objects.create(**data.model_dump())
            return JSONResponse(post._to_dict(), status_code=201)

    PostCreateView.register(router, "/posts")

Return Type Annotation for Response Schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pydantic import BaseModel

    class PostOut(BaseModel):
        id: int
        title: str
        body: str

    @router.get("/posts/{post_id:int}")
    async def get_post(request, post_id: int) -> PostOut:
        post = await Post.objects.get(id=post_id)
        return JSONResponse(post._to_dict())

The ``PostOut`` model is reflected into the OpenAPI ``responses`` section for
this endpoint.

Accessing the Raw Schema
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.openapi.schema import generate_openapi_schema
    from openviper.routing.router import Router
    import json

    router = Router()
    # ... register routes ...

    schema = generate_openapi_schema(
        routes=router.routes,
        title="My API",
        version="2.0.0",
    )
    print(json.dumps(schema, indent=2))

.. _openapi-exclusion:

OpenAPI Exclusion
-----------------

The ``OPENAPI_EXCLUDE`` setting lets you disable the OpenAPI router entirely
or remove specific base routes from the generated schema without changing your
routing registration.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Value
     - Effect
   * - ``[]`` (default)
     - All routes appear in the schema; docs endpoints are active.
   * - ``"__ALL__"``
     - The OpenAPI router is **not registered**. ``/open-api/openapi.json``,
       ``/open-api/docs``, and ``/open-api/redoc`` all return **404**.
   * - ``["admin"]``
     - Routes whose path starts with ``/admin`` are removed from the schema.
       The docs endpoints remain accessible.
   * - ``["admin", "blogs"]``
     - Routes under ``/admin`` **and** ``/blogs`` are removed from the schema.

Disable OpenAPI
~~~~~~~~~~~~~~~

Set ``OPENAPI_EXCLUDE = "__ALL__"`` to prevent the docs and schema endpoints
from being registered. This is recommended for production deployments where
you do not want to expose API documentation.

.. code-block:: python

    # settings.py

    OPENAPI_EXCLUDE = "__ALL__"

After applying this setting, any request to ``/open-api/openapi.json``,
``/open-api/docs``, or ``/open-api/redoc`` will receive a **404** response.

Exclude Routes by Prefix
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass a list of route-path prefixes (without the leading ``/``) to remove
matching paths from the generated schema. The docs endpoint itself remains
accessible; only the schema content is filtered.

.. code-block:: python

    # Remove all /admin/* routes from the schema
    OPENAPI_EXCLUDE = ["admin"]

    # Remove /admin/* and /blogs/* routes
    OPENAPI_EXCLUDE = ["admin", "blogs"]

    # Remove /admin/*, /blogs/*, and /internal/* routes
    OPENAPI_EXCLUDE = ["admin", "blogs", "internal"]

Prefix Matching Rules
~~~~~~~~~~~~~~~~~~~~~

* Matching is **case-insensitive**: ``"Admin"`` and ``"admin"`` produce the
  same result.
* Leading slashes in a prefix are normalised: ``"/admin"`` is treated
  identically to ``"admin"``.
* Only **complete path segments** are matched.  A prefix of ``"blogs"`` will
  exclude ``/blogs`` and ``/blogs/posts`` but **not** ``/blogsearch`` or
  ``/blog``.

Security Benefits
~~~~~~~~~~~~~~~~~

Using ``OPENAPI_EXCLUDE`` reduces the attack surface of your API:

* Hide internal admin endpoints from the public schema.
* Prevent automated scanners from discovering route structures.
* Disable the schema entirely in production to avoid information leakage.

.. seealso::

   :ref:`openapi` — main OpenAPI reference page.

API Reference — Exclusion Helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``openviper.openapi.schema``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:function:: filter_openapi_routes(routes: list[Route]) -> list[Route]

   Filter a list of :class:`~openviper.routing.router.Route` objects
   according to ``settings.OPENAPI_EXCLUDE``.

   * ``"__ALL__"`` → returns ``[]``.
   * A ``list[str]`` of prefixes → drops routes whose path starts with any
     of the given prefixes (case-insensitive, leading ``/`` normalised).
   * Empty list or missing setting → returns all routes unchanged.
   * Any other value triggers a warning and returns all routes unchanged.

``openviper.openapi.router``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:function:: should_register_openapi() -> bool

   Return ``True`` when the OpenAPI router should be registered.

   Returns ``False`` when ``OPENAPI_ENABLED`` is ``False`` **or** when
   ``OPENAPI_EXCLUDE`` is ``"__ALL__"``.  The :class:`~openviper.app.OpenViper`
   application calls this at start-up to decide whether to mount the docs
   routes.
