.. _db:

Database & ORM
==============

The ``openviper.db`` package provides an async ORM built on top of
SQLAlchemy Core.  Define models as Python classes, query them with a
chainable ``QuerySet`` API, and manage schema changes with the built-in
migration system — all with ``async``/``await``.

Overview
--------

Models inherit from :class:`~openviper.db.models.Model` and declare fields
as class-level descriptors.  Every database operation is coroutine-based
and uses a per-request connection pool managed by SQLAlchemy's async engine.

A ``permissions`` layer enforces row-level access control by default;
use ``ignore_permissions=True`` or the :func:`~openviper.db.executor.bypass_permissions`
context manager for trusted internal code paths.

Table naming is automatic: a model in ``apps/blog/models.py`` named ``Post``
gets table name ``blog_post``.  Override with ``Meta.table_name``.

Key Classes & Functions
-----------------------

``openviper.db.models``
~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: Model

   Base class for all ORM models.  Subclass and set ``class Meta`` to
   configure the table name and other options.

   Every model gets a default auto-incrementing integer ``id`` primary key
   unless you declare your own.

   **Meta options:**

   - ``table_name`` — explicit table name (auto-generated otherwise).
   - ``abstract = True`` — mark as abstract; no table is created; useful
     for shared-field mixins.

   .. py:attribute:: objects

      :class:`Manager` instance — the primary entry point for queries.

   .. py:attribute:: pk

      Alias for ``id``.  Always returns the primary key value.

   .. py:attribute:: has_changed

      ``True`` if any field value differs from the last saved state.

   .. py:method:: save(ignore_permissions=False) -> Awaitable[None]

      Persist (INSERT or UPDATE) the instance.  Runs the full lifecycle
      hook chain — see `Lifecycle Hooks`_ below.

   .. py:method:: delete(ignore_permissions=False) -> Awaitable[None]

      Delete this instance.  Fires ``on_delete`` → DELETE → ``after_delete``.

   .. py:method:: refresh_from_db() -> Awaitable[None]

      Re-load all field values from the database in place.

   .. py:method:: _to_dict() -> dict

      Serialize the instance to a plain Python dict.

.. py:class:: AbstractModel

   Abstract base — subclasses inherit its fields but share no table.  Use
   for timestamp mixins or other common patterns.

.. py:class:: Manager

   Attached to every non-abstract model as ``Model.objects``.  Provides
   factory methods that all return :class:`QuerySet` (lazy) or awaitables
   (terminal).

   **Factory methods (return QuerySet):**
   ``all()``, ``filter()``, ``exclude()``, ``order_by()``, ``only()``,
   ``defer()``, ``distinct()``, ``annotate()``, ``select_related()``,
   ``prefetch_related()``

   **Awaitable shortcuts:**
   ``get(**kwargs)``, ``get_or_none(**kwargs)``, ``create(**kwargs)``,
   ``get_or_create(defaults, **kwargs)``

   **Bulk operations:**
   ``bulk_create(objs, batch_size=None)``,
   ``bulk_update(objs, fields, batch_size=None)``

   **Iteration helpers:**
   ``iterator(chunk_size=2000)``, ``batch(size=100)``, ``id_batch(size=100)``

