.. _http:

HTTP - Requests, Responses & Views
====================================

The ``openviper.http`` package contains everything related to the HTTP
request/response cycle: the :class:`~openviper.http.request.Request` abstraction,
a family of :class:`~openviper.http.response.Response` subclasses,
:class:`~openviper.http.views.View` for class-based views, and a set of
shared type aliases in :mod:`~openviper.http.types`.

Overview
--------

Every view handler receives a :class:`~openviper.http.request.Request` object
and must return a :class:`~openviper.http.response.Response` (or a subclass).
Handlers are always ``async def`` coroutines.

Type Aliases & Protocols
-------------------------

``openviper.http.types``
~~~~~~~~~~~~~~~~~~~~~~~~

Shared type aliases and structural protocols used across the HTTP layer.

.. py:data:: JsonValue
   :no-index:

   Recursive type alias representing a valid JSON value:
   ``str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]``.

.. py:data:: JsonObject
   :no-index:

   Shorthand for ``dict[str, JsonValue]``.

.. py:data:: ASGIMessage

   Type alias for an ASGI message dict: ``dict[str, object]``.

.. py:data:: ASGIScope

   Type alias for an ASGI connection scope dict: ``dict[str, object]``.

.. py:data:: ASGIReceive

   Type alias for the ASGI receive callable.

.. py:data:: ASGISend

   Type alias for the ASGI send callable.

.. py:data:: TemplateContext

   Type alias for Jinja2 template context dicts: ``dict[str, object]``.

.. py:class:: AuthenticatorProtocol

   Structural type for authentication backends.  Defines
   ``async authenticate(request) -> tuple[object, object] | None``.

.. py:class:: PermissionProtocol

   Structural type for permission classes.  Defines
   ``async has_permission(request, view) -> bool`` and
   ``async has_object_permission(request, view, obj) -> bool``.

.. py:class:: ThrottleProtocol

   Structural type for throttle classes.  Defines
   ``async allow_request(request, view) -> bool`` and ``wait() -> float | None``.

.. py:class:: UserProtocol

   Structural type for user objects attached to requests.  Requires
   ``is_authenticated``, ``is_staff``, ``is_superuser`` attributes and
   ``async has_role(role_name) -> bool`` and ``async has_perm(codename) -> bool`` methods.

.. py:class:: SessionProtocol

   Structural type for session objects.  Requires a ``key: str`` attribute.

.. py:class:: MultipartField

   Structural type for python-multipart field callbacks.  Requires
   ``field_name: bytes`` and ``value: bytes`` attributes.

.. py:class:: MultipartFile

   Structural type for python-multipart file callbacks.  Requires
   ``field_name: bytes``, ``file_name: bytes | None``, ``content_type: bytes | str | None``,
   and ``file_object: object`` attributes.

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

   .. py:attribute:: path_params -> dict[str, str]

      Path parameters captured by the router (e.g. ``{"id": "42"}``).
      Values are strings; convert to int/float in your handler.

   .. py:attribute:: client -> tuple[str, int] | None

      ``(ip, port)`` of the connected client, or ``None`` for UNIX sockets.

   .. py:attribute:: state -> dict[str, object]

      Per-request mutable storage for middleware to attach data.

   .. py:attribute:: user -> UserProtocol | None

      The authenticated user attached by :class:`AuthenticationMiddleware`.
      ``None`` when unauthenticated.  Conforms to :class:`~openviper.http.types.UserProtocol`.

   .. py:attribute:: auth -> object | None

      Auth info attached by :class:`AuthenticationMiddleware`
      (e.g. a token payload or credentials object).

   .. py:attribute:: session -> Session

      Lazy access to the session object.  Requires ``SessionMiddleware``
      to be active.  If no session is found, returns an empty ``Session``
      with ``key=""``.

   **Raw header lookup:**

   .. py:method:: header(name: bytes) -> bytes | None

      O(1) raw header lookup.  *name* must be lower-cased bytes
      (e.g. ``b"content-type"``).

   **Body reading (all coroutines):**

   .. py:method:: body() -> Awaitable[bytes]

      Read and cache the full request body.  Limited to **10 MB** by
      default.  Raises ``ValueError`` when Content-Length is exceeded.

   .. py:method:: json() -> Awaitable[JsonValue]

      Parse the body as JSON.  Returns a :data:`~openviper.http.types.JsonValue`.

   .. py:method:: form() -> Awaitable[ImmutableMultiDict]

      Parse ``application/x-www-form-urlencoded`` or ``multipart/form-data``.
      Returns both regular fields and :class:`UploadFile` objects in the
      same dict-like structure.

