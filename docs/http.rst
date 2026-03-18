.. _http:

HTTP — Requests, Responses & Views
====================================

The ``openviper.http`` package contains everything related to the HTTP
request/response cycle: the :class:`~openviper.http.request.Request` abstraction,
a family of :class:`~openviper.http.response.Response` subclasses, and
:class:`~openviper.http.views.View` for class-based views.

Overview
--------

Every view handler receives a :class:`~openviper.http.request.Request` object
and must return a :class:`~openviper.http.response.Response` (or a subclass).
Handlers are always ``async def`` coroutines.

Key Classes & Functions
-----------------------

``openviper.http.request``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: Request(scope, receive)

   Wraps an ASGI scope and receive callable.  All body-reading methods are
   coroutines.

   **Properties (synchronous):**

   .. py:attribute:: method -> str

      The HTTP method in upper-case (e.g. ``"GET"``, ``"POST"``).

   .. py:attribute:: path -> str

      The request URL path (e.g. ``"/users/42"``).

   .. py:attribute:: root_path -> str

      The ASGI ``root_path`` (application mount prefix).

   .. py:attribute:: url -> URL

      Full URL object with ``scheme``, ``netloc``, ``path``, ``query``.

   .. py:attribute:: query_params -> QueryParams

      Parsed query string as a multi-dict.  Supports ``.get()``,
      ``.getlist()``, and ``in`` tests.

   .. py:attribute:: headers -> Headers

      Case-insensitive, immutable header map.  Access like a dict:
      ``request.headers["content-type"]``.

   .. py:attribute:: cookies -> dict[str, str]

      Parsed ``Cookie`` header.

   .. py:attribute:: path_params -> dict[str, Any]

      Path parameters captured by the router (e.g. ``{"id": 42}``).

   .. py:attribute:: client -> tuple[str, int] | None

      ``(ip, port)`` of the connected client, or ``None`` for UNIX sockets.

   .. py:attribute:: state -> dict[str, Any]

      Per-request mutable storage for middleware to attach data.

   .. py:attribute:: user

      The authenticated user attached by :class:`AuthenticationMiddleware`.
      An :class:`~openviper.auth.models.AnonymousUser` when unauthenticated.

   .. py:attribute:: auth

      Auth info dict attached by :class:`AuthenticationMiddleware`
      (e.g. ``{"type": "jwt", "claims": {...}}``).

   **Raw header lookup:**

   .. py:method:: header(name: bytes) -> bytes | None

      O(1) raw header lookup.  *name* must be lower-cased bytes
      (e.g. ``b"content-type"``).

   **Body reading (all coroutines):**

   .. py:method:: body() -> Awaitable[bytes]

      Read and cache the full request body.  Limited to **10 MB** by
      default.  Raises ``ValueError`` when Content-Length is exceeded.

   .. py:method:: json() -> Awaitable[Any]

      Parse the body as JSON.

   .. py:method:: form() -> Awaitable[ImmutableMultiDict]

      Parse ``application/x-www-form-urlencoded`` or ``multipart/form-data``.
      Returns both regular fields and :class:`UploadFile` objects in the
      same dict-like structure.

.. py:class:: UploadFile(filename, content_type, file)

   Represents an uploaded file from a multipart form submission.

   .. py:attribute:: filename -> str
   .. py:attribute:: content_type -> str

   .. py:method:: read(size=-1) -> Awaitable[bytes]

      Read bytes from the underlying file off-thread (non-blocking).

   .. py:method:: seek(offset) -> Awaitable[None]

      Seek within the file off-thread.

   .. py:method:: close() -> Awaitable[None]

      Close the file handle.

``openviper.http.response``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

All response classes accept ``status_code`` and ``headers`` arguments.
The ``headers`` dict may include any additional response headers.

