.. _exceptions:

Exception Reference
===================

All OpenViper exceptions are defined in ``openviper.exceptions`` and form a
single hierarchy rooted at :class:`OpenViperException`.  HTTP exceptions carry
a ``status_code`` and are automatically converted to JSON error responses by
the framework's error handler.

Overview
--------

The exception hierarchy is organized into five groups:

1. **Configuration** - raised during startup when settings are invalid.
2. **HTTP** - raised inside view handlers to return specific HTTP status codes.
3. **ORM/Database** - raised by the ORM layer on query errors.
4. **Middleware** - raised within the middleware pipeline.
5. **AI** - raised by the AI provider registry.

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
    │   ├── TableNotFound
    │   ├── QueryError
    │   └── FieldError
    ├── MigrationError
    ├── MiddlewareException
    └── AIException
        ├── ModelNotFoundError
        └── ModelCollisionError

Type Aliases
-------------

.. py:data:: DetailValue

   Type alias for values accepted by :exc:`HTTPException` ``detail``
   parameter::

      type DetailValue = str | dict[str, str | int] | list[dict[str, str | int]] | None

   When ``None``, the default detail phrase for the status code is used
   (resolved via :func:`HTTPException.default_detail`).

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
   structured JSON error response with the given status code.  *detail*
   accepts a :data:`DetailValue` - a string, structured dict, list of
   dicts, or ``None``.  When ``None``, the HTTP status phrase is used
   automatically via :func:`HTTPException.default_detail`.

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

   Returns **422 Unprocessable Entity**.  *errors* is a
   ``list[dict[str, str]]`` or ``dict[str, str]`` included verbatim in
   the response body.

.. py:exception:: Conflict(detail="Conflict.")

   Returns **409 Conflict**.

.. py:exception:: TooManyRequests(retry_after=None, detail=None)

   Returns **429 Too Many Requests**.  When *retry_after* is given the
   ``Retry-After`` header is set.

.. py:exception:: ServiceUnavailable(detail="Service unavailable.")

   Returns **503 Service Unavailable**.

.. py:exception:: AuthenticationFailed(detail="Invalid credentials.")

   Returns **401 Unauthorized**.  Used by auth backends on credential failure.

.. py:exception:: TokenExpired()

   Subclass of :exc:`AuthenticationFailed` - raised when a JWT is expired.

.. py:exception:: ORMException

   Base exception for all ORM and database errors.

.. py:exception:: DoesNotExist

   Raised by the ORM when ``get()`` finds no matching record.

.. py:exception:: MultipleObjectsReturned

   Raised by the ORM when ``get()`` matches more than one record.

.. py:exception:: IntegrityError

   Raised when a database integrity constraint is violated.

.. py:exception:: TableNotFound(model_name, table_name)

   Raised when a model's database table does not exist.  Carries
   ``model_name`` and ``table_name`` attributes.

.. py:exception:: QueryError(detail="Invalid query.")

   Raised when an ORM query is structurally invalid - for example,
   referencing a non-existent field or using a malformed filter expression.

.. py:exception:: FieldError(detail="Field does not exist.")

   Raised when a referenced field does not exist on the model.

.. py:exception:: MigrationError

   Raised when a migration cannot be applied or reversed.

.. py:exception:: MiddlewareException(detail="Middleware error.")

   Raised within the middleware pipeline.  Carries a ``detail`` attribute.

.. py:exception:: AIException

   Base exception for all OpenViper AI errors.

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
