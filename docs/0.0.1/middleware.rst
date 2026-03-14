.. _middleware:

Middleware
==========

The ``openviper.middleware`` package provides a set of built-in ASGI middlewares
for cross-cutting concerns: CORS, CSRF protection, rate limiting, security
headers, and authentication.  All middlewares follow the standard ASGI callable
protocol and can be composed freely.

Overview
--------

Middlewares are registered in ``settings.MIDDLEWARE`` (a tuple of dotted import
paths) or attached programmatically by wrapping the ASGI app.  Each middleware
accepts the next ``app`` as its first constructor argument.

The stack is applied **inner-first**: the first entry in the list wraps the
outermost layer (first to receive the request, last to process the response).

Key Classes
-----------

``openviper.middleware.cors``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: CORSMiddleware(app, allowed_origins=None, allow_credentials=False, allowed_methods=None, allowed_headers=None, expose_headers=None, max_age=600)

   Adds ``Access-Control-*`` headers and handles preflight ``OPTIONS`` requests.

   - ``allowed_origins`` — list of allowed origin strings.  Supports
     ``"*"`` (all) and wildcard patterns such as
     ``"https://*.example.com"``.  Defaults to ``["*"]``.
   - ``allow_credentials`` — set ``Access-Control-Allow-Credentials: true``
     and allow ``Authorization`` headers / cookies cross-origin.
     Defaults to ``False`` for security.
   - ``allowed_methods`` — permitted request methods.  Defaults to ``["*"]``
     (all methods).
   - ``allowed_headers`` — permitted request headers.  Defaults to ``["*"]``
     (all headers).
   - ``expose_headers`` — list of headers to expose to the browser via
     ``Access-Control-Expose-Headers``.  Defaults to ``[]``.
   - ``max_age`` — preflight response cache TTL in seconds (default: 600).

   Origin patterns are compiled at ``__init__`` time so no per-request
   regex compilation occurs.

``openviper.middleware.csrf``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: CSRFMiddleware(app, secret="", cookie_name="csrftoken", header_name="x-csrftoken", exempt_paths=None)

   Double-submit cookie CSRF protection for unsafe methods (``POST``, ``PUT``,
   ``PATCH``, ``DELETE``).

   The CSRF token is stored in a cookie (``csrftoken``) and must be
   re-submitted in either:

   - The ``X-CSRFToken`` request header, **or**
   - The ``csrfmiddlewaretoken`` form field.

   ``GET``, ``HEAD``, and ``OPTIONS`` requests pass through without validation.

   - ``secret`` — signing secret.  Defaults to ``settings.SECRET_KEY``.
   - ``cookie_name`` — name of the CSRF cookie.
   - ``header_name`` — name of the HTTP header to check.
   - ``exempt_paths`` — list of path strings that skip CSRF validation
     (e.g. ``["/api/webhooks"]``).

   Token verification uses HMAC-SHA256 with a per-request salt (128-bit)
   and ``hmac.compare_digest`` for constant-time comparison.

``openviper.middleware.ratelimit``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: RateLimitMiddleware(app, max_requests=None, window_seconds=None, key_func=None)

   Sliding-window rate limiter using 256 independent lock stripes for high
   concurrency.

   - ``max_requests`` — requests allowed per *window* (default: ``RATE_LIMIT_REQUESTS``
     setting, or 100).
   - ``window_seconds`` — time window in seconds (default: ``RATE_LIMIT_WINDOW``
     setting, or 60).
   - ``key_func`` — callable ``(scope) -> str`` that returns the bucket key.
     Defaults to the client IP address from the ASGI ``client`` tuple.

   Responds with **429 Too Many Requests** when the limit is exceeded and
   sets ``X-RateLimit-Limit``, ``X-RateLimit-Remaining``, and
   ``Retry-After`` headers on every response.

.. py:function:: openviper.middleware.ratelimit.rate_limit(max_requests=60, window_seconds=60.0)

   Per-view rate limit **decorator** (alternative to the middleware).
   Limits by client IP.  Raises
   :class:`~openviper.exceptions.TooManyRequests` (429) when exceeded.

``openviper.middleware.security``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: SecurityMiddleware(app, ssl_redirect=False, hsts_seconds=0, hsts_include_subdomains=False, hsts_preload=False, x_frame_options="DENY", content_type_nosniff=True, xss_filter=None, csp=None)

   Adds HTTP security headers to every response.

   Headers added unconditionally (when the corresponding option is enabled):

   - ``X-Content-Type-Options: nosniff`` (``content_type_nosniff=True``)
   - ``X-Frame-Options: DENY`` (configurable; set to ``""`` to disable)
   - ``Referrer-Policy: strict-origin-when-cross-origin``
   - ``X-XSS-Protection: 1; mode=block`` (``xss_filter=True``; legacy header)

   Conditional headers:

   - ``Strict-Transport-Security: max-age=N[; includeSubDomains][; preload]``
     — when ``hsts_seconds > 0``.
   - HTTP → HTTPS redirect — when ``ssl_redirect=True``.
   - ``Content-Security-Policy`` — when *csp* is provided as a dict or string.

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

Registering via Settings
~~~~~~~~~~~~~~~~~~~~~~~~~

When ``"openviper.middleware.cors.CORSMiddleware"`` is listed in ``MIDDLEWARE``,
OpenViper automatically reads the following settings and passes them as constructor
arguments — no manual wiring required:

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

.. code-block:: python

    import dataclasses
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        MIDDLEWARE: tuple = (
            "openviper.middleware.security.SecurityMiddleware",
            "openviper.middleware.cors.CORSMiddleware",
            "openviper.auth.middleware.AuthenticationMiddleware",
        )

        # CORS is configured here — automatically picked up by CORSMiddleware
        CORS_ALLOWED_ORIGINS: tuple = ("https://frontend.example.com",)
        CORS_ALLOW_CREDENTIALS: bool = True
        CORS_ALLOWED_METHODS: tuple = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        CORS_ALLOWED_HEADERS: tuple = ("Content-Type", "Authorization", "X-CSRFToken")
        CORS_EXPOSE_HEADERS: tuple = ("X-Request-Id",)
        CORS_MAX_AGE: int = 3600

Programmatic Composition
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper import OpenViper
    from openviper.middleware.cors import CORSMiddleware
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

    from openviper.middleware.base import BaseMiddleware
    import time

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

        import uuid

        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] == "http":
                from openviper.http.request import Request
                req = Request(scope, receive)
                req.state["request_id"] = str(self.uuid.uuid4())
            await self.app(scope, receive, send)