.. py:class:: Response(content=None, status_code=200, headers=None, media_type=None)

   Base ASGI response.  ``content`` may be ``bytes``, ``str``, or ``None``.

   .. py:method:: set_cookie(key, value="", max_age=None, expires=None, path="/", domain=None, secure=False, httponly=False, samesite="lax")

      Append a ``Set-Cookie`` header.

   .. py:method:: delete_cookie(key, path="/", domain=None)

      Append a ``Set-Cookie`` header that expires the named cookie.

   .. py:attribute:: headers -> MutableHeaders

      Mutable response header map.  Use ``.set()`` or ``["name"] = value``
      to add/change headers before the response is sent.

.. py:class:: JSONResponse(content, status_code=200, headers=None, indent=None)

   Serialize *content* to JSON using ``orjson`` (C extension).  Handles
   ``datetime``, ``date``, ``UUID``, and FK proxy objects automatically.
   Pass ``indent=2`` for pretty-printed output.

.. py:class:: HTMLResponse(content=None, status_code=200, headers=None, template=None, context=None, template_dir="templates")

   Return HTML.  Either pass *content* as a string, or provide *template*
   (a Jinja2 template name) and *context* for template rendering.

.. py:class:: PlainTextResponse(content, status_code=200, headers=None)

   Return a plain-text string with ``Content-Type: text/plain``.

.. py:class:: RedirectResponse(url, status_code=307, headers=None)

   HTTP redirect to *url*.  Default status is 307 (Temporary Redirect).
   Use ``status_code=301`` for permanent redirects.

.. py:class:: StreamingResponse(content, status_code=200, headers=None, media_type=None)

   Stream an async generator (or sync iterator) of bytes chunks to the
   client.  *content* may also be a zero-argument callable that returns an
   async generator.

.. py:class:: FileResponse(path, status_code=200, headers=None, *, media_type=None, filename=None, allowed_dir=None)

   Stream a file from the filesystem.  Automatically sets
   ``Content-Type``, ``ETag``, ``Last-Modified``, and
   ``Content-Disposition`` (when *filename* is given).  Supports
   ``If-None-Match`` and ``If-Modified-Since`` conditional requests
   (returns 304 when appropriate).

   Pass *allowed_dir* to restrict *path* to a safe directory, preventing
   path-traversal attacks.

.. py:class:: GZipResponse(content, minimum_size=500, compresslevel=6)

   Wrap another :class:`Response` and gzip-compress its body when its size
   exceeds *minimum_size* bytes.

.. note::

   For template rendering use
   ``HTMLResponse(template="…", context={…})`` — see :ref:`template`.

Common HTTP Status Codes
~~~~~~~~~~~~~~~~~~~~~~~~

The ``status_code`` parameter accepts any integer.  Commonly used values:

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Code
     - Meaning
   * - 200
     - OK
   * - 201
     - Created
   * - 204
     - No Content
   * - 301
     - Moved Permanently
   * - 302 / 307
     - Redirect (temporary)
   * - 400
     - Bad Request
   * - 401
     - Unauthorized
   * - 403
     - Forbidden
   * - 404
     - Not Found
   * - 405
     - Method Not Allowed
   * - 422
     - Unprocessable Entity (validation errors)
   * - 429
     - Too Many Requests
   * - 500
     - Internal Server Error

``openviper.http.views``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: View

   Base class-based view.  Subclass and implement one or more HTTP-verb
   methods (``get``, ``post``, ``put``, ``patch``, ``delete``, ``head``,
   ``options``).  Unimplemented methods return **405 Method Not Allowed**.

   **Class attributes:**

   .. py:attribute:: http_method_names
      :type: list[str]

      Lowercase method names this view handles.  Defaults to all standard
      HTTP verbs.

   .. py:attribute:: serializer_class

      Optional Pydantic serializer attached for OpenAPI ``requestBody``
      schema generation.

   **Methods:**

   .. py:method:: dispatch(request, **kwargs) -> Awaitable[Response]

      Route *request* to the appropriate handler method.

   .. py:classmethod:: as_view(**initkwargs) -> Callable

      Return an async callable suitable for use as a route handler.
      *initkwargs* are forwarded to ``__init__`` for each request.

   .. py:classmethod:: register(router, path, *, name=None, **initkwargs)

      Shorthand to register the view on *router* at *path*.  Automatically
      determines which HTTP methods are implemented.

