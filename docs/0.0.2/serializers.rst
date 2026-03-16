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
fields and serializer fields — just point ``Meta.model`` at your model class.

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
   * - ``read_only_fields``
     - Class variable
     - Also set via ``Meta.read_only_fields``

Key Classes & Functions
-----------------------

.. py:class:: openviper.serializers.Serializer

   Base serializer backed by Pydantic v2.  Declare fields as annotated
   class attributes exactly as you would in a ``BaseModel``.

   **Class variables** (set at class level, not instance level):

   .. py:attribute:: read_only_fields
      :type: tuple[str, ...]

      Fields included in serialized output but stripped before
      ``create()`` / ``update()`` writes.  Defaults to ``()``.

   .. py:attribute:: write_only_fields
      :type: tuple[str, ...]

      Fields accepted on input but excluded from ``serialize()`` output
      (e.g. passwords).  Defaults to ``()``.

   .. py:attribute:: PAGE_SIZE
      :type: int

      Batch size used by :meth:`serialize_many` when the input is a
      ``QuerySet``.  Defaults to ``25``.

   **Parsing / deserialization:**

   .. py:classmethod:: validate(data, *, partial=False) -> Self

      Parse and validate *data* (dict, ORM object, or mapping).  Raises
      :class:`~openviper.exceptions.ValidationError` with structured error
      details on failure.

      When ``partial=True`` every field becomes optional, which is ideal
      for ``PATCH`` endpoints.  The returned instance tracks which fields
      were supplied via ``model_fields_set``; call
      ``model_dump(exclude_unset=True)`` to get only the changed keys.

   .. py:classmethod:: validate_json_string(json_str) -> Self

      Parse a raw JSON string directly (bypasses the ``body()`` call).

   .. py:classmethod:: from_orm(obj) -> Self

      Build a serializer instance from an ORM model instance (or any
      object with the right attributes).

   .. py:classmethod:: from_orm_many(objs) -> list[Self]

      Build a list of serializer instances from a list of ORM objects.

   **Serialization:**

   .. py:method:: serialize(*, exclude=None) -> dict[str, Any]

      Return a JSON-safe ``dict``.  ``write_only_fields`` are automatically
      excluded.  Pass an additional ``exclude`` set to drop more fields.

   .. py:method:: serialize_json(*, exclude=None) -> bytes

      Return JSON bytes via pydantic-core's Rust encoder (fast path).

   .. py:classmethod:: serialize_many(objs, *, exclude=None) -> Awaitable[list[dict]]

      Serialize a list **or QuerySet** of ORM objects to a list of dicts.

      When *objs* is a ``QuerySet`` (detected via ``hasattr(objs, "batch")``),
      objects are fetched in ``PAGE_SIZE``-sized batches to avoid loading
      the entire result set into memory.  Plain lists are handled with a
      simple comprehension (no DB calls).

   .. py:classmethod:: serialize_many_json(objs, *, exclude=None) -> Awaitable[bytes]

      Like :meth:`serialize_many` but returns a JSON bytes array.  Also
      uses ``PAGE_SIZE``-sized batches for QuerySets.

   .. py:classmethod:: paginate(qs, *, page=1, page_size=None, base_url="", exclude=None) -> Awaitable[PaginatedSerializer]

      Return a :class:`PaginatedSerializer` envelope for a single page of
      *qs*.

      - *qs* must support ``.count()``, ``.offset()``, ``.limit()``, and ``.all()``.
      - *page* is 1-based.
      - *page_size* defaults to ``cls.PAGE_SIZE``.
      - When *base_url* is given, ``next`` / ``previous`` URL strings are
        built as ``{base_url}?page=N&page_size=M``.

.. py:class:: openviper.serializers.PaginatedSerializer

   Returned by :meth:`Serializer.paginate`.

   Fields:

   - ``count`` — total number of matching objects.
   - ``next`` — URL for the next page, or ``None``.
   - ``previous`` — URL for the previous page, or ``None``.
   - ``results`` — list of serialized dicts for the current page.

.. py:class:: openviper.serializers.ModelSerializer

   Extends :class:`Serializer` with automatic field generation from an ORM
   model.  Requires a nested ``Meta`` class.

   **Meta attributes:**

   - ``model`` — the ORM model class (required).
   - ``fields`` — ``"__all__"`` or a list of field names to include.
   - ``exclude`` — list of field names to exclude (alternative to ``fields``).
   - ``read_only_fields`` — tuple of field names that are output-only.
   - ``write_only_fields`` — tuple of field names that are input-only.
   - ``extra_kwargs`` — dict of ``{field_name: {"required": False, ...}}``
     overrides applied after field auto-generation.

   **CRUD helpers** (only on ``ModelSerializer``):

   .. py:method:: create() -> Awaitable[Model]

      Persist a new model instance from the validated data.  Read-only
      fields and the PK are stripped before the INSERT.  Returns the saved
      model instance.

   .. py:method:: update(instance) -> Awaitable[Model]

      Apply validated data to an existing *instance* and save it.  Only
      fields present in ``model_fields_set`` (i.e. fields the caller
      explicitly provided) are written — safe for ``PATCH`` semantics.

   .. py:method:: save(instance=None) -> Awaitable[dict]

      Smart create-or-update.  If *instance* is provided, update it.  If
      the validated data contains a non-``None`` PK, fetch the existing
      record and update it.  Otherwise create a new record.  Returns the
      serialized dict of the persisted object.

