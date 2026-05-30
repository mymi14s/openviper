.. _middleware:

Middleware
==========

The ``openviper.middleware`` package provides built-in ASGI middlewares for
cross-cutting concerns: CORS, CSRF protection, rate limiting, security
headers, database connection pinning, error handling, and authentication.
All middlewares follow the standard ASGI callable protocol and can be
composed freely.

Overview
--------

Middlewares are registered in ``settings.MIDDLEWARE`` (a tuple of dotted
import paths) or attached programmatically by wrapping the ASGI app.  Each
middleware accepts the next ``app`` as its first constructor argument.

The stack is applied **inner-first**: the first entry in the list wraps the
outermost layer (first to receive the request, last to process the response).

Key Classes
-----------

``openviper.middleware.cors``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: CORSMiddleware(app, allowed_origins=None, allow_credentials=None, allowed_methods=None, allowed_headers=None, expose_headers=None, max_age=None)

   Adds ``Access-Control-*`` headers and handles preflight ``OPTIONS``
   requests.

   - ``allowed_origins`` - list of allowed origin strings.  Supports
     ``"*"`` (all) and wildcard patterns such as
     ``"https://*.example.com"``.  Defaults to ``["*"]``.
     When ``None``, reads ``CORS_ALLOWED_ORIGINS`` from project settings.
   - ``allow_credentials`` - set ``Access-Control-Allow-Credentials: true``
     and allow ``Authorization`` headers / cookies cross-origin.
     Defaults to ``False`` (``CORS_ALLOW_CREDENTIALS`` setting).
     **Cannot** be combined with wildcard origins - a
     ``ValueError`` is raised to prevent credential leakage.
   - ``allowed_methods`` - permitted request methods.  Defaults to ``["*"]``
     (all methods).  Reads ``CORS_ALLOWED_METHODS`` setting when ``None``.
   - ``allowed_headers`` - permitted request headers.  Defaults to ``["*"]``
     (all headers).  Reads ``CORS_ALLOWED_HEADERS`` setting when ``None``.
   - ``expose_headers`` - list of headers to expose to the browser via
     ``Access-Control-Expose-Headers``.  Defaults to ``[]``.
   - ``max_age`` - preflight response cache TTL in seconds.
     Defaults to ``600`` (``CORS_MAX_AGE`` setting).

   Origin patterns are compiled to ``re.Pattern`` objects at ``__init__``
   time so no per-request regex compilation occurs.  Exact-match origins
   are stored in a ``frozenset`` for O(1) lookup.

   When the response depends on the request origin (i.e. not wildcard),
   a ``Vary: Origin`` header is appended to prevent cache poisoning by
   shared caches (CDNs).

``openviper.middleware.csrf``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: CSRFMiddleware(app, secret="", cookie_name="csrftoken", header_name="x-csrftoken", exempt_paths=None)

   Double-submit cookie CSRF protection for unsafe methods (``POST``, ``PUT``,
   ``PATCH``, ``DELETE``).

   The CSRF token is stored in a cookie (``csrftoken``) and must be
   re-submitted in either:

   - The ``X-CSRFToken`` request header, **or**
   - The ``csrfmiddlewaretoken`` form field (``application/x-www-form-urlencoded``
     bodies only; body reads are capped at 2 MB to prevent DoS).

   ``GET``, ``HEAD``, and ``OPTIONS`` requests pass through without validation.

   - ``secret`` - signing secret.  Defaults to ``settings.SECRET_KEY``.
   - ``cookie_name`` - name of the CSRF cookie.
   - ``header_name`` - name of the HTTP header to check.
   - ``exempt_paths`` - list of path strings that skip CSRF validation
     (e.g. ``["/api/webhooks"]``).

   Token verification uses HMAC-SHA256 with a per-request salt (128-bit)
   and ``hmac.compare_digest`` for constant-time comparison.

   **Origin verification:** When the request carries an ``Origin`` header,
   it is checked against ``settings.CSRF_TRUSTED_ORIGINS``.  Trusted
   origins bypass the double-submit check, allowing cross-origin POST
   requests from known frontends.

   **Cookie security settings:**

   .. list-table::
      :widths: 35 15 50
      :header-rows: 1

      * - Setting
        - Default
        - Description
      * - ``CSRF_COOKIE_SECURE``
        - ``False``
        - Append ``Secure`` flag (HTTPS only).
      * - ``CSRF_COOKIE_HTTPONLY``
        - ``False``
        - Append ``HttpOnly`` flag (no JS access).
      * - ``CSRF_COOKIE_SAMESITE``
        - ``Lax``
        - ``SameSite`` attribute (``Lax``, ``Strict``, ``None``).
      * - ``CSRF_COOKIE_AGE``
        - ``None``
        - ``Max-Age`` in seconds.  ``None`` = session cookie.