Example Usage
-------------

.. seealso::

   Working projects that demonstrate HTTP views:

   - `examples/flexible/ <https://github.com/mymi14s/openviper/tree/master/examples/flexible>`_ — function-based views with ``JSONResponse``
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — class-based ``View`` with REST methods

Function-Based Views
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.routing.router import Router
    from openviper.http.request import Request
    from openviper.http.response import JSONResponse

    router = Router()

    @router.get("/posts")
    async def list_posts(request: Request) -> JSONResponse:
        posts = await Post.objects.filter(is_published=True).order_by("-created_at").all()
        return JSONResponse([p._to_dict() for p in posts])

    @router.post("/posts")
    async def create_post(request: Request) -> JSONResponse:
        data = await request.json()
        post = await Post.objects.create(**data)
        return JSONResponse(post._to_dict(), status_code=201)

Reading Query Parameters
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @router.get("/search")
    async def search(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "")
        page = int(request.query_params.get("page", 1))
        return JSONResponse({"query": q, "page": page})

Class-Based Views
~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.http.views import View
    from openviper.http.response import JSONResponse
    from openviper.exceptions import NotFound

    class PostDetailView(View):
        async def get(self, request: Request, post_id: int) -> JSONResponse:
            post = await Post.objects.get_or_none(id=post_id)
            if post is None:
                raise NotFound()
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

    # Register with router
    PostDetailView.register(router, "/posts/{post_id:int}")

File Upload
~~~~~~~~~~~

.. code-block:: python

    @router.post("/upload")
    async def upload(request: Request) -> JSONResponse:
        form = await request.form()
        avatar = form.get("avatar")          # UploadFile instance
        if avatar:
            content = await avatar.read()
            # save content …
        return JSONResponse({"filename": avatar.filename if avatar else None})

Cookie Handling
~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.http.response import JSONResponse

    @router.post("/set-pref")
    async def set_preference(request: Request) -> JSONResponse:
        response = JSONResponse({"status": "ok"})
        response.set_cookie(
            "theme",
            "dark",
            max_age=60 * 60 * 24 * 365,   # 1 year
            httponly=False,
            samesite="lax",
        )
        return response

    @router.post("/clear-pref")
    async def clear_preference(request: Request) -> JSONResponse:
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("theme")
        return response

Streaming Response
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.http.response import StreamingResponse
    import asyncio

    async def event_generator():
        for i in range(10):
            yield f"data: {i}\n\n".encode()
            await asyncio.sleep(1)

    @router.get("/events")
    async def sse(request: Request) -> StreamingResponse:
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

File Download
~~~~~~~~~~~~~

.. code-block:: python

    from openviper.http.response import FileResponse

    @router.get("/download/{filename:str}")
    async def download(request: Request, filename: str) -> FileResponse:
        return FileResponse(
            f"/media/uploads/{filename}",
            filename=filename,                     # triggers Content-Disposition
            allowed_dir="/media/uploads",          # prevent path traversal
        )

Redirect
~~~~~~~~

.. code-block:: python

    from openviper.http.response import RedirectResponse

    @router.get("/old-url")
    async def old_url(request: Request) -> RedirectResponse:
        return RedirectResponse("/new-url", status_code=301)

Template Rendering
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.http.response import HTMLResponse

    @router.get("/")
    async def home(request: Request) -> HTMLResponse:
        posts = await Post.objects.filter(is_published=True).limit(10).all()
        return HTMLResponse(template="home.html", context={"posts": posts, "request": request})

GZip Compression
~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.http.response import JSONResponse, GZipResponse

    @router.get("/large-data")
    async def large_data(request: Request) -> GZipResponse:
        data = await fetch_large_dataset()
        return GZipResponse(JSONResponse(data), minimum_size=1024, compresslevel=6)