.. py:class:: QuerySet

   Lazy, chainable query builder.  All filtering/ordering/slicing methods
   return a **new** ``QuerySet`` (non-mutating).  Results are fetched only
   when a *terminal* method is awaited.

   A ``QuerySet`` is also directly awaitable: ``await qs`` is equivalent to
   ``await qs.all()``.

   .. warning:: **Default row limit**

      ``filter()``, ``all()``, and other terminal methods that return a list
      cap results at **1 000 rows** by default.  This is a safety guard
      against accidentally loading entire large tables into memory.

      Override this per-query with :meth:`limit`, project-wide via
      ``MAX_QUERY_ROWS`` in your settings (hard ceiling: 100 000), or bypass
      it entirely with :meth:`iterator` / :meth:`batch` which stream through
      all matching rows using keyset pagination.

      .. code-block:: python

         # ── default: max 1 000 rows ─────────────────────────────────
         async def example():
             posts = await Post.objects.all()           # up to 1 000

             # ── explicit limit ────────────────────────────────────────
             posts = await Post.objects.limit(50).all() # exactly 50

         # ── settings override ────────────────────────────────────────
         # settings.py
         MAX_QUERY_ROWS = 5000  # raise per-project cap (max 100 000)

         # ── no limit: stream all rows ────────────────────────────────
         async def example():
             async for post in Post.objects.filter(published=True).iterator():
                 await process(post)   # keyset-paginated, unbounded

             # ── batch processing ──────────────────────────────────────
             async for batch in Post.objects.all().batch(size=200):
                 await send_emails(batch)  # list of ≤200 instances

   .. tip:: **Use a serializer for automatic pagination**

      :class:`~openviper.serializers.ModelSerializer` provides three
      class-methods that work directly on a ``QuerySet`` and handle the row
      limit / pagination for you:

      .. code-block:: python

         from openviper.serializers import ModelSerializer
         from myapp.models import Post

         class PostSerializer(ModelSerializer):
             class Meta:
                 model = Post
                 fields = ["id", "title", "created_at"]
             # PAGE_SIZE = 25  ← default; override per-serializer

         async def list_posts(request):
             # ── serialize_many: all rows, batched internally ──────────
             # Bypasses the 1 000-row cap; fetches in PAGE_SIZE chunks.
             data = await PostSerializer.serialize_many(
                 Post.objects.filter(published=True).order_by("-created_at")
             )
             # returns: list[dict]

             # ── paginate: one page with total count + next/prev URLs ──
             page   = int(request.query_params.get("page", 1))
             result = await PostSerializer.paginate(
                 Post.objects.filter(published=True).order_by("-created_at"),
                 page=page,
                 page_size=20,
                 base_url="/api/posts/",
             )
             # result.count     → total matching rows
             # result.results   → list[dict] for this page
             # result.next      → "/api/posts/?page=3&page_size=20" or None
             # result.previous  → "/api/posts/?page=1&page_size=20" or None
             return JSONResponse(result.model_dump())

         async def list_posts_json(request):
             # ── serialize_many_json: same as serialize_many but returns bytes
             body = await PostSerializer.serialize_many_json(
                 Post.objects.filter(published=True)
             )
             return Response(body, content_type="application/json")

   **Filtering:**

   .. py:method:: filter(*q_objects, **kwargs) -> QuerySet

      Add ``WHERE`` conditions.  Accepts :class:`Q` objects or
      ``keyword=value`` pairs with lookup suffixes:
      ``__contains``, ``__icontains``, ``__startswith``, ``__endswith``,
      ``__gt``, ``__gte``, ``__lt``, ``__lte``, ``__in``, ``__isnull``,
      ``__exact``, ``__range``.

      FK traversal is supported: ``author__username="alice"`` performs a
      JOIN on the ``author`` FK field.

   .. py:method:: exclude(*q_objects, **kwargs) -> QuerySet

      Exclude rows matching the given conditions (negated ``filter``).

   **Ordering & slicing:**

   .. py:method:: order_by(*fields) -> QuerySet

      Order results.  Prefix with ``-`` for descending (``"-created_at"``).

   .. py:method:: limit(n) -> QuerySet

      Limit the number of rows returned (SQL ``LIMIT``).

      .. code-block:: python

         # Get first 10 posts
         posts = await Post.objects.order_by("-created_at").limit(10).all()

         # Combine with offset for manual pagination
         page_size = 20
         page = 3
         offset = (page - 1) * page_size
         posts = await Post.objects.limit(page_size).offset(offset).all()

   .. py:method:: offset(n) -> QuerySet

      Skip the first *n* rows (SQL ``OFFSET``).

      .. warning::
         ``OFFSET`` performance degrades linearly with the offset value.
         For example, ``OFFSET 1000000`` requires scanning 1M rows before
         returning results. For deep pagination, prefer keyset (cursor)
         pagination using :meth:`paginate` with a cursor, or use
         :meth:`iterator` for streaming large datasets.

      .. code-block:: python

         # Manual pagination with offset (simple but slow for deep pages)
         page_size = 20
         page_number = 2
         offset = (page_number - 1) * page_size
         posts = await Post.objects.order_by("id").limit(page_size).offset(offset).all()

         # Better: Use paginate() which runs COUNT + fetch concurrently
         page = await Post.objects.order_by("id").paginate(page_number=2, page_size=20)

   .. py:method:: distinct() -> QuerySet

      Add ``SELECT DISTINCT``.

   **Column selection:**

   .. py:method:: only(*fields) -> QuerySet

      Restrict the ``SELECT`` to the given field names.  The primary key is
      always included.  All other fields will be ``None`` on instances.

   .. py:method:: defer(*fields) -> QuerySet

      Exclude the given fields from the ``SELECT``.  Mutually exclusive
      with ``only()`` — the last call wins.

   **Relationships:**

   .. py:method:: select_related(*fields) -> QuerySet

      Perform a SQL ``JOIN`` to load the related objects in the same query
      (one query total).  Best for single FK objects where you always need
      the related data.

   .. py:method:: prefetch_related(*fields) -> QuerySet

      Issue a separate ``id__in`` query per field and attach results to
      instances in Python (two queries total for one FK).  Best for
      large result sets or when the related data is optional.

   **Annotations:**

   .. py:method:: annotate(**kwargs) -> QuerySet

      Add computed columns using :class:`F` expressions or aggregate
      functions (:class:`Count`, :class:`Sum`, :class:`Avg`,
      :class:`Max`, :class:`Min`).  Values are accessible as attributes on
      returned instances.

   **Terminal methods:**

   .. py:method:: all() -> Awaitable[list[Model]]

      Execute and return all matching rows.

   .. py:method:: get() -> Awaitable[Model]

      Return exactly one object.  Raises
      :class:`~openviper.exceptions.DoesNotExist` or
      :class:`~openviper.exceptions.MultipleObjectsReturned`.

   .. py:method:: first() -> Awaitable[Model | None]

      Return the first matching row, or ``None``.

   .. py:method:: last() -> Awaitable[Model | None]

      Return the last matching row (reverses ordering or uses ``-id``).

   .. py:method:: count() -> Awaitable[int]

      Return the row count for the current query.

   .. py:method:: exists() -> Awaitable[bool]

      Return ``True`` if at least one row matches.

   .. py:method:: delete() -> Awaitable[int]

      Bulk-delete matching rows.  Returns the number of deleted rows.

   .. py:method:: update(**kwargs) -> Awaitable[int]

      Bulk-update matching rows.  Accepts :class:`F` expressions for
      atomic arithmetic updates.  Returns the number of affected rows.

   .. py:method:: values(*fields) -> Awaitable[list[dict]]

      Return each row as a plain ``dict``.  If *fields* are given only
      those columns are included.

   .. py:method:: values_list(*fields, flat=False) -> Awaitable[list[tuple] | list]

      Return rows as tuples.  Use ``flat=True`` with exactly one field to
      get a flat list of scalar values.

   .. py:method:: aggregate(**kwargs) -> Awaitable[dict]

      Execute aggregate functions and return a single result dict.  Values
      must be aggregate instances (``Count``, ``Sum``, etc.).

   .. py:method:: explain() -> Awaitable[str]

      Return the database ``EXPLAIN`` plan for the current query.

   .. py:method:: raw_sql() -> str

      Return the raw SQL query string with literal parameter values.
      Non-async method useful for debugging and logging.

      .. code-block:: python

         qs = Post.objects.filter(is_published=True).order_by("-created_at").limit(10)
         print(qs.raw_sql())
         # SELECT posts.* FROM posts WHERE is_published = 1
         # ORDER BY created_at DESC LIMIT 10

   .. py:method:: paginate(page_number=1, page_size=25, cursor=None) -> Awaitable[Page]

      Paginate the queryset efficiently using concurrent COUNT and data fetch.
      Returns a :class:`Page` object containing items, total count, and cursor.

      Uses ``asyncio.gather()`` to run the count and fetch queries in parallel
      for ~2x faster performance. Supports both OFFSET-based pagination (via
      ``page_number``) and keyset cursor pagination for sequential navigation.

      .. code-block:: python

         # Basic pagination
         page = await Post.objects.filter(is_published=True).paginate(
             page_number=2,
             page_size=20
         )
         # page.items         → list[Post] (20 items)
         # page.total_count   → total matching rows
         # page.number        → current page (2)
         # page.page_size     → items per page (20)
         # page.next_cursor   → cursor for next page (or None)

         # With cursor for fast sequential navigation
         page = await Post.objects.order_by("created_at", "id").paginate(
             page_number=1,
             page_size=20,
             cursor=request.query_params.get("cursor")
         )

      **Performance:** COUNT and data fetch execute concurrently. Deep pages
      using OFFSET can be slow (O(N)); prefer cursors for Next/Prev navigation.

   **Streaming / large datasets:**

   .. py:method:: iterator(chunk_size=2000) -> AsyncGenerator[Model, None]

      Yield model instances one at a time using keyset (``id > last_id``)
      pagination.  Safe for very large tables — **not subject to the default
      1 000-row cap**.

   .. py:method:: batch(size=100) -> AsyncGenerator[list[Model], None]

      Yield successive lists of at most *size* model instances using
      ``OFFSET``-based pagination.  **Not subject to the default 1 000-row
      cap.**

   .. py:method:: id_batch(size=100) -> AsyncGenerator[list[Model], None]

      Like :meth:`batch` but uses keyset pagination for stability during
      concurrent writes.  **Not subject to the default 1 000-row cap.**