``openviper.middleware.ratelimit``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: RateLimitMiddleware(app, max_requests=None, window_seconds=None, key_func=None)

   Sliding-window rate limiter using 256 independent lock stripes for high
   concurrency.

   - ``max_requests`` - requests allowed per *window* (default:
     ``RATE_LIMIT_REQUESTS`` setting, or 2000).
   - ``window_seconds`` - time window in seconds (default:
     ``RATE_LIMIT_WINDOW`` setting, or 60).
   - ``key_func`` - callable ``(scope) -> str`` that returns the bucket key.
     Defaults based on ``RATE_LIMIT_BY`` setting (see below).

   Responds with **429 Too Many Requests** when the limit is exceeded and
   sets ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``,
   ``X-RateLimit-Reset``, and ``Retry-After`` headers on every response.

   **Key strategies** (``RATE_LIMIT_BY`` setting):

   - ``"ip"`` (default) - client IP from the ASGI ``client`` tuple.
     ``X-Forwarded-For`` is intentionally not used to prevent spoofing.
   - ``"user"`` - authenticated user primary key; falls back to IP for
     anonymous requests.
   - ``"path"`` - ``(client IP, request path)`` tuple; rate-limits each
     endpoint independently.

   **Backend** (``RATE_LIMIT_BACKEND`` setting):

   - ``"memory"`` (default) - in-process ``SlidingWindowCounter`` with
     per-stripe locking and lazy bucket eviction.
   - ``"redis"`` - ``RedisWindowCounter`` backed by a Redis sorted set.
     Requires ``redis>=7.4.0`` (install with ``pip install 'openviper[redis]'``).
     Uses ``settings.CACHE_URL`` as the Redis connection URL.

.. py:function:: openviper.middleware.ratelimit.rate_limit(max_requests=60, window_seconds=60.0)

   Per-view rate limit **decorator** (alternative to the middleware).
   Limits by client IP.  Raises
   :class:`~openviper.exceptions.TooManyRequests` (429) when exceeded.

``openviper.middleware.security``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: SecurityMiddleware(app, ssl_redirect=None, hsts_seconds=None, hsts_include_subdomains=None, hsts_preload=None, x_frame_options=None, content_type_nosniff=True, xss_filter=None, csp=None, permissions_policy=None, cross_origin_opener_policy=None, cross_origin_embedder_policy=None, cross_origin_resource_policy=None)

   Adds HTTP security headers to every response and validates the
   ``Host`` header against ``settings.ALLOWED_HOSTS``.

   **Host header validation:** Requests with a disallowed host or
   header-control bytes (``\\r``, ``\\n``, ``\\0``) in the host receive
   a **400 Bad Request** response.  This prevents host-header injection,
   CRLF response splitting, and cache poisoning.

   Headers added unconditionally (when the corresponding option is enabled):

   - ``X-Content-Type-Options: nosniff`` (``content_type_nosniff=True``)
   - ``X-Frame-Options: DENY`` (configurable; set to ``""`` to disable)
   - ``Referrer-Policy: strict-origin-when-cross-origin``

   Conditional headers:

   - ``Strict-Transport-Security: max-age=N[; includeSubDomains][; preload]``
     - when ``hsts_seconds > 0``.
   - HTTP to HTTPS redirect - when ``ssl_redirect=True``.  Redirect
     targets are validated for CRLF bytes to prevent response splitting.
   - ``Content-Security-Policy`` - when *csp* is provided as a dict or
     string.  Semicolons in CSP dict keys/values are stripped as a
     defense against header injection.
   - ``Permissions-Policy`` - when *permissions_policy* is provided.
   - ``Cross-Origin-Opener-Policy`` - when *cross_origin_opener_policy*
     is provided.
   - ``Cross-Origin-Embedder-Policy`` - when *cross_origin_embedder_policy*
     is provided.
   - ``Cross-Origin-Resource-Policy`` - when *cross_origin_resource_policy*
     is provided.

   All parameters default to ``None`` and fall back to their
   ``SECURE_*`` / ``X_FRAME_OPTIONS`` settings counterparts.

   **Deprecated:** ``xss_filter`` defaults to ``None`` (disabled).  The
   ``X-XSS-Protection`` header is removed from modern browsers and its
   legacy IE implementation introduced XSS vectors.  Use
   ``Content-Security-Policy`` instead.  When explicitly enabled, a
   deprecation warning is logged.

   **CSP dict example:**

   .. code-block:: python

      SecurityMiddleware(
          app,
          csp={
              "default-src": "'self'",
              "script-src": "'self' https://cdn.example.com",
              "style-src": "'self' 'unsafe-inline'",
          },
      )

