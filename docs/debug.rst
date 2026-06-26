.. _debug:

Debug Page
==========

The ``openviper.debug`` package provides a rich HTML traceback page that is
rendered when ``DEBUG=True`` and an unhandled exception escapes the ASGI
stack.  In production mode a plain ``500 Internal Server Error`` text body is
returned instead.

The debug page is activated automatically by
:class:`~openviper.middleware.error.ServerErrorMiddleware` - no manual
integration is required.

.. rubric:: Security warning

The debug page exposes internal application state (source code, local
variables, request metadata).  **Never run with ``DEBUG=True`` in
production.**

Overview
--------

When an unhandled exception occurs in debug mode, the middleware calls
:func:`~openviper.debug.traceback_page.render_debug_page` which produces a
self-contained HTML document with:

* **Exception header** - fully-qualified exception type and message.
* **Traceback frames** - source code context (7 lines around each frame) with
  the offending line highlighted.
* **Exception chain** - ``__cause__`` and ``__context__`` links rendered as
  inline notes.
* **Request metadata** - HTTP method, path, query parameters, and headers.

Credential Redaction
--------------------

The debug page applies multiple layers of credential redaction to prevent
accidental leakage of secrets even in debug output.

Exception messages
^^^^^^^^^^^^^^^^^^

All exception messages (including chained exceptions) pass through
:func:`~openviper.debug.traceback_page.redact_credentials` before rendering.
The function matches and masks common credential patterns:

* **Database URLs** - passwords in ``postgres://``, ``mysql://``,
  ``redis://``, ``mongodb://``, ``amqp://`` connection strings are replaced
  with ``********``.
* **Python assignments** - ``SECRET_KEY = "..."``, ``API_KEY = '...'``,
  ``PASSWORD = ...`` patterns are masked.
* **Auth tokens** - ``Bearer ...`` and ``Basic ...`` tokens are masked.
* **Generic key-value** - ``api-key: ...``, ``password: ...``,
  ``token: ...`` patterns (8+ character values) are masked.

Source code frames
^^^^^^^^^^^^^^^^^^

Each source line rendered in a traceback frame is also passed through
:func:`~openviper.debug.traceback_page.redact_credentials`.  If the traceback
includes a frame from a settings module, credential assignments like
``SECRET_KEY = "real-key"`` are redacted.

Request headers
^^^^^^^^^^^^^^^

Header values are masked when the header name (case-insensitive) is in
:data:`~openviper.debug.traceback_page.SENSITIVE_HEADERS`:

.. list-table::
   :header-rows: 0
   :widths: 50 50

   * - ``authorization``
     - ``cookie``
   * - ``set-cookie``
     - ``x-api-key``
   * - ``api-key``
     - ``x-forwarded-for``
   * - ``x-real-ip``
     - ``proxy-authorization``
   * - ``www-authenticate``
     - ``x-csrf-token``
   * - ``x-xsrf-token``
     - ``x-auth-token``
   * - ``x-access-token``
     - ``x-refresh-token``
   * - ``x-session-id``
     -

Query parameters
^^^^^^^^^^^^^^^^

Query parameter values are masked when the parameter name (case-insensitive)
is in :data:`~openviper.debug.traceback_page.SENSITIVE_QUERY_PARAMS`:

.. list-table::
   :header-rows: 0
   :widths: 50 50

   * - ``password``
     - ``passwd``
   * - ``secret``
     - ``token``
   * - ``api_key``
     - ``apikey``
   * - ``access_token``
     - ``refresh_token``
   * - ``private_key``
     - ``client_secret``
   * - ``client_id``
     - ``session_id``
   * - ``sessionid``
     - ``csrf_token``
   * - ``xsrf_token``
     -

API Reference
-------------

.. py:data:: openviper.debug.traceback_page.SENSITIVE_HEADERS

   ``frozenset[str]`` - HTTP header names whose values are masked in debug
   output.

.. py:data:: openviper.debug.traceback_page.SENSITIVE_QUERY_PARAMS

   ``frozenset[str]`` - Query parameter names whose values are masked in
   debug output.

.. py:data:: openviper.debug.traceback_page.CREDENTIAL_PATTERNS

   ``list[re.Pattern[str]]`` - Compiled regex patterns used by
   :func:`redact_credentials` to detect and mask credential-bearing strings.

.. py:function:: openviper.debug.traceback_page.redact_credentials(text: str) -> str

   Redact credential patterns from *text*, replacing matched secrets with
   ``********``.  Iterates over :data:`CREDENTIAL_PATTERNS` and applies each
   pattern as a substitution.

.. py:function:: openviper.debug.traceback_page.sanitize_header_value(key: str, value: str) -> str

   Return ``"********"`` when *key* (lowercased) is in
   :data:`SENSITIVE_HEADERS`; otherwise return *value* unchanged.

.. py:function:: openviper.debug.traceback_page.sanitize_query_param(key: str, value: str) -> str

   Return ``"********"`` when *key* (lowercased) is in
   :data:`SENSITIVE_QUERY_PARAMS`; otherwise return *value* unchanged.

.. py:function:: openviper.debug.traceback_page.render_debug_page(exc: BaseException, request: _DebugRequest | None = None) -> str

   Render a self-contained HTML 500 page for *exc*.

   :param exc: Unhandled exception.
   :param request: Optional request object for metadata (must provide
     ``method``, ``path``, ``query_params``, ``headers``).
   :returns: HTML string suitable as an HTTP 500 response body.