.. py:class:: F(name)

   Reference a model field for database-side operations.  Supports
   arithmetic: ``+``, ``-``, ``*``, ``/``.

.. py:class:: Q(**kwargs)

   Encapsulate filter conditions supporting ``|`` (OR), ``&`` (AND), and
   ``~`` (NOT).

.. py:class:: Page

   Pagination result container returned by :meth:`QuerySet.paginate`.

   .. py:attribute:: items
      :type: list[Model]

      The list of model instances for this page.

   .. py:attribute:: total_count
      :type: int

      Total number of matching rows across all pages.

   .. py:attribute:: number
      :type: int

      Current page number (1-indexed).

   .. py:attribute:: page_size
      :type: int

      Maximum items per page.

   .. py:attribute:: next_cursor
      :type: str | None

      Base64-encoded cursor for the next page (for keyset pagination).
      ``None`` if this is the last page.

**Aggregate classes:**

``Count(field, distinct=False)``, ``Sum(field)``, ``Avg(field)``,
``Max(field)``, ``Min(field)``

``openviper.db.fields``
~~~~~~~~~~~~~~~~~~~~~~~

All fields accept a common set of base arguments: ``primary_key``,
``null``, ``blank``, ``unique``, ``db_index``, ``default``, ``db_column``,
``choices``, ``help_text``.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Field Class
     - Description
   * - ``AutoField``
     - Auto-incrementing integer primary key.  Added automatically.
   * - ``IntegerField``
     - 32-bit integer (−2 147 483 648 – 2 147 483 647).
   * - ``BigIntegerField``
     - 64-bit integer.
   * - ``FloatField(allow_inf=False, allow_nan=False)``
     - Floating-point number.
   * - ``DecimalField(max_digits=10, decimal_places=2)``
     - Fixed-precision decimal stored as ``NUMERIC``.
   * - ``CharField(max_length=255)``
     - Variable-length string stored as ``VARCHAR``.
   * - ``TextField``
     - Unbounded text stored as ``TEXT``.
   * - ``EmailField``
     - ``CharField(max_length=254)`` with RFC 5322 e-mail validation.
   * - ``URLField``
     - ``CharField`` with URL validation.
   * - ``SlugField``
     - ``CharField`` restricted to ``[-a-zA-Z0-9_]``.
   * - ``BooleanField``
     - Boolean (stored as 0/1).
   * - ``DateTimeField(auto_now=False, auto_now_add=False)``
     - Timezone-aware datetime.  ``auto_now_add`` sets on INSERT;
       ``auto_now`` updates on every save.
   * - ``DateField``
     - Date-only column.
   * - ``TimeField``
     - Time-only column.
   * - ``UUIDField(auto=False)``
     - UUID stored as text.  ``auto=True`` generates ``uuid.uuid4()`` default.
   * - ``JSONField(max_size=None)``
     - Arbitrary JSON stored as ``JSON``/``TEXT``.  Max size defaults to 1 MB.
   * - ``BinaryField``
     - Raw binary data (``BYTEA`` / ``BLOB``).
   * - ``FileField(upload_to="uploads/", max_size=None)``
     - File upload; stores path relative to ``MEDIA_ROOT``.
   * - ``ImageField``
     - ``FileField`` with image content-type validation.
   * - ``ForeignKey(to, on_delete="CASCADE", related_name=None)``
     - Many-to-one relationship.  FK column is ``{name}_id``.
       ``on_delete``: ``"CASCADE"``, ``"PROTECT"``, ``"SET_NULL"``,
       ``"SET_DEFAULT"``.
   * - ``OneToOneField(to, **kwargs)``
     - One-to-one relationship (unique FK).
   * - ``ManyToManyField(to, through=None, related_name=None)``
     - Many-to-many via a junction table (no direct column).

