.. _exceptions:

====================
Exceptions Reference
====================

All OpenViper exceptions are defined in :mod:`openviper.exceptions` and
inherit from :class:`~openviper.exceptions.OpenViperException`.

.. contents:: On this page
   :local:
   :depth: 2

----

HTTP Exceptions
----------------

HTTP exceptions are raised inside view handlers to return specific error
responses.  OpenViper's exception handler converts them to JSON
``{"detail": "..."}`` responses automatically.

.. code-block:: python

   from openviper.exceptions import NotFound, PermissionDenied, ValidationError

   async def get_post(request, post_id: int):
       post = await Post.objects.get_or_none(id=post_id)
       if post is None:
           raise NotFound("Post not found.")
       if not post.published and request.user != post.author:
           raise PermissionDenied("You cannot view unpublished posts.")
       return JSONResponse(PostSerializer.from_orm(post).serialize())

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Exception
     - Status
     - Notes
   * - ``HTTPException``
     - any
     - Base; pass ``status_code`` and ``detail`` explicitly
   * - ``NotFound``
     - 404
     - Record not found; ``detail`` defaults to ``"Not found."``
   * - ``MethodNotAllowed``
     - 405
     - Pass ``allowed`` list; sets ``Allow`` header automatically
   * - ``PermissionDenied``
     - 403
     - User lacks permission
   * - ``Unauthorized``
     - 401
     - Not authenticated; sets ``WWW-Authenticate: Bearer``
   * - ``AuthenticationFailed``
     - 401
     - Invalid credentials (distinct from ``Unauthorized``)
   * - ``TokenExpired``
     - 401
     - JWT or session token has expired (subclass of ``AuthenticationFailed``)
   * - ``ValidationError``
     - 422
     - Request body / parameter validation failure
   * - ``Conflict``
     - 409
     - Resource already exists or state conflict
   * - ``TooManyRequests``
     - 429
     - Rate limit exceeded; pass ``retry_after`` seconds to set ``Retry-After`` header
   * - ``ServiceUnavailable``
     - 503
     - Downstream dependency unavailable

Examples:

.. code-block:: python

   from openviper.exceptions import (
       Conflict,
       TooManyRequests,
       ServiceUnavailable,
       AuthenticationFailed,
       TokenExpired,
   )

   # 409 when a unique constraint would be violated
   raise Conflict("A user with this email already exists.")

   # 429 with a Retry-After header
   raise TooManyRequests(retry_after=60)

   # 503 when a required service is down
   raise ServiceUnavailable("AI provider is temporarily unavailable.")

   # 401 with a custom message
   raise AuthenticationFailed("Invalid API key.")

   # 401 token expired (raised automatically by JWT middleware)
   raise TokenExpired()

Custom exception handlers:

.. code-block:: python

   from openviper import OpenViper
   from openviper.exceptions import ValidationError
   from openviper import JSONResponse

   app = OpenViper(...)

   @app.exception_handler(ValidationError)
   async def handle_validation_error(request, exc: ValidationError):
       return JSONResponse(
           {"errors": exc.validation_errors},
           status_code=422,
       )

----

ORM / Database Exceptions
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Exception
     - Raised when
   * - ``DoesNotExist``
     - ``.get()`` found no matching record
   * - ``MultipleObjectsReturned``
     - ``.get()`` matched more than one record
   * - ``IntegrityError``
     - Database constraint violated (e.g. unique, foreign key)
   * - ``MigrationError``
     - Migration could not be applied or reversed

.. code-block:: python

   from openviper.exceptions import DoesNotExist, IntegrityError

   try:
       post = await Post.objects.get(id=post_id)
   except DoesNotExist:
       raise NotFound("Post not found.")

   try:
       await user.save()
   except IntegrityError:
       raise Conflict("A user with this email already exists.")

----

AI Exceptions
--------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Exception
     - Raised when
   * - ``AIException``
     - Base class for all AI-related errors
   * - ``ModelNotFoundError``
     - Requested model ID is not registered in the ProviderRegistry
   * - ``ModelCollisionError``
     - A model ID is already registered and ``allow_override=False``
   * - ``ProviderNotConfiguredError``
     - Provider type is listed in settings but has no usable config
   * - ``ProviderNotAvailableError``
     - Provider cannot be initialised (missing SDK or bad API key)
   * - ``ModelUnavailableError``
     - Model is registered but the provider cannot serve it

.. code-block:: python

   from openviper.exceptions import AIException
   from openviper.ai.exceptions import ModelNotFoundError, ProviderNotAvailableError

   try:
       provider = provider_registry.get_by_model("unknown-model")
   except ModelNotFoundError as exc:
       print(f"Model not found: {exc.model}")
       print(f"Available: {exc.available}")

   try:
       response = await provider.generate(prompt)
   except AIException as exc:
       print(f"AI error: {exc}")

----

Configuration Exceptions
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Exception
     - Raised when
   * - ``ImproperlyConfigured``
     - Framework or application is incorrectly configured
   * - ``SettingsValidationError``
     - Settings dataclass fails validation at startup

These are raised at application start-up and should not be caught in
normal application code.

.. seealso::

   :ref:`settings` — full configuration reference.
