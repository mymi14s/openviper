.. _staticfiles:

Static Files
============

The ``openviper.staticfiles`` package provides development-time static file
serving and a ``collectstatic`` utility for production builds.

Overview
--------

In development (``DEBUG=True``), static files are served directly by the
framework via :class:`~openviper.staticfiles.StaticFilesMiddleware`.  In
production (``DEBUG=False``), static files should be served by a reverse
proxy such as nginx; the middleware is not mounted.

Call :func:`static` and/or :func:`media` in ``routes.py`` to opt in to
framework-managed serving:

.. code-block:: python

    # routes.py
    from openviper.staticfiles import static, media

    route_paths = [
        ("/", main_router),
        ("/admin", get_admin_site()),
    ] + static() + media()

Key Classes & Functions
-----------------------

.. py:class:: openviper.staticfiles.StaticFilesMiddleware(app, url_path="/static", directories=None, cache_max_age=3600, max_file_size=52428800)

   ASGI middleware that intercepts requests whose path starts with *url_path*
   and serves the matching file from one of the *directories*.

   - ``app`` - the next ASGI application in the chain.
   - ``url_path`` - URL prefix to intercept (default: ``"/static"``).
   - ``directories`` - list of filesystem directories to search.
     Defaults to ``["static"]``.
   - ``cache_max_age`` - ``Cache-Control: max-age`` value in seconds
     (default: ``3600``).
   - ``max_file_size`` - maximum file size in bytes; larger files receive
     a 413 response (default: 50 MiB).

   Supports conditional requests (``If-None-Match``, ``If-Modified-Since``),
   byte-range requests (``Range`` / ``If-Range``), correct MIME type
   detection with ``X-Content-Type-Options: nosniff``, ``Content-Length``,
   ``ETag``, and ``Last-Modified`` headers.

   Security features include path traversal sanitisation, symlink rejection,
   and directory confinement checks.

.. py:function:: openviper.staticfiles.static() -> list[str]

   Signal the framework to enable static file serving at ``STATIC_URL``.
   Returns an empty list so it can be appended safely to ``route_paths``.

.. py:function:: openviper.staticfiles.media() -> list[str]

   Signal the framework to enable media file serving at ``MEDIA_URL``.
   Returns an empty list so it can be appended safely to ``route_paths``.

.. py:function:: openviper.staticfiles.is_static_enabled() -> bool

   Return ``True`` if :func:`static` has been called (i.e. the user opted in).

.. py:function:: openviper.staticfiles.is_media_enabled() -> bool

   Return ``True`` if :func:`media` has been called.

.. py:function:: openviper.staticfiles.collect_static(source_dirs, dest_dir, *, clear=False) -> int

   Copy all static files from *source_dirs* (including per-app ``static/``
   directories discovered via :func:`discover_app_static_dirs`) into
   *dest_dir*.  Returns the number of files collected.

   When *clear* is ``True`` and the destination is not a symlink and does not
   overlap a source directory, the destination is deleted before collection
   begins.  Raises ``ValueError`` if *clear* is ``True`` and the destination
   is a symlink.

.. py:function:: openviper.staticfiles.handlers.discover_app_static_dirs() -> tuple[Path, ...]

   Discover ``static/`` directories inside every installed app (including
   ``openviper.admin``).  Results are cached via ``functools.lru_cache``.

.. py:function:: openviper.staticfiles.handlers.sanitize_relative_path(relative) -> str | None

   Neutralise path traversal, encoded slashes, and null bytes in a relative
   path.  Returns the cleaned path or ``None`` if the path is unsafe.

.. py:function:: openviper.staticfiles.handlers.parse_range(range_header, file_size) -> tuple[int, int] | Literal["ignore", "unsatisfiable"]

   Parse a ``bytes`` Range header.  Returns ``(start, end)`` for a
   satisfiable single range, ``"ignore"`` for multi-range or malformed
   input (serve 200), or ``"unsatisfiable"`` when the range is beyond EOF
   (respond 416).

.. py:class:: openviper.staticfiles.handlers.NotModifiedResponse

   A 304 Not Modified ASGI response carrying ``ETag`` and ``Last-Modified``
   headers.

.. py:class:: openviper.staticfiles.handlers.FileEntry

   Bundles a resolved :class:`~pathlib.Path` with its pre-fetched
   :class:`os.stat_result`.  Used internally by
   :class:`StaticFilesMiddleware` to avoid redundant stat calls.

.. py:function:: openviper.staticfiles.handlers.copy_tree(src_root, dest) -> int

   Copy every file under *src_root* into *dest*, preserving directory
   structure.  Skips symlinks that resolve outside *src_root* and files
   whose resolved target escapes *dest* (Zip-Slip protection).  Returns the
   number of files copied.

Security
--------

The static file serving pipeline enforces several security measures:

- **Path traversal sanitisation** - :func:`sanitize_relative_path` decodes
  percent-encoded sequences, rejects null bytes, encoded slashes (``%2f``,
  ``%5c``), and any path component equal to ``..``.
- **Symlink rejection** - :class:`StaticFilesMiddleware` skips files that
  are symlinks or have symlinked parent directories within the serving root.
- **Directory confinement** - resolved file paths are verified to remain
  inside the configured serving directory via ``Path.relative_to()``.
- **Zip-Slip protection** - :func:`copy_tree` rejects symlinks that resolve
  outside the source root and files whose resolved destination escapes the
  target directory.
- **Symlink-destination guard** - :func:`collect_static` with ``clear=True``
  refuses to delete a destination that is a symlink.
- **X-Content-Type-Options** - all responses include the ``nosniff`` header
  to prevent MIME-type sniffing.
- **Method restriction** - only ``GET`` and ``HEAD`` are served; other
  methods receive a 405 response.
- **File size limit** - files exceeding ``max_file_size`` receive a 413
  response.

Example Usage
-------------

.. seealso::

   Working projects that serve static and media files:

   - `examples/ai_smart_recipe_generator/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator>`_ - ``static()`` + ``media()`` route helpers
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - static assets and user-uploaded media

Development Static Serving
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # routes.py
    from openviper.routing.router import Router
    from openviper.staticfiles import static, media

    router = Router()

    @router.get("/")
    async def home(request): ...

    route_paths = [
        ("/", router),
    ] + static() + media()

Now ``/static/app.js`` resolves to ``<project_root>/static/app.js`` and
``/media/uploads/photo.jpg`` resolves to ``<MEDIA_ROOT>/uploads/photo.jpg``
when ``DEBUG=True``.

Direct Middleware Usage
~~~~~~~~~~~~~~~~~~~~~~~

Attach the middleware manually when you need custom URL paths or multiple
static directories:

.. code-block:: python

    from openviper import OpenViper
    from openviper.staticfiles import StaticFilesMiddleware

    app = OpenViper()
    app = StaticFilesMiddleware(
        app,
        url_path="/assets",
        directories=["static", "frontend/dist"],
    )

Collecting Static Files for Production
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    openviper viperctl collectstatic .

Or call it programmatically:

.. code-block:: python

    from openviper.staticfiles.handlers import collect_static

    count = collect_static(
        source_dirs=["static", "myapp/static"],
        dest_dir="public/static",
    )
    print(f"Collected {count} files")

To clear the destination before collecting:

.. code-block:: python

    collect_static(
        source_dirs=["static"],
        dest_dir="public/static",
        clear=True,
    )

Configuration
-------------

.. code-block:: python

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        STATIC_URL: str = "/static/"
        STATIC_ROOT: str = "staticfiles"
        MEDIA_URL: str = "/media/"
        MEDIA_ROOT: str = "media"