``openviper.middleware.db``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: DatabaseMiddleware(app)

   Pins a single pooled database connection for the lifetime of each
   HTTP/WebSocket request via ``ContextVar``.  All ORM calls within the
   request reuse the same connection, reducing pool checkout overhead
   and ensuring consistent reads under ``READ COMMITTED`` or stricter
   isolation.

   Non-HTTP scopes (lifespan, etc.) pass through without connection
   pinning.

   No constructor arguments beyond ``app``.  Connection management is
   handled by :func:`openviper.db.connection.request_connection`.

``openviper.middleware.error``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ServerErrorMiddleware(app, *, debug=False)

   Outermost ASGI middleware that catches all unhandled exceptions and
   converts them into HTTP 500 responses.

   - ``debug=True`` - returns a rich HTML traceback page with CSP and
     ``X-Content-Type-Options: nosniff`` headers for developer
     diagnostics.
   - ``debug=False`` - logs the exception at ``ERROR`` level and
     returns a plain ``500 Internal Server Error`` text body that
     exposes no internals.

   If ``http.response.start`` was already sent downstream when the
   exception occurs, the error can only be logged (no replacement
   response can be sent) and the exception is re-raised.

   This middleware does **not** extend ``BaseMiddleware``; it manages
   its own ``__call__`` and ``__slots__`` directly.

``openviper.middleware.auth``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AuthenticationMiddleware(app)
   :no-index:

   See :ref:`auth` for full documentation.  Populates ``request.user`` and
   ``request.auth`` from the configured auth backends.

``openviper.middleware.base``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: BaseMiddleware(app)

   Convenience base class for custom middlewares.  Subclass and override
   ``__call__``.

.. py:function:: openviper.middleware.base.build_middleware_stack(app, middleware_classes) -> ASGIApp

   Wrap *app* with a stack of ASGI middleware classes.  *middleware_classes*
   is a list of either class objects (``CORSMiddleware``) or
   ``(cls, kwargs_dict)`` tuples for classes that need arguments.
   Middlewares are applied inner-first (first item = outermost layer).

Example Usage
-------------

.. seealso::

   Working projects that configure middleware:

   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - CORS, Security, and Auth middleware
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - Security, CORS, and Auth middleware stack

Registering via Settings
~~~~~~~~~~~~~~~~~~~~~~~~~

When middleware classes are listed in ``MIDDLEWARE``, OpenViper automatically
reads the corresponding settings and passes them as constructor arguments -
no manual wiring required.

**CORS settings** (``CORSMiddleware``):

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Setting
     - Default
     - Description
   * - ``CORS_ALLOWED_ORIGINS``
     - ``()`` → ``["*"]``
     - Allowed origin strings or wildcard patterns (``"https://*.example.com"``).
   * - ``CORS_ALLOW_CREDENTIALS``
     - ``False``
     - Set ``Access-Control-Allow-Credentials: true`` to allow cookies / auth
       headers cross-origin.  Keep ``False`` unless you need credentialed requests.
   * - ``CORS_ALLOWED_METHODS``
     - all methods
     - Permitted HTTP methods.
   * - ``CORS_ALLOWED_HEADERS``
     - ``("*",)``
     - Permitted request headers.
   * - ``CORS_EXPOSE_HEADERS``
     - ``()``
     - Headers exposed to the browser via ``Access-Control-Expose-Headers``.
   * - ``CORS_MAX_AGE``
     - ``600``
     - Preflight cache TTL in seconds.