``openviper.db.connection``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: init_db() -> Awaitable[None]

   Initialize the SQLAlchemy async engine.  Called automatically on startup.

.. py:function:: close_db() -> Awaitable[None]

   Dispose of the engine and close all connections.

.. py:function:: get_connection() -> AsyncContextManager[AsyncConnection]

   Async context manager that yields a live database connection.

Lifecycle Hooks
---------------

Override any of the following ``async`` methods on a ``Model`` subclass to
hook into the persistence lifecycle.  All default to no-ops.

**Create flow** (``pk is None``)::

    before_validate → validate → before_insert → before_save
    → INSERT → after_insert → on_change

**Update flow** (``pk`` set)::

    before_validate → validate → before_save
    → UPDATE → on_update → on_change  (only when data actually changed)

**Delete flow**::

    on_delete → DELETE → after_delete

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Hook
     - When called
   * - ``async before_validate(self)``
     - Before field validation, on both create and update.
   * - ``async validate(self)``
     - Validates all fields.  Override to add custom business rules —
       call ``await super().validate()`` to keep built-in checks.
   * - ``async before_insert(self)``
     - Create only, after validation, before the INSERT.
   * - ``async before_save(self)``
     - Both create and update, immediately before the DB write.
   * - ``async after_insert(self)``
     - Create only, after the INSERT succeeds.
   * - ``async on_update(self)``
     - Update only, after the UPDATE succeeds.
   * - ``async on_delete(self)``
     - Before the DELETE.  Raise to abort.
   * - ``async after_delete(self)``
     - After a successful DELETE.
   * - ``async on_change(self, previous_state)``
     - After create or update when field values changed.
       *previous_state* is ``{field: old_value}`` for changed fields.

