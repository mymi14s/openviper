.. _exceptions:

Exception Reference
===================

All OpenViper exceptions are defined in ``openviper.exceptions`` and form a
single hierarchy rooted at :class:`OpenViperException`.  HTTP exceptions carry
a ``status_code`` and are automatically converted to JSON error responses by
the framework's error handler.

Overview
--------

The exception hierarchy is organized into four groups:

1. **Configuration** — raised during startup when settings are invalid.
2. **HTTP** — raised inside view handlers to return specific HTTP status codes.
3. **ORM/Database** — raised by the ORM layer on query errors.
4. **AI** — raised by the AI provider registry.

Exception Hierarchy
-------------------

.. code-block:: text

    OpenViperException
    ├── ImproperlyConfigured
    ├── SettingsValidationError
    ├── HTTPException
    │   ├── NotFound                 (404)
    │   ├── MethodNotAllowed         (405)
    │   ├── PermissionDenied         (403)
    │   ├── Unauthorized             (401)
    │   ├── ValidationError          (422)
    │   ├── Conflict                 (409)
    │   ├── TooManyRequests          (429)
    │   ├── ServiceUnavailable       (503)
    │   └── AuthenticationFailed     (401)
    │       └── TokenExpired         (401)
    ├── ORMException
    │   ├── DoesNotExist
    │   ├── MultipleObjectsReturned
    │   ├── IntegrityError
    │   ├── MigrationError
    │   └── FieldError
    ├── MiddlewareException
    └── AIException
        ├── ModelNotFoundError
        └── ModelCollisionError

Key Exceptions
--------------

.. py:exception:: OpenViperException

   Base exception for all OpenViper errors.

.. py:exception:: ImproperlyConfigured

   Raised when the framework or application is incorrectly configured.

.. py:exception:: SettingsValidationError

   Raised when settings fail validation on startup.  Carries an ``errors``
   list of human-readable messages.

.. py:exception:: HTTPException(status_code, detail=None, headers=None)

   Base HTTP error.  Raise this (or a subclass) from any view to return a
   structured JSON error response with the given status code.

.. py:exception:: NotFound(detail="Not found.")

   Returns **404 Not Found**.

.. py:exception:: MethodNotAllowed(allowed)

   Returns **405 Method Not Allowed** with an ``Allow`` header listing the
   permitted methods.

.. py:exception:: PermissionDenied(detail="Permission denied.")

   Returns **403 Forbidden**.

.. py:exception:: Unauthorized(detail="Authentication required.")

   Returns **401 Unauthorized** with ``WWW-Authenticate: Bearer``.

.. py:exception:: ValidationError(errors)

   Returns **422 Unprocessable Entity**.  *errors* is included verbatim in
   the response body.

.. py:exception:: Conflict(detail="Conflict.")

   Returns **409 Conflict**.

.. py:exception:: TooManyRequests(retry_after=None, detail=None)

   Returns **429 Too Many Requests**.  When *retry_after* is given the
   ``Retry-After`` header is set.

.. py:exception:: AuthenticationFailed(detail="Invalid credentials.")

   Returns **401 Unauthorized**.  Used by auth backends on credential failure.

.. py:exception:: TokenExpired()

   Subclass of :exc:`AuthenticationFailed` — raised when a JWT is expired.

.. py:exception:: DoesNotExist

   Raised by the ORM when ``get()`` finds no matching record.

.. py:exception:: MultipleObjectsReturned

   Raised by the ORM when ``get()`` matches more than one record.

.. py:exception:: ModelNotFoundError(model, available=None)

   Raised by :class:`~openviper.ai.registry.ProviderRegistry` when the
   requested model ID is not registered.

.. py:exception:: ModelCollisionError(model, existing_provider, new_provider)

   Raised when two AI providers try to claim the same model ID.

Example Usage
-------------

Raising HTTP Exceptions in Views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.exceptions import NotFound, PermissionDenied, ValidationError
    from openviper.http.request import Request
    from openviper.http.response import JSONResponse

    async def get_post(request: Request, post_id: int) -> JSONResponse:
        post = await Post.objects.get_or_none(id=post_id)
        if post is None:
            raise NotFound(f"Post {post_id} does not exist.")
        if not post.is_published and not request.user.is_staff:
            raise PermissionDenied("You cannot view this post.")
        return JSONResponse(post._to_dict())

Handling ORM Exceptions
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.exceptions import DoesNotExist

    async def get_user(request):
        try:
            user = await User.objects.get(email="alice@example.com")
        except DoesNotExist:
            return JSONResponse({"error": "User not found"}, status_code=404)

Custom HTTP Exception
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.exceptions import HTTPException

    raise HTTPException(451, detail="Unavailable for legal reasons.")