**CSRF settings** (``CSRFMiddleware``):

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Setting
     - Default
     - Description
   * - ``CSRF_TRUSTED_ORIGINS``
     - ``()``
     - Origins allowed to bypass the double-submit check (e.g.
     ``("https://frontend.example.com",)``).
   * - ``CSRF_COOKIE_SECURE``
     - ``False``
     - Append ``Secure`` flag to the CSRF cookie (HTTPS only).
   * - ``CSRF_COOKIE_HTTPONLY``
     - ``False``
     - Append ``HttpOnly`` flag (no JavaScript access).
   * - ``CSRF_COOKIE_SAMESITE``
     - ``Lax``
     - ``SameSite`` attribute: ``Lax``, ``Strict``, or ``None``.
   * - ``CSRF_COOKIE_AGE``
     - ``None``
     - ``Max-Age`` in seconds.  ``None`` = session-scoped cookie.

**Rate-limit settings** (``RateLimitMiddleware``):

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Setting
     - Default
     - Description
   * - ``RATE_LIMIT_REQUESTS``
     - ``100``
     - Maximum requests per window.
   * - ``RATE_LIMIT_WINDOW``
     - ``60``
     - Window duration in seconds.
   * - ``RATE_LIMIT_BY``
     - ``"ip"``
     - Key strategy: ``"ip"``, ``"user"``, or ``"path"``.
   * - ``RATE_LIMIT_BACKEND``
     - ``"memory"``
     - Counter backend: ``"memory"`` or ``"redis"``.

**Security settings** (``SecurityMiddleware``):

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Setting
     - Default
     - Description
   * - ``SECURE_SSL_REDIRECT``
     - ``False``
     - Redirect all HTTP requests to HTTPS.
   * - ``SECURE_HSTS_SECONDS``
     - ``0``
     - HSTS ``max-age``.  ``0`` disables the header.
   * - ``SECURE_HSTS_INCLUDE_SUBDOMAINS``
     - ``False``
     - Include ``includeSubDomains`` in HSTS.
   * - ``SECURE_HSTS_PRELOAD``
     - ``False``
     - Include ``preload`` in HSTS.
   * - ``X_FRAME_OPTIONS``
     - ``"DENY"``
     - ``X-Frame-Options`` value.  Set to ``""`` to disable.
   * - ``SECURE_BROWSER_XSS_FILTER``
     - ``False``
     - **Deprecated.** Adds ``X-XSS-Protection`` header.
   * - ``SECURE_CONTENT_SECURITY_POLICY``
     - ``None``
     - CSP as a dict or string.
   * - ``SECURE_PERMISSIONS_POLICY``
     - ``None``
     - ``Permissions-Policy`` header value.
   * - ``SECURE_CROSS_ORIGIN_OPENER_POLICY``
     - ``None``
     - ``Cross-Origin-Opener-Policy`` header value.
   * - ``SECURE_CROSS_ORIGIN_EMBEDDER_POLICY``
     - ``None``
     - ``Cross-Origin-Embedder-Policy`` header value.
   * - ``SECURE_CROSS_ORIGIN_RESOURCE_POLICY``
     - ``None``
     - ``Cross-Origin-Resource-Policy`` header value.
   * - ``ALLOWED_HOSTS``
     - ``()``
     - Permitted ``Host`` header values.  ``"*"`` allows all.

