.. _serializers:

Serializers
===========

The ``openviper.serializers`` package provides a Pydantic v2-based
serialization and validation layer.  :class:`Serializer` is a thin wrapper
over ``pydantic.BaseModel`` giving it OpenViper-idiomatic helpers, while
:class:`ModelSerializer` auto-generates fields directly from an ORM model.

Overview
--------

Use :class:`Serializer` to:

- Validate and deserialize incoming request data.
- Serialize outgoing ORM instances to plain dicts / JSON.
- Produce OpenAPI-compatible JSON Schema for Swagger UI.

Use :class:`ModelSerializer` to remove duplication between ORM model
fields and serializer fields - just point ``Meta.model`` at your model class.

The two classes share a common API.  The main difference is where fields
come from:

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Feature
     - ``Serializer``
     - ``ModelSerializer``
   * - Field source
     - Manually declared type annotations
     - Auto-generated from ``Meta.model``
   * - ``Meta`` class
     - Not required
     - Required (``model``, ``fields`` / ``exclude``)
   * - ORM ``save()`` / ``create()`` / ``update()``
     - Not provided
     - Built-in, delegates to ``Model.objects``
   * - File field handling
     - Manual
     - Automatic (``FileField`` / ``ImageField``)
   * - ``readonly_fields``
     - Class variable
     - Also set via ``Meta.readonly_fields``

Key Classes & Functions
-----------------------