Model Events (Signals)
----------------------

Beyond lifecycle hooks, model events allow you to attach handlers
*outside* the model class using ``@model_event.trigger()``:

.. code-block:: python

    from openviper.db.events import model_event

    @model_event.trigger("myapp.models.Post.after_insert")
    async def on_post_created(post, event):
        print(f"New post: {post.title}")

Example Usage
-------------

.. seealso::

   Working projects that use the ORM:

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ — simple model (``CharField``, ``BooleanField``, ``DateTimeField``)
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — ``UUIDField`` PK, ``DecimalField``, ``ImageField``, ``after_insert`` lifecycle hook
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — ``ForeignKey``, ``JSONField``, ``ImageField``, custom ``BaseUser``
   - `examples/fx/ <https://github.com/mymi14s/openviper/tree/master/examples/fx>`_ — root-layout project with models and migrations

Defining Models
~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.models import Model, AbstractModel
    from openviper.db import fields

    class TimestampMixin(AbstractModel):
        """Shared timestamp fields — no table created."""
        created_at = fields.DateTimeField(auto_now_add=True)
        updated_at = fields.DateTimeField(auto_now=True)

        class Meta:
            abstract = True

    class Author(TimestampMixin):
        class Meta:
            table_name = "authors"

        name = fields.CharField(max_length=200)
        email = fields.EmailField(unique=True)

    class Post(TimestampMixin):
        class Meta:
            table_name = "posts"

        title = fields.CharField(max_length=255)
        body = fields.TextField()
        author = fields.ForeignKey(Author, on_delete="CASCADE")
        is_published = fields.BooleanField(default=False)
        views = fields.IntegerField(default=0)

        async def before_save(self) -> None:
            self.title = self.title.strip()

        async def validate(self) -> None:
            await super().validate()
            if not self.title:
                raise ValueError("Title is required")

