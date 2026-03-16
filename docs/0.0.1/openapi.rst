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