.. py:class:: openviper.serializers.Serializer

   Base serializer backed by Pydantic v2.  Declare fields as annotated
   class attributes exactly as you would in a ``BaseModel``.

   **Class variables** (set at class level, not instance level):

   .. py:attribute:: readonly_fields
      :type: tuple[str, ...]

      Fields included in serialized output but stripped before
      ``create()`` / ``update()`` writes.  Defaults to ``()``.

   .. py:attribute:: writeonly_fields
      :type: tuple[str, ...]

      Fields accepted on input but excluded from ``serialize()`` output
      (e.g. passwords).  Defaults to ``()``.

   .. py:attribute:: PAGE_SIZE
      :type: int

      Batch size used by :meth:`serialize_many` when the input is a
      ``QuerySet``.  Defaults to ``25``.

   .. py:attribute:: MAX_PAGE_SIZE
      :type: int

      Upper bound for ``page_size`` in :meth:`paginate`.  Defaults to ``1000``.

   .. py:attribute:: permission_classes
      :type: list[type[PermissionProtocol]]

      List of permission classes evaluated by :meth:`check_permissions`.
      Each class must implement the :class:`PermissionProtocol` interface
      (``async has_permission(request, serializer) -> bool``).
      Defaults to ``[]``.  When empty, no permission checks are performed.

   .. py:attribute:: validated_data
      :type: dict[str, Any]

      Validated in-memory input values after instance validation.  Fields not
      supplied by the caller are omitted.  Accessing this property before
      calling ``validate()`` on a staged ``data=...`` serializer raises
      ``RuntimeError``.

   **Permission checks:**

   .. py:method:: check_permissions() -> Awaitable[None]

      Evaluate all ``permission_classes`` against the current request.
      Raises :class:`~openviper.exceptions.PermissionDenied` on the first
      failing permission.  Returns immediately when no request is bound
      and no ambient user is present (via ``current_user`` context var).

   .. py:method:: permission_denied(request, message=None) -> None

      Raise :class:`~openviper.exceptions.PermissionDenied` with the
      given *message* (defaults to ``"Permission denied."``).

   **Parsing / deserialization:**

   .. py:classmethod:: validate_data(data, *, partial=False, context=None) -> Self

      Parse and validate *data* (dict, ORM object, or mapping).  Raises
      :class:`~openviper.exceptions.ValidationError` with structured error
      details on failure.

      When ``partial=True`` every field becomes optional, which is ideal
      for ``PATCH`` endpoints.  The returned instance tracks which fields
      were supplied via ``model_fields_set``; call
      ``model_dump(exclude_unset=True)`` to get only the changed keys.

      Pass ``context`` to make extra data available to field validators
      (via Pydantic's ``ValidationInfo.context``) and to the serializer
      instance itself (accessible via ``.context``).  Typical usage:
      ``context={"request": request}``.

      Partial classes preserve all original ``FieldInfo`` constraints
      (``min_length``, ``pattern``, custom validators, etc.) - only the
      ``default`` is relaxed to ``None`` so missing fields are accepted.

   .. py:attribute:: validate
      :type: SerializerValidationDescriptor

      Convenience descriptor that delegates to :meth:`validate_data`.
      Supports both class-level and instance-level calls:

      .. code-block:: python

         # Class-level: validates fresh data
         serializer = PostSerializer.validate_data(payload)

         # Instance-level: validates staged data
         serializer = PostSerializer(data=payload)
         serializer.validate()

      Instance validation also accepts ``raise_exception=True`` to raise an
      immediate HTTP ``422`` response carrying the structured validation
      reasons:

      .. code-block:: python

         serializer = PostSerializer(data=payload)
         serializer.validate(raise_exception=True)

   .. py:classmethod:: validate_json_string(json_str) -> Self

      Parse a raw JSON string directly (bypasses the ``body()`` call).
      Raises :class:`~openviper.exceptions.ValidationError` if the input
      exceeds ``MAX_JSON_STRING_BYTES`` (1 MiB by default).

   .. py:classmethod:: from_orm(obj) -> Self

      Build a serializer instance from an ORM model instance (or any
      object with the right attributes).

      ``ForeignKey`` fields are automatically unwrapped to their raw
      foreign-key ID.  If the ORM descriptor returns a related model
      instance, its primary key is extracted so the serializer receives
      an ``int`` (or ``None``) rather than a nested object.

   .. py:classmethod:: from_orm_many(objs) -> list[Self]

      Build a list of serializer instances from a list of ORM objects.

   **Internal helpers** (used by ``serialize_many`` / ``paginate``):

   .. py:classmethod:: get_excluded_fields(exclude=None) -> frozenset[str]

      Return ``writeonly_fields`` merged with *exclude*.  Returns an
      empty ``frozenset`` when neither is set.

   .. py:staticmethod:: serialize_value(value) -> bool | int | float | str | list | dict | None

      Convert a single value to a JSON-serializable type.  Handles
      ``Decimal``, ``datetime``, ``date``, ``time``, ``UUID``, ``bytes``
      (base64), ``LazyFK`` (unwrapped to FK id), and nested
      ``list`` / ``dict`` containers recursively.

   .. py:classmethod:: obj_to_dict(obj, excl) -> dict[str, Any]

      Map a single ORM object to a JSON-safe dict using direct
      attribute access (no Pydantic model instantiation).  Fields in
      *excl* are omitted.

   .. py:classmethod:: build_partial_class() -> type[Self]

      Return a version of this class where every field is optional.
      The result is cached on ``PARTIAL_CLASSES`` (a
      ``WeakKeyDictionary``) so it is only created once per
      serializer class.

   .. py:method:: compute_excluded(exclude=None) -> set[str] | None

      Instance-level counterpart of :meth:`get_excluded_fields`.
      Returns ``writeonly_fields`` merged with *exclude*, or ``None``
      when the result is empty.

   **Serialization:**

   .. py:method:: serialize(*, exclude=None) -> dict[str, Any]

      Return a JSON-safe ``dict``.  ``writeonly_fields`` are automatically
      excluded.  Pass an additional ``exclude`` set to drop more fields.
      ``bytes`` values are encoded as base64 strings to avoid leaking
      raw binary data through JSON fallbacks.

   .. py:method:: serialize_json(*, exclude=None) -> bytes

      Return JSON bytes via pydantic-core's Rust encoder (fast path).

   .. py:classmethod:: serialize_many(objs, *, exclude=None) -> Awaitable[list[dict]]

      Serialize a list **or QuerySet** of ORM objects to a list of dicts.

      When *objs* is a ``QuerySet`` (detected via ``hasattr(objs, "batch")``),
      objects are fetched in ``PAGE_SIZE``-sized batches to avoid loading
      the entire result set into memory.  Plain lists are handled with a
      simple comprehension (no DB calls).

      **Performance:** Uses direct ORM→dict mapping without intermediate
      Pydantic model validation, providing ~35-40% faster serialization
      compared to traditional double-conversion approaches.

   .. py:classmethod:: serialize_many_json(objs, *, exclude=None) -> Awaitable[bytes]

      Like :meth:`serialize_many` but returns a JSON bytes array.  Also
      uses ``PAGE_SIZE``-sized batches for QuerySets.

      **Performance:** Uses direct ORM→dict mapping (35-40% faster) and
      optimized JSON encoding for bulk serialization.

   .. py:classmethod:: paginate(qs, *, page=1, page_size=None, cursor=None, base_url="", exclude=None) -> Awaitable[PaginatedSerializer]

      Return a :class:`PaginatedSerializer` envelope for a single page of
      *qs*. Uses ``asyncio.gather()`` to execute COUNT and data fetch queries
      concurrently for ~2x faster performance.

      - *qs* must be a QuerySet (supports ``.count()``, ``.offset()``, ``.limit()``, and ``.all()``).
      - *page* is 1-based (default: 1).
      - *page_size* defaults to ``cls.PAGE_SIZE`` (default: 25).
      - *cursor* - optional base64-encoded cursor for keyset pagination (faster for Next/Prev navigation).
      - *base_url* - when given, ``next`` / ``previous`` URL strings are built.
        Only relative paths (``"/api/users"``) or ``http`` / ``https`` URLs
        are accepted; absolute URLs with an unexpected scheme or host are
        silently discarded to prevent open-redirect attacks.
      - *exclude* - set of field names to omit from serialized output.

      **Performance notes:**

      - COUNT and data fetch run in parallel via ``asyncio.gather()``.
      - OFFSET-based page jumps (e.g., page 1000) are O(N) and can be slow.
      - Cursor-based Next/Prev navigation is O(log N) using keyset seeks.
      - Exclude field computation is cached to avoid repeated set allocation.

      .. code-block:: python

         # Basic usage
         result = await PostSerializer.paginate(
             Post.objects.filter(published=True).order_by("-created_at"),
             page=2,
             page_size=20,
             base_url="/posts"
         )
         # result.count       → total matching rows
         # result.next        → "/posts?page=3&page_size=20"
         # result.previous    → "/posts?page=1&page_size=20"
         # result.next_cursor → base64 cursor for next page (or None)
         # result.results     → list[dict] for page 2

         # With cursor for fast sequential navigation
         cursor = request.query_params.get("cursor")
         result = await PostSerializer.paginate(
             Post.objects.order_by("created_at", "id"),
             page=1,
             page_size=20,
             cursor=cursor,
             base_url="/posts"
         )
         # Click "Next" uses result.next_cursor for O(log N) performance

.. py:class:: openviper.serializers.PaginatedSerializer

   Returned by :meth:`Serializer.paginate`.

   Fields:

   - ``count`` - total number of matching objects.
   - ``next`` - URL for the next page, or ``None``.
   - ``previous`` - URL for the previous page, or ``None``.
   - ``next_cursor`` - base64-encoded cursor for keyset pagination, or ``None``.
   - ``results`` - list of serialized dicts for the current page.

.. py:class:: openviper.serializers.ModelSerializer

   Extends :class:`Serializer` with automatic field generation from an ORM
   model.  Requires a nested ``Meta`` class.

   **Meta attributes:**

   - ``model`` - the ORM model class (required).
   - ``fields`` - ``"__all__"`` or a list of field names to include.
   - ``exclude`` - list of field names to exclude (alternative to ``fields``).
   - ``readonly_fields`` - tuple of field names that are output-only.
   - ``writeonly_fields`` - tuple of field names that are input-only.
   - ``extra_kwargs`` - dict of ``{field_name: {"required": False, ...}}``
     overrides applied after field auto-generation.

   **CRUD helpers** (only on ``ModelSerializer``):

   .. py:method:: create() -> Awaitable[Model]

      Persist a new model instance from the validated data.  Read-only
      fields and the PK are stripped before the INSERT.  Returns the saved
      model instance.  If a required model field is removed by
      ``readonly_fields``, a structured ``ValidationError`` is raised before
      any database write is attempted.

   .. py:method:: update(instance) -> Awaitable[Model]

      Apply validated data to an existing *instance* and save it.  Only
      fields present in ``model_fields_set`` (i.e. fields the caller
      explicitly provided) are written - safe for ``PATCH`` semantics.

   .. py:method:: save(instance=None) -> Awaitable[dict]

      Smart create-or-update.  If *instance* is provided, update it.  If
      the validated data contains a non-``None`` PK, fetch the existing
      record and update it.  Otherwise create a new record.  Returns the
      serialized dict of the persisted object.

      Database integrity failures are translated into serializer validation
      errors when possible.  For example, a duplicate unique value becomes a
      field error with ``type="unique"`` instead of an unhandled database
      exception.

   **File-field helpers** (only on ``ModelSerializer``):

   .. py:classmethod:: get_file_fields() -> MappingProxyType

      Return a read-only mapping of file-type ORM fields (``FileField``
      and ``ImageField``).  Cached with ``@lru_cache(maxsize=512)`` and
      wrapped in ``MappingProxyType`` to prevent cache mutation.

   .. py:classmethod:: validate_file_sizes(data) -> None

      Raise :class:`~openviper.exceptions.ValidationError` if any file
      value in *data* exceeds its ORM field size limit.  No-op when
      the model has no file fields.

   .. py:classmethod:: persist_files(data, *, old_instance=None) -> Awaitable[dict]

      Save file values through the storage backend.  Returns a copy of
      *data* with file values replaced by their stored paths.  On update,
      the previous file is deleted from storage after the new one is
      persisted.

   **Validation helpers** (only on ``ModelSerializer``):

   .. py:classmethod:: validate_create_data(data) -> None

      Reject creates that cannot satisfy required model fields.  Raises
      :class:`~openviper.exceptions.ValidationError` with ``type="missing"``
      for each required field absent from *data*.

   .. py:classmethod:: integrity_error_to_validation_error(exc) -> ValidationError

      Map a ``sqlalchemy.exc.IntegrityError`` to a structured
      :class:`~openviper.exceptions.ValidationError`.  Recognises
      ``UNIQUE`` and ``NOT NULL`` constraint failures and maps them
      to the offending field.  Unrecognised integrity errors produce
      a generic ``type="integrity_error"`` on ``__all__``.

   **Metaclass:**

   .. py:class:: openviper.serializers.base.ModelSerializerMeta

      Metaclass for :class:`ModelSerializer`.  Reads ``Meta.model``,
      ``Meta.fields``, ``Meta.exclude``, ``Meta.readonly_fields``,
      ``Meta.writeonly_fields``, and ``Meta.extra_kwargs`` at
      class-creation time and builds Pydantic ``model_fields``
      automatically.

   **File-field security:**

   ``FileField`` and ``ImageField`` values are handled automatically:

   - **Path traversal prevention** - directory components (``../``, ``..\\``)
     are stripped from uploaded filenames; only the basename is retained.
   - **Unsafe character rejection** - filenames containing null bytes,
     control characters, or path separators are rejected with a
     ``ValidationError``.
   - **Unique filenames** - a UUID suffix is appended to every upload so
     concurrent uploads never overwrite each other.
   - **Streaming uploads** - file-like objects are streamed directly to
     the storage backend without buffering the entire payload in memory.
   - **Safe replacement on update** - when a file changes, the old file
     is deleted only after the new file is persisted successfully.  Delete
     failures are logged as warnings rather than swallowed silently.

.. py:function:: openviper.serializers.field_validator(field_name, *, mode="before")

   Re-export of ``pydantic.field_validator``.  Attach to a serializer method
   to add per-field validation logic.

.. py:function:: openviper.serializers.model_validator(*, mode="after")

   Re-export of ``pydantic.model_validator``.  Attach to a serializer method
   for cross-field validation.

.. py:function:: openviper.serializers.computed_field

   Re-export of ``pydantic.computed_field``.  Decorate a property to include
   computed values in ``serialize()`` output.

.. py:function:: openviper.serializers.map_pydantic_errors(exc) -> ValidationError

   Convert a ``pydantic.ValidationError`` to an OpenViper
   :class:`~openviper.exceptions.ValidationError`.  Each Pydantic error
   location is flattened to a dot-separated ``field`` string (or
   ``"__all__"`` for root-level errors).

.. py:function:: openviper.serializers.python_type_for_field_by_name(field_class_name) -> type

   Return the Python type for an ORM field class name (e.g.
   ``"CharField"`` → ``str``).  Cached with ``@lru_cache(maxsize=256)``.
   Returns ``Any`` for unrecognised field names.

.. py:function:: openviper.serializers.field_is_optional(field) -> bool

   Return ``True`` if the ORM *field* allows ``None``.  A field is
   considered optional when it is a primary key, has ``null=True``,
   ``auto_now=True``, ``auto_now_add=True``, or a non-sentinel default
   value.  Delegates to :func:`field_is_optional_cached` for cached
   lookups.

Security Constants
------------------

.. py:data:: openviper.serializers.base.MAX_JSON_STRING_BYTES

   Maximum allowed size for a JSON input string (default: 1 MiB).
   ``validate_json_string()`` raises
   :class:`~openviper.exceptions.ValidationError` when this limit is
   exceeded.

.. py:data:: openviper.serializers.base.UNSAFE_FILENAME_CHAR_RE

   Compiled regex matching null bytes, control characters (``\\x00``
   – ``\\x1f``), backslashes, and forward slashes in uploaded
   filenames.  ``persist_files()`` rejects any filename that matches.

.. py:data:: openviper.serializers.base.ALLOWED_URL_SCHEMES

   ``frozenset`` of URL schemes (``""``, ``"http"``, ``"https"``)
   permitted for ``base_url`` in :meth:`Serializer.paginate`.
   Prevents open-redirect attacks via malicious scheme injection.

Structural Protocols
--------------------

The serializers module defines ``@runtime_checkable`` protocols that
describe the minimal interfaces expected from ORM models, managers,
query sets, fields, requests, permissions, and upload values.  These
enable strict static typing without coupling to a concrete ORM
implementation:

.. py:class:: openviper.serializers.base.OrmModelProtocol

   Minimal interface that OpenViper ORM models satisfy.  Requires
   ``_fields``, ``_table_name``, ``id``, and ``__dict__``.

.. py:class:: openviper.serializers.base.OrmManagerProtocol

   Interface for the ``objects`` manager.  Requires ``async create()``,
   ``async get()``, and ``async get_or_none()``.

.. py:class:: openviper.serializers.base.QuerySetProtocol

   Interface for lazy chainable query builders.  Requires ``filter()``,
   ``offset()``, ``limit()``, ``async all()``, ``async count()``, and
   ``async batch()``.

.. py:class:: openviper.serializers.base.OrmFieldProtocol

   Minimal interface for ORM field descriptors.  Requires
   ``primary_key``, ``null``, ``auto_now``, ``auto_now_add``,
   ``default``, ``column_name``, ``name``, ``validate()``, and
   ``has_default()``.

.. py:class:: openviper.serializers.base.RequestProtocol

   Minimal interface for HTTP request objects.  Requires ``method``
   and ``path``.

.. py:class:: openviper.serializers.base.PermissionProtocol

   Interface for permission classes.  Requires
   ``async has_permission(request, serializer) -> bool``.

.. py:class:: openviper.serializers.base.UploadValueProtocol

   Interface for uploaded file values.  Requires ``filename``,
   ``name``, and ``read()``.

Field Type Mapping
------------------

When ``ModelSerializer`` auto-generates fields from an ORM model it maps
field class names to Python types as follows:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - ORM Field
     - Pydantic Type
   * - ``IntegerField``, ``BigIntegerField``, ``AutoField``, ``PositiveIntegerField``
     - ``int``
   * - ``FloatField``
     - ``float``
   * - ``DecimalField``
     - ``Decimal``
   * - ``CharField``, ``TextField``, ``EmailField``, ``SlugField``, ``URLField``, ``IPAddressField``
     - ``str``
   * - ``BooleanField``
     - ``bool``
   * - ``DateTimeField``
     - ``datetime.datetime``
   * - ``DateField``
     - ``datetime.date``
   * - ``TimeField``
     - ``datetime.time``
   * - ``UUIDField``
     - ``uuid.UUID``
   * - ``JSONField``
     - ``Any``
   * - ``ForeignKey``, ``OneToOneField``
     - ``int`` (raw FK id)
   * - ``FileField``, ``ImageField``
     - ``str`` (stored path)

A field is automatically marked optional when the ORM field has
``null=True``, ``auto_now=True``, ``auto_now_add=True``, a default value,
or is the primary key.

Example Usage
-------------

.. seealso::

   Working projects that use serializers:

   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - pydantic-based serializers with validation
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - ``ModelSerializer`` for products, orders, reviews

Manual Serializer
~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.serializers import Serializer, field_validator

    class PostSerializer(Serializer):
        title: str
        body: str
        tags: list[str] = []

        @field_validator("title")
        @classmethod
        def title_not_empty(cls, v: str) -> str:
            if not v.strip():
                raise ValueError("Title cannot be blank.")
            return v.strip()

    # Validate incoming data
    data = PostSerializer.validate({"title": "Hello", "body": "World"})

    async def example():
        # Serialize an ORM instance
        post = await Post.objects.get(id=1)
        out = PostSerializer.from_orm(post).serialize()

Model Serializer
~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.serializers import ModelSerializer
    from myapp.models import Post

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Post
            fields = ["id", "title", "body", "created_at"]
            readonly_fields = ("id", "created_at")

    async def example():
        post = await Post.objects.get(id=1)
        out = PostSerializer.from_orm(post).serialize()
        # {"id": 1, "title": "...", "body": "...", "created_at": "..."}

Exclude Fields
^^^^^^^^^^^^^^

.. code-block:: python

    class PostPublicSerializer(ModelSerializer):
        class Meta:
            model = Post
            exclude = ["internal_notes", "admin_flag"]

write_only and read_only Fields
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    class UserSerializer(ModelSerializer):
        class Meta:
            model = User
            fields = "__all__"
            readonly_fields = ("id", "created_at")
            writeonly_fields = ("password",)  # never appears in serialize()

    user = UserSerializer.validate({"username": "alice", "password": "s3cr3t"})
    out = user.serialize()
    # "password" is absent from out; "id" and "created_at" cannot be set

Cross-Field Validation
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.serializers import Serializer, model_validator

    class PasswordChangeSerializer(Serializer):
        password: str
        confirm_password: str

        @model_validator(mode="after")
        def passwords_match(self) -> "PasswordChangeSerializer":
            if self.password != self.confirm_password:
                raise ValueError("Passwords do not match.")
            return self

Computed Fields
~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.serializers import Serializer, computed_field

    class ProductSerializer(Serializer):
        price: float
        tax_rate: float = 0.2

        @computed_field
        @property
        def price_with_tax(self) -> float:
            return round(self.price * (1 + self.tax_rate), 2)

    out = ProductSerializer(price=100.0).serialize()
    # {"price": 100.0, "tax_rate": 0.2, "price_with_tax": 120.0}

Partial Validation (PATCH)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @router.patch("/posts/{post_id:int}")
    async def patch_post(request: Request, post_id: int) -> JSONResponse:
        post = await Post.objects.get(id=post_id)
        ser = PostSerializer.validate(await request.json(), partial=True)
        # Only update the fields the caller sent
        changes = ser.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(post, key, value)
        await post.save()
        return JSONResponse(PostSerializer.from_orm(post).serialize())

serialize_many - Bulk Serialization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def example():
        posts = await Post.objects.filter(is_published=True).all()

        # From a plain list - no DB call
        data = await PostSerializer.serialize_many(posts)

        # From a QuerySet - streamed in PAGE_SIZE batches (default 25)
        qs = Post.objects.filter(is_published=True).order_by("-created_at")
        data = await PostSerializer.serialize_many(qs)

        # Exclude specific fields
        data = await PostSerializer.serialize_many(posts, exclude={"body"})

Pagination
~~~~~~~~~~

.. code-block:: python

    from openviper.serializers import ModelSerializer
    from openviper.http import JSONResponse, Request
    from myapp.models import Post

    class PostSerializer(ModelSerializer):
        PAGE_SIZE = 20          # override default of 25

        class Meta:
            model = Post
            fields = ["id", "title", "body", "created_at"]

    @router.get("/posts")
    async def list_posts(request: Request) -> JSONResponse:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", PostSerializer.PAGE_SIZE))
        cursor = request.query_params.get("cursor")  # for fast Next/Prev

        qs = Post.objects.filter(is_published=True).order_by("-created_at", "id")

        # Uses asyncio.gather() for concurrent COUNT + fetch (~2x faster)
        paginated = await PostSerializer.paginate(
            qs,
            page=page,
            page_size=page_size,
            cursor=cursor,
            base_url="/posts",
        )
        return JSONResponse(paginated.model_dump())
        # {
        #   "count": 120,
        #   "next": "/posts?cursor=eyJjcmVhdGVkX2F0IjouLi59&page=3&page_size=20",
        #   "previous": "/posts?page=1&page_size=20",
        #   "next_cursor": "eyJjcmVhdGVkX2F0IjouLi4sImlkIjoxMjN9",
        #   "results": [...]
        # }

**Performance tips:**

- COUNT and fetch queries run concurrently (using ``asyncio.gather()``).
- Direct page jumps (e.g., ``?page=1000``) use OFFSET and are O(N) - slower for deep pages.
- Sequential navigation via ``next_cursor`` uses keyset pagination - O(log N), fast at any depth.
- Always include ``id`` as the last ordering field for stable cursor pagination.

**Common mistakes:**

``paginate`` is a **classmethod** that accepts a **QuerySet**, not a list of
already-serialized objects.  These patterns will **not** work:

.. code-block:: python

    # WRONG - from_orm_many returns a list, not a QuerySet
    instances = PostSerializer.from_orm_many(await Post.objects.all())
    result = await PostSerializer.paginate(instances)  # TypeError

    # WRONG - serialize_many returns a list of dicts
    data = await PostSerializer.serialize_many(Post.objects.all())
    result = await PostSerializer.paginate(data)  # TypeError

    # WRONG - awaiting the QuerySet evaluates it to a list
    result = await PostSerializer.paginate(
        await Post.objects.all(),  # list, not QuerySet
        page=1, page_size=20,
    )  # AttributeError: 'list' object has no attribute 'offset'

The correct approach is to pass the **unevaluated QuerySet** directly:

.. code-block:: python

    qs = Post.objects.filter(is_published=True).order_by("-created_at", "id")
    result = await PostSerializer.paginate(qs, page=1, page_size=20)

**ORM-level pagination:**

For more control, paginate at the ORM level before serialization:

.. code-block:: python

    @router.get("/posts")
    async def list_posts(request: Request) -> JSONResponse:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        qs = Post.objects.filter(is_published=True).order_by("-created_at", "id")

        # Paginate at ORM level (also uses asyncio.gather)
        page_obj = await qs.paginate(page_number=page, page_size=page_size)

        # Serialize only the paginated items
        results = await PostSerializer.serialize_many(page_obj.items)

        return JSONResponse({
            "count": page_obj.total_count,
            "page": page_obj.number,
            "page_size": page_obj.page_size,
            "next_cursor": page_obj.next_cursor,
            "results": results,
        })

Performance Optimizations
~~~~~~~~~~~~~~~~~~~~~~~~~

The serializers module includes several performance optimizations that provide
significant speed improvements for production workloads:

**Direct ORM→Dict Mapping (35-40% faster)**

``serialize_many()``, ``serialize_many_json()``, and ``paginate()`` use direct
attribute access instead of double conversion (ORM → Pydantic model → dict).
This eliminates unnecessary validation and model instantiation overhead:

.. code-block:: python

    # Old approach (slow):
    instances = [cls.model_validate(obj) for obj in objs]  # Conversion 1
    results = [inst.model_dump(mode="json") for inst in instances]  # Conversion 2

    # Optimized approach (35-40% faster):
    results = [
        {fname: getattr(obj, fname, None) for fname in cls.model_fields}
        for obj in objs
    ]

**Cached Exclude Field Computation (5-10% reduction)**

The ``get_excluded_fields()`` helper caches write-only field sets to avoid
repeated set construction on every serialization call:

.. code-block:: python

    excl = cls.get_excluded_fields(exclude)  # Cached, returns frozenset

**LRU-Cached File Fields (Memory Safe)**

File field introspection uses ``@lru_cache(maxsize=512)`` instead of unbounded
dict caching, preventing memory leaks in applications with dynamic serializer
creation:

.. code-block:: python

    @classmethod
    @lru_cache(maxsize=512)
    def get_file_fields(cls) -> MappingProxyType:
        # Cached per serializer class with automatic eviction

**Parallel Query Execution (2x faster)**

``paginate()`` uses ``asyncio.gather()`` to run COUNT and data fetch queries
concurrently, doubling baseline performance:

.. code-block:: python

    total, objs = await asyncio.gather(
        qs.count(),      # Query 1
        page_qs.all(),   # Query 2 (runs in parallel)
    )

**Expected Performance Gains**

When combined with :doc:`db query optimizations <db>`, these improvements provide:

- **60-80% faster paginated list endpoints** (COUNT + fetch + serialization)
- **35-40% faster bulk serialization** (``serialize_many`` / ``serialize_many_json``)
- **50% faster file field validation** (cached introspection)
- **Eliminated O(N) allocation overhead** for exclude field computation

For highest performance on large lists, consider using cursor-based pagination
(keyset seeks) instead of OFFSET, and ensure proper database indexes exist for
ordering columns.

ModelSerializer CRUD Helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Post
            fields = "__all__"
            readonly_fields = ("id", "created_at")

    # CREATE
    @router.post("/posts")
    async def create_post(request: Request) -> JSONResponse:
        ser = PostSerializer(data=await request.json())
        ser.validate(raise_exception=True)
        saved = await ser.save()          # calls ser.create() internally
        return JSONResponse(saved, status_code=201)

    # UPDATE (PUT - full replacement)
    @router.put("/posts/{post_id:int}")
    async def update_post(request: Request, post_id: int) -> JSONResponse:
        post = await Post.objects.get(id=post_id)
        ser = PostSerializer.validate(await request.json())
        saved = await ser.save(post)      # calls ser.update(post) internally
        return JSONResponse(saved)

    # UPDATE (PATCH - partial)
    @router.patch("/posts/{post_id:int}")
    async def patch_post(request: Request, post_id: int) -> JSONResponse:
        post = await Post.objects.get(id=post_id)
        ser = PostSerializer.validate(await request.json(), partial=True)
        saved = await ser.save(post)
        return JSONResponse(saved)

Nested Serializers
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    class AuthorSerializer(Serializer):
        id: int
        username: str

    class PostSerializer(Serializer):
        id: int
        title: str
        author: AuthorSerializer   # nested - expects author to be an object
        tags: list[str] = []

    # When building from ORM, use select_related to avoid N+1:
    async def example():
        post = await Post.objects.select_related("author").get(id=1)
        out = PostSerializer.from_orm(post).serialize()
        # {"id": 1, "title": "...", "author": {"id": 5, "username": "alice"}, "tags": []}

Error Handling
~~~~~~~~~~~~~~

:meth:`~Serializer.validate` wraps all Pydantic errors in
:class:`~openviper.exceptions.ValidationError` whose
``validation_errors`` attribute is a list of structured dicts:

.. code-block:: python

    from openviper.exceptions import ValidationError

    try:
        data = PostSerializer.validate({"title": ""})
    except ValidationError as exc:
        print(exc.validation_errors)
        # [{"field": "title", "message": "Title cannot be blank.", "type": "value_error"}]

When a :class:`ModelSerializer` reaches the database, common persistence
failures are converted into the same structured format:

.. code-block:: python

    serializer = PostSerializer(data={"slug": "already-used"})
    serializer.validate(raise_exception=True)
    await serializer.save()
    # duplicate unique values raise:
    # [{"field": "slug", "message": "This value must be unique.", "type": "unique"}]

Malformed JSON is separate from serializer validation: ``request.json()``
returns HTTP ``400`` when the body cannot be parsed at all, while serializers
return HTTP ``422`` when the JSON is valid but the data is invalid.

Using in a View
~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.routing.router import Router
    from openviper.http.request import Request
    from openviper.http.response import JSONResponse
    from openviper.exceptions import ValidationError

    router = Router()

    @router.post("/posts")
    async def create_post(request: Request) -> JSONResponse:
        serializer = PostSerializer(data=await request.json())
        serializer.validate(raise_exception=True)
        saved = await serializer.save()
        return JSONResponse(saved, status_code=201)