.. code-block:: python

    import dataclasses
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        MIDDLEWARE: tuple = (
            "openviper.middleware.security.SecurityMiddleware",
            "openviper.middleware.cors.CORSMiddleware",
            "openviper.middleware.db.DatabaseMiddleware",
            "openviper.middleware.csrf.CSRFMiddleware",
            "openviper.middleware.ratelimit.RateLimitMiddleware",
            "openviper.auth.middleware.AuthenticationMiddleware",
        )

        # CORS
        CORS_ALLOWED_ORIGINS: tuple = ("https://frontend.example.com",)
        CORS_ALLOW_CREDENTIALS: bool = True
        CORS_ALLOWED_METHODS: tuple = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        CORS_ALLOWED_HEADERS: tuple = ("Content-Type", "Authorization", "X-CSRFToken")
        CORS_EXPOSE_HEADERS: tuple = ("X-Request-Id",)
        CORS_MAX_AGE: int = 3600

        # Security
        SECURE_SSL_REDIRECT: bool = True
        SECURE_HSTS_SECONDS: int = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = True
        SECURE_HSTS_PRELOAD: bool = True
        ALLOWED_HOSTS: tuple = (".example.com",)

        # CSRF
        CSRF_TRUSTED_ORIGINS: tuple = ("https://frontend.example.com",)
        CSRF_COOKIE_SECURE: bool = True
        CSRF_COOKIE_SAMESITE: str = "Lax"

        # Rate limiting
        RATE_LIMIT_REQUESTS: int = 200
        RATE_LIMIT_WINDOW: int = 60
        RATE_LIMIT_BY: str = "ip"

Programmatic Composition
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper import OpenViper
    from openviper.middleware.cors import CORSMiddleware
    from openviper.middleware.csrf import CSRFMiddleware
    from openviper.middleware.db import DatabaseMiddleware
    from openviper.middleware.security import SecurityMiddleware
    from openviper.middleware.ratelimit import RateLimitMiddleware
    from openviper.auth.middleware import AuthenticationMiddleware

    app = OpenViper()
    app = SecurityMiddleware(
        app,
        hsts_seconds=31536000,
        hsts_include_subdomains=True,
        hsts_preload=True,
        ssl_redirect=True,
        x_frame_options="SAMEORIGIN",
        csp={"default-src": "'self'"},
    )
    app = CORSMiddleware(
        app,
        allowed_origins=["https://frontend.example.com"],
        allow_credentials=True,
        expose_headers=["X-Request-Id"],
        max_age=3600,
    )
    app = CSRFMiddleware(app, exempt_paths=["/api/webhooks"])
    app = DatabaseMiddleware(app)
    app = RateLimitMiddleware(app, max_requests=200, window_seconds=60)
    app = AuthenticationMiddleware(app)

Using ``build_middleware_stack``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.middleware.base import build_middleware_stack
    from openviper.middleware.cors import CORSMiddleware
    from openviper.middleware.ratelimit import RateLimitMiddleware

    app = build_middleware_stack(core_app, [
        (CORSMiddleware, {"allowed_origins": ["*"]}),
        (RateLimitMiddleware, {"max_requests": 100, "window_seconds": 60}),
    ])

CSRF Token in Forms
~~~~~~~~~~~~~~~~~~~~

Include the CSRF token in HTML forms:

.. code-block:: html

    <form method="post" action="/submit">
      <input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf_token }}">
      ...
    </form>

For AJAX requests, read the ``csrftoken`` cookie and send it as the
``X-CSRFToken`` header:

.. code-block:: javascript

    const csrfToken = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
    fetch("/api/data", {
        method: "POST",
        headers: {"X-CSRFToken": csrfToken, "Content-Type": "application/json"},
        body: JSON.stringify({key: "value"}),
    });

Rate Limiting a Single View
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.middleware.ratelimit import rate_limit

    @router.post("/auth/login")
    @rate_limit(max_requests=5, window_seconds=60)
    async def login(request: Request) -> JSONResponse:
        # At most 5 login attempts per IP per minute
        ...

Custom Middleware
~~~~~~~~~~~~~~~~~

.. code-block:: python

    import time
    import uuid

    from openviper.http.request import Request
    from openviper.middleware.base import BaseMiddleware

    class TimingMiddleware(BaseMiddleware):
        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            start = time.perf_counter()
            await self.app(scope, receive, send)
            elapsed = time.perf_counter() - start
            print(f"{scope['path']} took {elapsed * 1000:.1f}ms")

    class RequestIdMiddleware(BaseMiddleware):
        """Attach a unique request ID to every request's state."""

        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] == "http":
                req = Request(scope, receive)
                req.state["request_id"] = str(uuid.uuid4())
            await self.app(scope, receive, send)
