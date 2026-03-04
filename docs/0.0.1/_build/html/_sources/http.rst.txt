.. _http:

============================
HTTP — Requests & Responses
============================

The ``openviper.http`` package provides the :class:`~openviper.http.request.Request`
object available inside every handler, and a family of response classes for
returning different content types to clients.

.. contents:: On this page
   :local:
   :depth: 2

----

Request Object
---------------

Every handler receives a :class:`~openviper.http.request.Request` as its
first argument.

.. code-block:: python

   async def my_view(request):
       # Core metadata
       method  = request.method          # "GET", "POST", …
       path    = request.path            # "/posts/42"
       headers = request.headers         # Headers dict-like
       cookies = request.cookies         # dict[str, str]

       # Query string  →  /search?q=async&page=2
       q    = request.query_params.get("q")
       page = request.query_params.get("page", "1")

       # Path parameters (set by the router)
       post_id = request.path_params.get("post_id")

       # Full URL components
       url  = request.url            # URL object: scheme, hostname, path, query

       # Per-request mutable store (populated by middleware / other handlers)
       request.state["correlation_id"] = "abc"

Reading the body:

.. code-block:: python

   # JSON body
   data = await request.json()

   # Raw bytes
   raw = await request.body()

   # Form fields (application/x-www-form-urlencoded)
   form = await request.form()
   name = form.get("name")

----

File Uploads
~~~~~~~~~~~~~

Multipart file uploads are handled via ``request.form()``.  Uploaded files
are returned as :class:`~openviper.http.request.UploadFile` instances.

.. code-block:: python

   from openviper.http.request import Request

   @router.post("/upload")
   async def upload_file(request: Request):
       form = await request.form()
       upload: UploadFile = form["file"]

       # Metadata
       print(upload.filename)       # "photo.jpg"
       print(upload.content_type)   # "image/jpeg"

       # Read all bytes
       content = await upload.read()

       # Or read in chunks
       await upload.seek(0)
       chunk = await upload.read(4096)

       # Always close when done
       await upload.close()

       return {"filename": upload.filename, "size": len(content)}

``UploadFile`` API:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Attribute / Method
     - Description
   * - ``.filename``
     - Original filename from the browser
   * - ``.content_type``
     - MIME type declared by the browser (e.g. ``"image/png"``)
   * - ``await .read(size=-1)``
     - Read up to *size* bytes; ``-1`` reads the whole file
   * - ``await .seek(offset)``
     - Seek to *offset* (so you can re-read)
   * - ``await .close()``
     - Close the underlying temporary file

Saving an upload with the storage API:

.. code-block:: python

   from openviper.storage import default_storage

   @router.post("/avatar")
   async def upload_avatar(request: Request):
       form  = await request.form()
       photo = form["photo"]
       data  = await photo.read()

       path = await default_storage.save(f"avatars/{photo.filename}", data)
       url  = default_storage.url(path)
       return {"url": url}

.. seealso::

   :ref:`storage` — ``default_storage``, media root and URL configuration.

----

Response Types
---------------

View handlers can return a plain ``dict`` (automatically wrapped as
``JSONResponse``) or an explicit response object for full control.

.. code-block:: python

   # Implicit JSON (shorthand)
   async def ping(request):
       return {"status": "ok"}

   # Equivalent explicit form
   from openviper import JSONResponse
   async def ping(request):
       return JSONResponse({"status": "ok"})

   # With a custom status code
   async def create_item(request):
       ...
       return JSONResponse(item_data, status_code=201)

JSONResponse
~~~~~~~~~~~~~

Serialises the body using ``orjson``.  Dates and UUIDs are converted to ISO
strings automatically.

.. code-block:: python

   from openviper import JSONResponse
   import datetime

   return JSONResponse(
       {"created_at": datetime.datetime.now(), "id": "abc"},
       status_code=201,
       headers={"X-Custom": "header"},
   )

PlainTextResponse
~~~~~~~~~~~~~~~~~~

Returns a ``text/plain`` body.

.. code-block:: python

   from openviper.http.response import PlainTextResponse

   return PlainTextResponse("Hello, World!")

HTMLResponse
~~~~~~~~~~~~~

Returns ``text/html``.  Optionally renders a **Jinja2** template:

.. code-block:: python

   from openviper.http.response import HTMLResponse

   # Inline HTML
   return HTMLResponse("<h1>Welcome</h1>")

   # From a template (resolves from TEMPLATES_DIR and app template folders)
   return HTMLResponse(
       template="blog/post.html",
       context={"post": post, "user": request.user},
   )

RedirectResponse
~~~~~~~~~~~~~~~~~

Issues an HTTP redirect.  Default status code is ``307 Temporary Redirect``.

.. code-block:: python

   from openviper.http.response import RedirectResponse

   # Temporary redirect (default)
   return RedirectResponse("/login")

   # Permanent redirect
   return RedirectResponse("/new-url", status_code=301)

   # Post-login redirect preserving method
   return RedirectResponse(request.query_params.get("next", "/dashboard"))

FileResponse
~~~~~~~~~~~~~

Serves a file from disk with chunked streaming.  The ``Content-Type`` and
``Content-Length`` headers are set automatically.

.. code-block:: python

   from openviper.http.response import FileResponse

   @router.get("/downloads/{filename}")
   async def download(request, filename: str):
       path = f"/var/app/exports/{filename}"
       return FileResponse(path)

   # Force browser to download (attachment)
   return FileResponse(
       "/var/app/exports/report.pdf",
       media_type="application/pdf",
       filename="monthly_report.pdf",   # sets Content-Disposition: attachment
   )

``FileResponse`` parameters:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Parameter
     - Description
   * - ``path``
     - Absolute path to the file on disk
   * - ``status_code``
     - HTTP status (default ``200``)
   * - ``headers``
     - Extra response headers
   * - ``media_type``
     - Override MIME type (auto-detected from file extension otherwise)
   * - ``filename``
     - If set, adds ``Content-Disposition: attachment; filename="..."``

StreamingResponse
~~~~~~~~~~~~~~~~~~

Sends a body piece-by-piece from an async (or sync) generator.  Perfect for
large payloads, server-sent events, and live AI token streams.

.. code-block:: python

   from openviper.http.response import StreamingResponse

   @router.get("/events")
   async def stream_events(request):
       async def generate():
           for i in range(10):
               yield f"data: event {i}\n\n".encode()
               await asyncio.sleep(0.5)

       return StreamingResponse(generate(), media_type="text/event-stream")

GZipResponse
~~~~~~~~~~~~~

Wraps any other response and compresses the body with gzip when it exceeds
the minimum size threshold.

.. code-block:: python

   from openviper.http.response import GZipResponse, JSONResponse

   return GZipResponse(
       JSONResponse(large_payload),
       minimum_size=500,      # bytes; bodies smaller than this are not compressed
       compresslevel=9,       # 1 (fastest) – 9 (best compression)
   )

----

Setting Cookies
----------------

.. code-block:: python

   from openviper import JSONResponse

   response = JSONResponse({"ok": True})
   response.set_cookie(
       "session",
       value    = "abc123",
       max_age  = 3600,     # seconds
       httponly = True,
       secure   = True,
       samesite = "lax",
   )
   return response

   # Delete a cookie
   response.delete_cookie("session")

----

Custom Headers
---------------

.. code-block:: python

   response = JSONResponse({"ok": True}, headers={"X-Request-Id": "123"})
   response.headers["X-Rate-Limit"] = "100"
   return response

.. seealso::

   :ref:`architecture` — middleware system, routing, request pipeline.
