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

No extra code or decorator is required - the schema is generated automatically
from route registration and type annotations.

Key Functions
-------------

``openviper.openapi.schema``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: generate_openapi_schema(routes, title="OpenViper API", description="", version="1.0.0") -> dict

   Generate an OpenAPI 3.1.0 schema dict from a list of
   :class:`~openviper.routing.router.Route` objects.

   - Path parameters (e.g. ``{id:int}``) are included as ``parameters``.
   - Return type annotations that are Pydantic models are reflected into
     ``responses["200"]["content"]``.
   - When a ``serializer_class`` is set on a class-based view, it is used to
     produce the ``requestBody`` schema.
   - Python built-in types are mapped to JSON Schema types automatically.
   - Results are cached by a SHA-256 fingerprint of the routes, title,
     description, and version; call :func:`reset_openapi_cache` to invalidate.

.. py:function:: reset_openapi_cache() -> None

   Clear the generated schema cache.  Useful after dynamic route registration
   in tests.

.. py:function:: filter_openapi_routes(routes: list[Route]) -> list[Route]

   Filter a list of :class:`~openviper.routing.router.Route` objects
   according to ``OPENAPI["exclude"]``.

   * ``"__ALL__"`` → returns ``[]``.
   * A ``list[str]`` of prefixes → drops routes whose path starts with any
     of the given prefixes (case-insensitive, leading ``/`` normalised).
   * Empty list or missing setting → returns all routes unchanged.
   * Any other value triggers a warning and returns all routes unchanged.

.. py:function:: request_schema(serializer_cls: type) -> Callable[[RouteHandler], RouteHandler]

   Decorator that attaches a serializer class to a route handler.  The
   OpenAPI schema generator uses it to produce a ``requestBody`` entry so
   that Swagger UI displays the input form correctly.

   Works with both function-based and class-based views:

   .. code-block:: python

       @router.post("/blogs")
       @request_schema(BlogSerializer)
       async def create_blog(request):
           ...

   For class-based views, prefer setting ``serializer_class`` on the
   ``View`` subclass instead - it is picked up automatically.

.. py:function:: tag_from_path(path: str) -> str

   Derive a meaningful OpenAPI tag from a route path.  Skips path
   parameters, generic prefixes (``api``, ``v1``, ``v2``, ``v3``), and
   version segments.  Returns the first remaining segment capitalised, or
   ``"Root"`` when none is found.

.. py:function:: python_type_to_schema(annotation) -> dict

   Convert a Python type annotation to a JSON Schema dict.  Handles
   built-in types, ``list[X]``, ``dict``, ``Optional[X]`` / ``Union`` types,
   and Pydantic models that expose ``model_json_schema()``.

.. py:function:: extract_path_params(path: str) -> list[dict]

   Extract ``{name:type}`` segments from a path template.  Parameter names
   exceeding 128 characters are rejected to prevent resource-exhaustion
   vectors.

.. py:function:: openapi_path(path: str) -> str

   Convert an OpenViper path (e.g. ``/users/{id:int}``) to the OpenAPI
   form (e.g. ``/users/{id}``).

.. py:function:: resolve_request_schema(handler: RouteHandler) -> type | None

   Determine the request body schema class for a handler.  Resolution
   order:

   1. ``handler.openapi_request_schema`` - set by :func:`request_schema`
   2. ``handler.view_class.serializer_class`` - class-based view attribute
   3. Docstring tags (``Request: <Name>`` / ``Body: <Name>``)
   4. Source-code auto-detection (``<Name>.validate()`` calls)

.. py:function:: format_operation_description(docstring: str) -> str

   Render structured docstrings as safe HTML for documentation UIs.
   Recognises ``Request:``, ``Body:``, ``Example Request:``, and
   ``Example Response:`` sections and formats them with appropriate HTML
   tags.

.. py:function:: build_operation(route: Route, method: str) -> dict

   Build an OpenAPI operation object for a given route and HTTP method.
   Combines path parameters, request body, response schema, tags, and
   per-route security into a single operation dict.

.. py:function:: build_request_body(handler, method, hints, doc_handler=None) -> dict | None

   Resolve the request body schema for a handler at a given HTTP method.
   Checks the serializer, docstring examples, inline schemas, and
   parameter annotations in order.

.. py:function:: build_per_route_security(handler: RouteHandler) -> list[dict] | None

   Return an explicit ``security`` list for a handler when it restricts
   authentication.  Returns ``None`` when no per-route
   ``authentication_classes`` are set, letting the global security
   requirement remain in effect.