Querying
~~~~~~~~

.. code-block:: python

    from openviper.exceptions import DoesNotExist

    async def example():
        # Fetch all published posts ordered by newest first
        posts = await Post.objects.filter(is_published=True).order_by("-created_at").all()

        # Directly await a QuerySet
        posts = await Post.objects.filter(is_published=True)

        # Get a single post or raise DoesNotExist
        try:
            post = await Post.objects.get(id=42)
        except DoesNotExist:
            ...

        # Get or None
        post = await Post.objects.get_or_none(id=42)

        # Create
        author = await Author.objects.create(name="Alice", email="alice@example.com")

        # get_or_create
        post, created = await Post.objects.get_or_create(
            defaults={"body": "..."},
            title="Hello World",
        )

        # Update all matching rows
        updated = await Post.objects.filter(author=author).update(is_published=True)

        # Count & exists
        n = await Post.objects.filter(is_published=True).count()
        exists = await Post.objects.filter(title__contains="OpenViper").exists()

        # First and last
        first_post = await Post.objects.order_by("created_at").first()
        latest_post = await Post.objects.last()  # uses -id by default

        # only / defer
        titles = await Post.objects.only("id", "title").all()
        light = await Post.objects.defer("body").all()

        # distinct
        authors = await Post.objects.distinct().values("author_id")

        # values / values_list
        rows = await Post.objects.filter(is_published=True).values("id", "title")
        # [{"id": 1, "title": "Hello"}, ...]

        ids = await Post.objects.values_list("id", flat=True)
        # [1, 2, 3, ...]

        pairs = await Post.objects.values_list("id", "title")
        # [(1, "Hello"), (2, "World"), ...]

F() Expressions
~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.models import F

    async def example():
        # Atomic increment without a Python round-trip
        await Post.objects.filter(pk=1).update(views=F("views") + 1)

        # Multi-field arithmetic
        await Post.objects.filter(pk=1).update(score=F("likes") * 2 - F("dislikes"))

        # Filter where one column > another
        await Post.objects.filter(views__gte=F("min_views")).all()