.. py:function:: openviper.serializers.field_validator(field_name, *, mode="before")

   Re-export of ``pydantic.field_validator``.  Attach to a serializer method
   to add per-field validation logic.

.. py:function:: openviper.serializers.model_validator(*, mode="after")

   Re-export of ``pydantic.model_validator``.  Attach to a serializer method
   for cross-field validation.

.. py:function:: openviper.serializers.computed_field

   Re-export of ``pydantic.computed_field``.  Decorate a property to include
   computed values in ``serialize()`` output.

Field Type Mapping
------------------

When ``ModelSerializer`` auto-generates fields from an ORM model it maps
field class names to Python types as follows:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - ORM Field
     - Pydantic Type
   * - ``IntegerField``, ``BigIntegerField``, ``AutoField``
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

   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — pydantic-based serializers with validation
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — ``ModelSerializer`` for products, orders, reviews

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
            read_only_fields = ("id", "created_at")

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
            read_only_fields = ("id", "created_at")
            write_only_fields = ("password",)  # never appears in serialize()

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

serialize_many — Bulk Serialization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def example():
        posts = await Post.objects.filter(is_published=True).all()

        # From a plain list — no DB call
        data = await PostSerializer.serialize_many(posts)

        # From a QuerySet — streamed in PAGE_SIZE batches (default 25)
        qs = Post.objects.filter(is_published=True).order_by("-created_at")
        data = await PostSerializer.serialize_many(qs)

        # Exclude specific fields
        data = await PostSerializer.serialize_many(posts, exclude={"body"})

Pagination
~~~~~~~~~~

.. code-block:: python

    from openviper.serializers import ModelSerializer
    from myapp.models import Post

    class PostSerializer(ModelSerializer):
        PAGE_SIZE = 20          # override default of 25

        class Meta:
            model = Post
            fields = ["id", "title", "created_at"]

    @router.get("/posts")
    async def list_posts(request: Request) -> JSONResponse:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", PostSerializer.PAGE_SIZE))
        qs = Post.objects.filter(is_published=True).order_by("-created_at")

        paginated = await PostSerializer.paginate(
            qs,
            page=page,
            page_size=page_size,
            base_url="/posts",
        )
        return JSONResponse(paginated.model_dump())
        # {
        #   "count": 120,
        #   "next": "/posts?page=3&page_size=20",
        #   "previous": "/posts?page=1&page_size=20",
        #   "results": [...]
        # }

ModelSerializer CRUD Helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    class PostSerializer(ModelSerializer):
        class Meta:
            model = Post
            fields = "__all__"
            read_only_fields = ("id", "created_at")

    # CREATE
    @router.post("/posts")
    async def create_post(request: Request) -> JSONResponse:
        ser = PostSerializer.validate(await request.json())
        saved = await ser.save()          # calls ser.create() internally
        return JSONResponse(saved, status_code=201)

    # UPDATE (PUT — full replacement)
    @router.put("/posts/{post_id:int}")
    async def update_post(request: Request, post_id: int) -> JSONResponse:
        post = await Post.objects.get(id=post_id)
        ser = PostSerializer.validate(await request.json())
        saved = await ser.save(post)      # calls ser.update(post) internally
        return JSONResponse(saved)

    # UPDATE (PATCH — partial)
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
        author: AuthorSerializer   # nested — expects author to be an object
        tags: list[str] = []

    # When building from ORM, use select_related to avoid N+1:
    async def example():
        post = await Post.objects.select_related("author").get(id=1)
        out = PostSerializer.from_orm(post).serialize()
        # {"id": 1, "title": "...", "author": {"id": 5, "username": "alice"}, "tags": []}

Error Handling
~~~~~~~~~~~~~~

:meth:`~Serializer.validate` wraps all Pydantic errors in
:class:`~openviper.exceptions.ValidationError` whose ``errors`` attribute
is a list of structured dicts:

.. code-block:: python

    from openviper.exceptions import ValidationError

    try:
        data = PostSerializer.validate({"title": ""})
    except ValidationError as exc:
        print(exc.errors)
        # [{"field": "title", "message": "Title cannot be blank.", "type": "value_error"}]

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
        try:
            data = PostSerializer.validate(await request.json())
        except ValidationError as exc:
            return JSONResponse({"errors": exc.errors}, status_code=422)
        post = await Post.objects.create(**data.model_dump())
        return JSONResponse(post._to_dict(), status_code=201)