.. py:function:: build_responses(method, docstring, response_schema) -> dict

   Build the ``responses`` dict for an OpenAPI operation.  Includes the
   ``200`` success response with its schema, example responses from
   docstrings, and a ``422`` validation error entry for mutating methods.

.. py:data:: OPENAPI_REQUEST_SCHEMA_ATTR

   The attribute name (``"openapi_request_schema"``) used to carry the
   schema class on a handler function, set by :func:`request_schema`.

``openviper.openapi.router``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: read_openapi_settings() -> dict[str, object]

   Read and normalise the ``OPENAPI`` config dict from settings,
   then fill defaults for any missing keys.

.. py:function:: should_register_openapi() -> bool

   Return ``True`` when the OpenAPI router should be registered.

   Returns ``False`` when ``OPENAPI["enabled"]`` is ``False`` **or** when
   ``OPENAPI["exclude"]`` is ``"__ALL__"``.  The :class:`~openviper.app.OpenViper`
   application calls this at start-up to decide whether to mount the docs
   routes.

``openviper.openapi.utils``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Re-exports the public helpers so callers can import from a single, stable
location without depending on internal module structure.

.. py:function:: filter_openapi_routes(routes) -> list[Route]
   :no-index:

   Filter a list of :class:`Route` objects according to
   ``OPENAPI["exclude"]``.  Re-exported from
   :mod:`~openviper.openapi.schema`.

.. py:function:: should_register_openapi() -> bool
   :no-index:

   Return ``True`` when the OpenAPI router should be registered.
   Re-exported from :mod:`~openviper.openapi.router`.

``openviper.openapi.ui``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: get_swagger_html(title, openapi_url) -> str

   Generate the Swagger UI HTML page that loads the schema from *openapi_url*.

.. py:function:: get_redoc_html(title, openapi_url) -> str

   Generate the ReDoc HTML page.

.. py:function:: escape_html_attr(value: str) -> str

   Escape a value for safe inclusion in an HTML attribute (both single and
   double quote styles).  Uses ``html.escape`` with quote mode and
   additionally replaces ``'`` with ``&#x27;``.

``openviper.openapi.schema`` - Types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: RouteHandler

   A :class:`~typing.Protocol` describing the structural interface of a
   route handler callable.  Handlers must be callable and may carry
   optional metadata attributes set by decorators or view machinery:

   - ``__name__`` (``str``) - function name
   - ``__module__`` (``str``) - module name
   - ``view_class`` (``type | None``) - class-based view class
   - ``view_action`` (``str | None``) - view action name
   - ``openapi_request_schema`` (``type | None``) - set by :func:`request_schema`
   - ``authentication_classes`` (``list[type]``) - auth classes
   - ``__globals__`` (``dict[str, Any]``) - function globals

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

Method Documentation
~~~~~~~~~~~~~~~~~~~~

OpenAPI uses the first line of each handler docstring as the operation summary
and the remaining lines as the description.  For class-based views, each HTTP
method contributes its own documentation.

For small request bodies, an inline ``Body`` or ``Request`` block can build a
request schema without a serializer:

.. code-block:: python

    class PostCreateView(View):
        async def post(self, request) -> JSONResponse:
            """Create a post.

            Body: {
                "title": str,
                "state": str,  # "DRAFT", "PUBLISHED"
                "author_id": str (UUID)
            }
            """
            ...

Supported inline field types are ``str``, ``int``, ``float``, ``bool``,
``bytes``, ``list``, ``dict``, and ``UUID``.  Quoted values in a trailing
comment are exposed as enum choices.  Use a serializer for nested structures,
validation rules, or schemas reused across endpoints.

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

The ``OPENAPI`` dict's ``exclude`` key lets you disable the OpenAPI router
entirely or remove specific base routes from the generated schema without
changing your routing registration.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Value
     - Effect
   * - ``[]`` (default)
     - Non-admin routes appear in the schema; docs endpoints are active.
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

Set ``OPENAPI["exclude"] = "__ALL__"`` to prevent the docs and schema endpoints
from being registered. This is recommended for production deployments where
you do not want to expose API documentation.

.. code-block:: python

    # settings.py

    OPENAPI = {
        "exclude": "__ALL__",
    }

After applying this setting, any request to ``/open-api/openapi.json``,
``/open-api/docs``, or ``/open-api/redoc`` will receive a **404** response.

Exclude Routes by Prefix
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass a list of route-path prefixes (without the leading ``/``) to remove
matching paths from the generated schema. The docs endpoint itself remains
accessible; only the schema content is filtered.