Q() Objects — Complex Filters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.models import Q

    async def example():
        # OR
        posts = await Post.objects.filter(
            Q(is_published=True) | Q(is_featured=True)
        ).all()

        # NOT
        posts = await Post.objects.filter(~Q(status="draft")).all()

        # AND via & operator
        posts = await Post.objects.filter(
            Q(is_published=True) & Q(views__gte=100)
        ).all()

        # Compound: (title contains 'python' OR views >= 1000) AND published
        posts = await Post.objects.filter(
            Q(title__icontains="python") | Q(views__gte=1000),
            is_published=True,
        ).all()

Aggregate Functions
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.models import Count, Sum, Avg, Max, Min

    async def example():
        result = await Post.objects.filter(is_published=True).aggregate(
            total=Count("id"),
            total_views=Sum("views"),
            avg_views=Avg("views"),
            max_views=Max("views"),
            min_views=Min("views"),
        )
        # {"total": 42, "total_views": 9820, "avg_views": 233.8, ...}

annotate
~~~~~~~~

.. code-block:: python

    from openviper.db.models import Count, F

    async def example():
        posts = await (
            Post.objects
            .annotate(double_views=F("views") * 2, like_count=Count("likes"))
            .filter(is_published=True)
            .all()
        )
        for post in posts:
            print(post.double_views, post.like_count)

select_related vs prefetch_related
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def example():
        # select_related — one SQL JOIN, good for single FK always needed
        posts = await Post.objects.select_related("author").all()
        for post in posts:
            print(post.author.name)   # no extra DB query

        # prefetch_related — separate id__in query, good for large sets
        posts = await Post.objects.prefetch_related("author").all()
        for post in posts:
            print(post.author.name)   # cached from batch fetch

        # Lazy FK access (when neither is used) — await to load
        post = await Post.objects.get(id=1)
        author = await post.author   # issues SELECT on first access

bulk_create and bulk_update
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def example():
        # bulk_create — INSERT all in a single statement
        posts = [Post(title=f"Post {i}", body="...") for i in range(100)]
        await Post.objects.bulk_create(posts)

        # bulk_update — UPDATE in batches
        published_posts = await Post.objects.filter(is_published=False).all()
        for post in published_posts:
            post.is_published = True
        await Post.objects.bulk_update(published_posts, fields=["is_published"])

Large Dataset Iteration
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def example():
        # iterator — keyset pagination, one instance at a time
        async for post in Post.objects.filter(is_published=True).iterator(chunk_size=500):
            await process(post)

        # batch — OFFSET pagination, groups of instances
        async for batch in Post.objects.filter(is_published=True).batch(size=200):
            await index_search(batch)

        # id_batch — keyset pagination, groups of instances (stable during writes)
        async for batch in Post.objects.filter(is_published=True).id_batch(size=500):
            await process_batch(batch)

Transactions
~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.executor import _begin

    async def example():
        # Use _begin() for an explicit transaction block
        async with _begin() as conn:
            await conn.execute(...)

Bypassing Permissions
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.core.context import ignore_permissions_ctx

    async def example():
        token = ignore_permissions_ctx.set(True)
        try:
            sensitive = await SensitiveModel.objects.all(ignore_permissions=True)
        finally:
            ignore_permissions_ctx.reset(token)

        # Or pass flag directly:
        all_users = await User.objects.filter(ignore_permissions=True).all()

Migrations
----------

Run ``openviper viperctl makemigrations .`` to auto-detect schema changes,
then ``openviper viperctl migrate .`` to apply them.

Supported migration operations:

- ``CreateTable`` — create a new table.
- ``AddColumn`` — add a new column to an existing table.
- ``RemoveColumn`` — drop a column (soft-removed first to protect data).
- ``RenameColumn`` — rename a column.
- ``AlterColumn`` — change column type or constraints.

Soft-removed columns are tracked so that model validation skips them until
a subsequent migration drops them entirely.