.. py:class:: UploadFile(filename, content_type, file)

   Represents an uploaded file from a multipart form submission.

   **Security:** ``sanitize_filename`` strips path components, null bytes,
   control characters, and ``..`` sequences from the original filename.
   Filenames exceeding 255 characters are truncated.  Empty or hidden names
   (starting with ``.``) are replaced with ``"upload"``.

   .. py:attribute:: original_filename -> str

      The unsanitised filename as sent by the client.

   .. py:attribute:: filename -> str

      The sanitised filename safe for filesystem storage.

   .. py:attribute:: content_type -> str

      MIME type of the uploaded file.

   .. py:method:: read(size=-1) -> Awaitable[bytes]

      Read bytes from the underlying file object.

   .. py:method:: seek(offset) -> Awaitable[None]

      Seek within the file.

   .. py:method:: close() -> Awaitable[None]

      Close the file handle.

.. py:function:: sanitize_filename(filename: str) -> str

   Strip path components, null bytes, and traversal sequences from *filename*.
   Returns a safe basename suitable for storage on the filesystem.

``openviper.http.response``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

All response classes accept ``status_code`` and ``headers`` arguments.
The ``headers`` dict may include any additional response headers.

.. py:class:: Response(content: bytes | str | None = None, status_code: int = 200, headers: dict[str, str] | None = None, media_type: str | None = None)

   Base ASGI response.  ``content`` may be ``bytes``, ``str``, or ``None``.

   .. py:method:: set_cookie(key, value="", max_age=None, expires=None, path="/", domain=None, secure=False, httponly=False, samesite="lax")

      Append a ``Set-Cookie`` header.

      **Security:** Cookie names and values are validated to reject CR/LF
      characters.  Setting ``samesite="none"`` without ``secure=True``
      raises ``ValueError`` (violates RFC 6265bis).

   .. py:method:: delete_cookie(key, path="/", domain=None)

      Append a ``Set-Cookie`` header that expires the named cookie.

   .. py:attribute:: headers -> MutableHeaders

      Mutable response header map.  Use ``.set()`` or ``["name"] = value``
      to add/change headers before the response is sent.

.. py:class:: JSONResponse(content: JsonValue = None, status_code: int = 200, headers: dict[str, str] | None = None, indent: int | None = None)

   Serialize *content* to JSON using ``orjson`` (C extension).  Handles
   ``datetime``, ``date``, ``UUID``, and FK proxy objects automatically.
   Pass ``indent=2`` for pretty-printed output.  The *content* parameter
   accepts :data:`~openviper.http.types.JsonValue`.

.. py:class:: HTMLResponse(content: str | None = None, status_code: int = 200, headers: dict[str, str] | None = None, template: str | None = None, context: TemplateContext | None = None, template_dir: str | Path = "templates")

   Return HTML.  Either pass *content* as a string, or provide *template*
   (a Jinja2 template name) and *context* for template rendering.

   **Security:** Template names are validated against path traversal
   (``..``, ``/``, ``\``, Windows absolute paths).  The current request
   is auto-injected into the context when available.

.. py:class:: PlainTextResponse(content: str | None = None, status_code: int = 200, headers: dict[str, str] | None = None)

   Return a plain-text string with ``Content-Type: text/plain``.