.. code-block:: python

    # Remove all /admin/* routes from the schema
    OPENAPI = {"exclude": ["admin"]}

    # Remove /admin/* and /blogs/* routes
    OPENAPI = {"exclude": ["admin", "blogs"]}

    # Remove /admin/*, /blogs/*, and /internal/* routes
    OPENAPI = {"exclude": ["admin", "blogs", "internal"]}

Admin Routes
~~~~~~~~~~~~

Routes under ``/admin`` are hidden from generated schemas by default.  To
expose them intentionally, set the admin URL explicitly:

.. code-block:: python

    OPENAPI = {"admin_url": "/admin"}

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

Using ``OPENAPI["exclude"]`` reduces the attack surface of your API:

* Hide internal admin endpoints from the public schema.
* Prevent automated scanners from discovering route structures.
* Disable the schema entirely in production to avoid information leakage.

.. seealso::

   :ref:`openapi` - main OpenAPI reference page.

API Reference - Exclusion Helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``openviper.openapi.schema``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:function:: filter_openapi_routes(routes: list[Route]) -> list[Route]
   :no-index:

   Filter a list of :class:`~openviper.routing.router.Route` objects
   according to ``OPENAPI["exclude"]``.

   * ``"__ALL__"`` → returns ``[]``.
   * A ``list[str]`` of prefixes → drops routes whose path starts with any
     of the given prefixes (case-insensitive, leading ``/`` normalised).
   * Empty list or missing setting → returns all routes unchanged.
   * Any other value triggers a warning and returns all routes unchanged.

``openviper.openapi.router``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. py:function:: should_register_openapi() -> bool
   :no-index:

   Return ``True`` when the OpenAPI router should be registered.

   Returns ``False`` when ``OPENAPI["enabled"]`` is ``False`` **or** when
   ``OPENAPI["exclude"]`` is ``"__ALL__"``.  The :class:`~openviper.app.OpenViper`
   application calls this at start-up to decide whether to mount the docs
   routes.

----

Configuration Reference
-----------------------

OPENAPI
~~~~~~~

**Type:** ``dict``
**Default:** see key table below

A dict consolidating all OpenAPI configuration.  Each key corresponds to
a flat ``OPENAPI_*`` setting; the flat names are still accepted for
backward compatibility via ``read_openapi_settings()``.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Key
     - Default
     - Description
   * - ``enabled``
     - ``True``
     - Master switch. ``False`` prevents all docs routes from registering,
       identical in effect to ``exclude = "__ALL__"``.
   * - ``title``
     - ``"OpenViper API"``
     - Title shown in Swagger UI and ReDoc.
   * - ``version``
     - ``"0.0.1"``
     - API version string in the schema ``info`` block.
   * - ``description``
     - ``""``
     - API description in the schema ``info`` block.
   * - ``schema_url``
     - ``"/open-api/openapi.json"``
     - URL at which the raw JSON schema is served.
   * - ``docs_url``
     - ``"/open-api/docs"``
     - URL for the Swagger UI page.
   * - ``redoc_url``
     - ``"/open-api/redoc"``
     - URL for the ReDoc page.
   * - ``admin_url``
     - ``None``
     - When set, admin routes are included in the schema.
   * - ``exclude``
     - ``[]``
     - Route exclusion list (see above).

Configuration Examples
~~~~~~~~~~~~~~~~~~~~~~

Disable OpenAPI entirely in production:

.. code-block:: python

    # settings.py
    OPENAPI = {"exclude": "__ALL__"}

Remove admin routes from the public schema:

.. code-block:: python

    OPENAPI = {"exclude": ["admin"]}

Remove multiple path prefixes:

.. code-block:: python

    OPENAPI = {"exclude": ["admin", "blogs", "internal", "health"]}

Customise title and version:

.. code-block:: python

    OPENAPI = {
        "title": "My Service API",
        "version": "2.1.0",
        "description": "Internal microservice for order processing.",
    }

Security Considerations
~~~~~~~~~~~~~~~~~~~~~~~

- Disable the schema entirely (``OPENAPI["exclude"] = "__ALL__"``) in
  production to prevent automated scanners from discovering your API surface.
- Use prefix exclusion to hide ``/admin`` and other sensitive sub-trees from
  publicly served documentation.
- Schema exposure is listed as a risk in OWASP API Security Top 10
  (API7: Security Misconfiguration). ``OPENAPI["exclude"]`` directly mitigates
  this risk.