.. py:class:: RedirectResponse(url: str, status_code: int = 307, headers: dict[str, str] | None = None, **path_params: str)

   HTTP redirect to *url*.  Default status is 307 (Temporary Redirect).
   Use ``status_code=301`` for permanent redirects.

   **Security:** Redirect URLs are validated against:

   - CR/LF injection (``\r`` / ``\n``)
   - Protocol-relative URLs (``//``)
   - Path traversal sequences (``..``)
   - Disallowed URL schemes (only ``http`` and ``https`` allowed)

   Namespaced routes (``"namespace:route_name"``) are resolved via the
   active router.

.. py:class:: StreamingResponse(content: AsyncIterator[bytes] | Iterator[bytes] | Callable[[], AsyncIterator[bytes]], status_code: int = 200, headers: dict[str, str] | None = None, media_type: str | None = None)

   Stream an async generator (or sync iterator) of bytes chunks to the
   client.  *content* may also be a zero-argument callable that returns an
   async generator.

.. py:class:: FileResponse(path: str, status_code: int = 200, headers: dict[str, str] | None = None, *, media_type: str | None = None, filename: str | None = None, allowed_dir: str | None = None)

   Stream a file from the filesystem.  Automatically sets
   ``Content-Type``, ``ETag``, ``Last-Modified``, and
   ``Content-Disposition`` (when *filename* is given).  Supports
   ``If-None-Match`` and ``If-Modified-Since`` conditional requests
   (returns 304 when appropriate) and range requests (RFC 7233).

   **Security:** Pass *allowed_dir* to restrict *path* to a safe directory,
   preventing path-traversal attacks.  The resolved path is validated
   with ``Path.is_relative_to()``.  Filenames in Content-Disposition
   headers are sanitised against CR/LF injection.

.. py:class:: GZipResponse(content: Response, minimum_size: int = 500, compresslevel: int = 6)

   Wrap another :class:`Response` and gzip-compress its body when its size
   exceeds *minimum_size* bytes.  Content types already known to be
   compressed (images, video, audio, PDF, archives) are skipped automatically.

.. note::

   For template rendering use
   ``HTMLResponse(template="…", context={…})`` - see :ref:`template`.

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

   Handlers can return a :class:`Response` object, or a ``dict``/``list`` which
   is automatically wrapped in a :class:`JSONResponse`.

   **Class attributes:**

   .. py:attribute:: http_method_names
      :type: list[str]

      Lowercase method names this view handles.  Defaults to all standard
      HTTP verbs.

   .. py:attribute:: serializer_class

      Optional Pydantic serializer attached for OpenAPI ``requestBody``
      schema generation.

   .. py:attribute:: authentication_classes
      :type: list[AuthenticatorProtocol | str] | None

      List of authentication backends.  ``None`` inherits
      ``settings.DEFAULT_AUTHENTICATION_CLASSES``.  Set to ``[]`` to
      explicitly disable per-view authentication.

   .. py:attribute:: permission_classes
      :type: list[PermissionProtocol | str] | None

      List of permission classes.  ``None`` inherits
      ``settings.DEFAULT_PERMISSION_CLASSES``.  Set to ``[]`` to
      explicitly disable per-view permission checks.

   .. py:attribute:: throttle_classes
      :type: list[ThrottleProtocol | str] | None

      List of throttle classes.  ``None`` inherits
      ``settings.DEFAULT_THROTTLE_CLASSES``.  Set to ``[]`` to
      explicitly disable throttling.

   **Security:** ``View.__init__`` validates all keyword arguments against
   ``_ALLOWED_KWARGS`` (default: empty).  Unknown kwargs raise ``TypeError``
   to prevent mass-assignment attacks.

   **Methods:**

   .. py:method:: dispatch(request, **kwargs) -> Awaitable[Response]

      Route *request* to the appropriate handler method.

   .. py:classmethod:: as_view(_action_name=None, **initkwargs) -> Callable[..., Response]

      Return an async callable suitable for use as a route handler.
      *initkwargs* are validated against ``_ALLOWED_KWARGS`` and forwarded
      to ``__init__`` for each request.

   .. py:classmethod:: register(router, path, *, name=None, **initkwargs)

      Shorthand to register the view on *router* at *path*.  Automatically
      determines which HTTP methods are implemented.  For standard HTTP
      handlers, parameters declared after ``request`` are appended to the
      registered path automatically.

.. py:decorator:: action(methods=None, detail=False, url_path=None, name=None)

   Mark a :class:`View` method as a custom action for automatic routing.

   :param list[str] methods: List of HTTP methods (e.g. ``["GET", "POST"]``).
      Defaults to ``["GET"]``.
   :param bool detail:
      - If ``False`` (default), the action is for the collection (e.g. ``/users/search``).
      - If ``True``, the action is for a single instance (e.g. ``/users/{id}/deactivate``).
   :param str url_path: Optional override for the URL segment. Defaults to
      the method name.
   :param str name: Optional name for the reverse URL lookup. Defaults to
      the method name.

``openviper.http.permissions``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Permission classes control access to views.  Set them on a
:class:`View` via the ``permission_classes`` attribute, or globally via
``settings.DEFAULT_PERMISSION_CLASSES``.

.. py:class:: BasePermission

   Abstract base class for all permission classes.  Subclass and
   implement :meth:`has_permission` (and optionally
   :meth:`has_object_permission`).

   .. py:method:: has_permission(request, view) -> Awaitable[bool]

      Return ``True`` to allow the request, ``False`` to deny.

   .. py:method:: has_object_permission(request, view, obj) -> Awaitable[bool]

      Return ``True`` to allow access to a specific object.  Default
      implementation returns ``True``.

   Permission classes support composition using Python operators:

   - ``IsAuthenticated & IsAdmin`` - both must pass (AND).
   - ``IsAuthenticated | AllowAny`` - either may pass (OR).
   - ``~IsAdmin`` - negation (NOT).

.. py:class:: AllowAny

   Always allow access.  Equivalent to setting ``permission_classes = []``.

.. py:class:: IsAuthenticated

   Allow only authenticated users.  Returns ``False`` for anonymous
   requests.

.. py:class:: IsAdmin

   Allow only staff users or superusers.  Checks both
   ``request.user.is_staff`` and ``request.user.is_superuser``.

.. py:class:: IsAuthenticatedOrReadOnly

   Allow authenticated users for write methods; permit read-only access
   (``GET``, ``HEAD``, ``OPTIONS``) to anyone.

.. py:class:: HasRole(role_name)

   Allow only users with a specific role.  *role_name* is matched against
   ``request.user.has_role(role_name)``.

.. py:class:: HasPermission(codename)

   Allow only users with a specific permission codename.  *codename* is
   matched against ``request.user.has_perm(codename)``.

Usage example:

.. code-block:: python

    from openviper.http.views import View
    from openviper.http.permissions import IsAuthenticated, IsAdmin

    class SecretView(View):
        permission_classes = [IsAuthenticated & IsAdmin]

        async def get(self, request):
            return {"secret": "data"}

Example Usage
-------------

.. seealso::

   Working projects that demonstrate HTTP views:

   - `examples/flexible/ <https://github.com/mymi14s/openviper/tree/master/examples/flexible>`_ - function-based views with ``JSONResponse``
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - class-based ``View`` with REST methods

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

For standard HTTP handlers (``get``, ``post``, ``put``, ``patch``,
``delete``), parameters declared after ``request`` are inferred as URL
segments.  A handler with no extra parameters stays on the base path; a
handler such as ``get(self, request, post_id: int)`` is mounted at
``/{post_id:int}`` beneath that base path.

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

    # Registering at "/posts" creates:
    # GET    /posts/{post_id:int}
    # PUT    /posts/{post_id:int}
    # DELETE /posts/{post_id:int}
    PostDetailView.register(router, "/posts")

You may also mix collection and detail handlers in one class:

.. code-block:: python

    class PostView(View):
        async def post(self, request: Request) -> JSONResponse:
            data = await request.json()
            return JSONResponse({"created": data}, status_code=201)

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

    # POST /posts
    # GET  /posts/{post_id:int}
    # PUT  /posts/{post_id:int}
    PostView.register(router, "/posts")

``router.add("/posts", PostView.as_view())`` performs the same class-view
method discovery as ``PostView.register(router, "/posts")`` when
``methods=`` is omitted.

Extra View Actions
~~~~~~~~~~~~~~~~~~

You can add custom endpoints to a :class:`View` using the ``@action`` decorator.
These are automatically registered when the view is mounted.

.. code-block:: python

    from openviper.http.views import View, action

    class UserView(View):
        async def get(self, request):
            """List users."""
            return {"users": []}

        @action(detail=False, methods=["GET"])
        async def search(self, request):
            """Search users: GET /users/search?q=..."""
            q = request.query_params.get("q")
            return {"query": q, "results": []}

        @action(detail=True, methods=["POST"])
        async def deactivate(self, request, id):
            """Deactivate a user: POST /users/{id}/deactivate"""
            return {"id": id, "active": False}

    # Registering UserView at "/users" will create:
    # GET  /users                  -> UserView.get
    # GET  /users/search           -> UserView.search
    # POST /users/{id}/deactivate  -> UserView.deactivate
    UserView.register(router, "/users")

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
