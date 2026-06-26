.. _db:

Database & ORM
==============

The ``openviper.db`` package provides an async ORM built on top of
SQLAlchemy Core.  Define models as Python classes, query them with a
chainable ``QuerySet`` API, and manage schema changes with the
built-in JSON schema synchronization system - all with ``async``/``await``.

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

   - ``table_name`` - explicit table name (auto-generated otherwise).
   - ``abstract = True`` - mark as abstract; no table is created; useful
     for shared-field mixins.
   - ``proxy = True`` - proxy model; shares the parent's table, no new
     table is created.
   - ``managed = False`` - OpenViper will not create or manage this table;
     useful for views or externally-managed tables.
   - ``read_only = True`` - all write operations raise
     :class:`~openviper.db.exceptions.DatabaseReadOnlyError`.
   - ``single = True`` - singleton model; only one instance is allowed.
     See :doc:`single_models`.
   - ``cache_ttl = N`` - cache query results for *N* seconds using the
     project cache backend (``0`` disables caching).
   - ``verbose_name`` - human-readable singular name (defaults to the
     class name).
   - ``verbose_name_plural`` - human-readable plural name (defaults to
     ``verbose_name + 's'``).
   - ``ordering = ["-created_at"]`` - default ordering applied to all
     queries on this model.  Prefix with ``-`` for descending.
   - ``unique_together = [("field_a", "field_b")]`` - composite unique
     constraint.  Each inner tuple or list is one constraint.
   - ``index_together = [("field_a", "field_b")]`` - composite index.  Each
     inner tuple or list creates one index.
   - ``indexes = [Index(...)]`` - explicit :class:`Index` declarations.
   - ``constraints = [CheckConstraint(...)]`` - explicit
     :class:`Constraint` declarations.
   - ``backend = "alias"`` - route this model to a specific database alias
     instead of the default.

   .. py:attribute:: objects

      :class:`Manager` instance - the primary entry point for queries.

   .. py:attribute:: pk

      Alias for ``id``.  Always returns the primary key value.

   .. py:attribute:: has_changed

      ``True`` if any field value differs from the last saved state.

   .. py:method:: save(ignore_permissions=False) -> Awaitable[None]

      Persist (INSERT or UPDATE) the instance.  Runs the full lifecycle
      hook chain - see `Lifecycle Hooks`_ below.

   .. py:method:: delete(ignore_permissions=False) -> Awaitable[None]

      Delete this instance.  Fires ``on_delete`` → DELETE → ``after_delete``.

   .. py:method:: refresh_from_db() -> Awaitable[None]

      Re-load all field values from the database in place.

   .. py:method:: to_dict() -> dict

      Serialize the instance to a plain Python dict.

   .. py:method:: get_sensitive(field_name: str) -> str | None

      Decrypt and return the plaintext value of a :class:`SensitiveField`
      column.  Raises :class:`FieldError` if the field is not a
      ``SensitiveField``.

      .. code-block:: python

         config = await APIConfig.objects.get(id=1)
         plaintext = config.get_sensitive("api_key")  # "sk-live-abc123"

      For :class:`PasswordField` (user passwords), the original plaintext
      cannot be recovered; use ``check_password()`` instead.

.. py:class:: AbstractModel

   Abstract base - subclasses inherit its fields but share no table.  Use
   for timestamp mixins or other common patterns.

.. py:class:: Manager

   Attached to every non-abstract model as ``Model.objects``.  Provides
   factory methods that all return :class:`QuerySet` (lazy) or awaitables
   (terminal).

   **Factory methods (return QuerySet):**
   ``all()``, ``filter()``, ``exclude()``, ``order_by()``, ``only()``,
   ``defer()``, ``distinct()``, ``annotate()``, ``select_related()``,
   ``prefetch_related()``, ``using(alias)``

   **Awaitable shortcuts:**
   ``get(**kwargs)``, ``get_or_none(**kwargs)``, ``create(**kwargs)``,
   ``get_or_create(defaults, **kwargs)``,
   ``update_or_create(defaults, **kwargs)``,
   ``in_bulk(id_list=None, field_name='id')``

   **Terminal awaitables:**
   ``first()``, ``last()``, ``count()``, ``exists()``,
   ``values(*fields)``, ``values_list(*fields, flat=False)``,
   ``aggregate(**kwargs)``, ``explain()``

   **Bulk operations:**
   ``bulk_create(objs, batch_size=None)``,
   ``bulk_update(objs, fields, batch_size=None)``

   **Iteration helpers:**
   ``iterator(chunk_size=2000)``, ``batch(size=100)``, ``id_batch(size=100)``

   **Single-model helpers** (for models with ``Meta.single = True``):
   ``get_single()``, ``create_single(**kwargs)``,
   ``update_single(**kwargs)``, ``get_or_create_single(**kwargs)``

   **Custom QuerySet:**
   ``from_queryset(queryset_class)`` - classmethod that returns a Manager
   subclass using *queryset_class* for all queries, so custom QuerySet
   methods are callable directly on the manager.

   .. code-block:: python

      class PublishedQuerySet(QuerySet):
          def published(self) -> QuerySet:
              return self.filter(published=True)

      PublishedManager = Manager.from_queryset(PublishedQuerySet)

      class Post(Model):
          objects = PublishedManager()

      posts = await Post.objects.published().all()

   ``update_or_create`` looks up a row matching ``**kwargs``, updates it
   with ``defaults``, and creates it when absent.  Returns
   ``(instance, created)``.

   ``in_bulk`` returns a ``{field_value: instance}`` mapping.  When
   *id_list* is ``None`` all rows are returned (subject to
   ``MAX_QUERY_ROWS``).

.. py:class:: QuerySet

   Lazy, chainable query builder.  All filtering/ordering/slicing methods
   return a **new** ``QuerySet`` (non-mutating).  Results are fetched only
   when a *terminal* method is awaited.

   A ``QuerySet`` is also directly awaitable: ``await qs`` is equivalent to
   ``await qs.all()``.

   .. note:: **No default row limit**

      ``filter()``, ``all()``, and other terminal methods return **all
      matching rows** by default.  Use :meth:`limit` per-query or set
      ``MAX_QUERY_ROWS`` in your project settings to apply a project-wide
      cap.  For large datasets prefer :meth:`iterator` / :meth:`batch`
      which stream rows without loading the entire result into memory.

      .. code-block:: python

         # ── no limit by default ──────────────────────────────────────
         async def example():
             posts = await Post.objects.all()           # all rows

             # ── explicit limit ────────────────────────────────────────
             posts = await Post.objects.limit(50).all() # exactly 50

         # ── optional project-wide cap ────────────────────────────────
         # settings.py
         MAX_QUERY_ROWS = 1000  # apply a default cap to all queries

         # ── stream all rows without a limit ──────────────────────────
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

      FK traversal is supported across multiple relationship hops:
      ``author__username="alice"`` performs a JOIN on the ``author`` FK
      field, and ``parent__reporter__profile__bio="hello"`` chains three
      JOINs continuously through the relationship graph.  A maximum depth
      of 5 FK hops is enforced per traversal to prevent query complexity
      attacks.

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

   .. py:method:: using(alias) -> QuerySet

      Route this query to the database *alias*, overriding the router for
      the entire chain.  Unknown aliases raise
      :class:`~openviper.db.exceptions.DatabaseAliasNotFoundError` when the
      query executes.

      .. code-block:: python

         users = await User.objects.using("replica").filter(is_active=True).all()

   .. py:method:: select_for_update(nowait=False, skip_locked=False) -> QuerySet

      Apply ``SELECT FOR UPDATE`` row-level locking.  Must be used inside
      :func:`~openviper.db.connection.atomic` or
      :func:`~openviper.db.connection.transaction`.

      - *nowait* - raise immediately if a conflicting lock is held.
      - *skip_locked* - skip locked rows rather than waiting.
        ``nowait`` and ``skip_locked`` are mutually exclusive.

      .. code-block:: python

         async with atomic():
             post = await Post.objects.select_for_update().filter(id=1).get()
             post.views += 1
             await post.save()

   **Column selection:**

   .. py:method:: only(*fields) -> QuerySet

      Restrict the ``SELECT`` to the given field names.  The primary key is
      always included.  All other fields will be ``None`` on instances.

   .. py:method:: defer(*fields) -> QuerySet

      Exclude the given fields from the ``SELECT``.  Mutually exclusive
      with ``only()`` - the last call wins.

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

      Return the parameterized SQL query string for the current queryset.

      Compiles the query with parameter placeholders (not literal values)
      so that sensitive filter values are not exposed in the output.
      Useful for debugging and logging without leaking credentials.

      .. code-block:: python

         qs = Post.objects.filter(is_published=True).order_by("-created_at").limit(10)
         print(qs.raw_sql())
         # SELECT posts.* FROM posts WHERE is_published = :is_published_1
         # ORDER BY created_at DESC LIMIT :param_1

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
      pagination.  Safe for very large tables - **not subject to the default
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

   .. py:attribute:: num_pages
      :type: int

      Total number of pages (``ceil(total_count / page_size)``).

   .. py:attribute:: has_next
      :type: bool

      ``True`` when a next page exists (checks ``next_cursor`` first,
      then ``number < num_pages``).

   .. py:attribute:: has_previous
      :type: bool

      ``True`` when ``number > 1``.

   .. py:attribute:: next_page_number
      :type: int

      ``number + 1``.

   .. py:attribute:: previous_page_number
      :type: int

      ``number - 1``.

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
       Rejects all C0 control characters (U+0000–U+001F) and DEL (U+007F)
       to prevent header injection attacks.
   * - ``URLField``
     - ``CharField`` with URL validation.  Only ``http`` and ``https``
       schemes are accepted by default.
   * - ``SlugField``
     - ``CharField`` restricted to ``[-a-zA-Z0-9_]``.  Must start and end
       with an alphanumeric character.
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
     - File upload; stores path relative to ``MEDIA_ROOT``.  Content is
       validated against declared MIME type via magic-number signatures.
   * - ``ImageField``
     - ``FileField`` with image content-type validation and structural
       magic-number verification.
   * - ``HTMLField``
     - HTML content with XSS sanitization via *nh3* (or ``html.escape``
       fallback).  Configurable allowed tags, attributes, and URL schemes.
   * - ``PasswordField(min_length=4, max_length=128)``
     - One-way hashed password storage (e.g. user passwords).  Stores
       Argon2id/bcrypt hashes produced by
       :mod:`openviper.auth.hashers`.  The original plaintext cannot be
       recovered; use ``model.set_password()`` to hash and
       ``model.check_password()`` to verify.
   * - ``SensitiveField(max_length=512)``
     - Encrypted secret storage (e.g. API keys, tokens).  Values are
       encrypted with Fernet symmetric encryption derived from
       ``settings.SECRET_KEY``.  The original plaintext can be retrieved
       via ``model.get_sensitive()``.  Encrypted values are prefixed
       with ``enc$`` for identification.
   * - ``ForeignKey(to, on_delete="CASCADE", related_name=None)``
     - Many-to-one relationship.  FK column is ``{name}_id``.
       ``on_delete``: ``"CASCADE"``, ``"PROTECT"``, ``"SET_NULL"``,
       ``"SET_DEFAULT"``.
   * - ``OneToOneField(to, **kwargs)``
     - One-to-one relationship (unique FK).
   * - ``ManyToManyField(to, through=None, related_name=None)``
     - Many-to-many via a junction table (no direct column).
   * - ``CountryField(max_length=2, extra_countries=None)``
     - ISO 3166-1 alpha-2 country code stored as a 2-character ``VARCHAR``.
       Values are validated against the built-in country registry.
       Returns a :class:`~openviper.contrib.fields.countries.Country` instance on
       access, giving rich metadata properties: ``.iso``, ``.name``,
       ``.dial_code``, ``.alpha3``, ``.numeric``, ``.continent``,
       ``.region``, ``.capital``, ``.currency_code``, ``.currency_name``,
       ``.currency_symbol``, ``.languages``, ``.tld``, ``.flag``,
       ``.is_eu``, ``.is_eea``, ``.timezone``, ``.is_valid``.
       Pass ``extra_countries`` to register non-standard codes.
       Available from ``openviper.contrib.fields.countries``.

       .. code-block:: python

          from openviper.db import Model
          from openviper.contrib.fields.countries import CountryField

          class UserProfile(Model):
              country = CountryField(null=True, db_index=True)

          # Property access on instances
          profile.country.iso             # 'GB'
          profile.country.name            # 'United Kingdom'
          profile.country.dial_code       # '+44'
          profile.country.alpha3          # 'GBR'
          profile.country.numeric         # '826'
          profile.country.continent       # 'Europe'
          profile.country.region          # 'Northern Europe'
          profile.country.capital         # 'London'
          profile.country.currency_code   # 'GBP'
          profile.country.currency_name   # 'British Pound'
          profile.country.currency_symbol # '£'
          profile.country.languages       # ['en']
          profile.country.tld             # '.gb'
          profile.country.flag            # '🇬🇧'
          profile.country.is_eu           # False
          profile.country.is_eea          # False
          profile.country.timezone        # 'Europe/London'
          profile.country.is_valid        # True
          profile.country == 'GB'         # True (str subclass)

   * - ``PositiveIntegerField``
     - Non-negative integer (``>= 0``).  Stored as ``INTEGER``; validation
       rejects negative values.

   * - ``SmallIntegerField``
     - 16-bit integer (−32 768 to 32 767).  Stored as ``SMALLINT``.

   * - ``BigAutoField``
     - Auto-incrementing 64-bit integer primary key.  Use when the 32-bit
       ``AutoField`` range is insufficient.

   * - ``NullBooleanField``
     - ``BooleanField(null=True)`` - explicit three-state
       (``True`` / ``False`` / ``None``).

   * - ``DurationField``
     - ``timedelta`` stored as ``BIGINT`` microseconds.  Returns
       :class:`datetime.timedelta` on access.

   * - ``IPAddressField``
     - IPv4 or IPv6 address stored as ``VARCHAR(45)``.  Validates with
       :func:`ipaddress.ip_address`.

   * - ``GenericIPAddressField(protocol="both", unpack_ipv4=False)``
     - IPv4/IPv6 address with protocol filtering.  *protocol* accepts
       ``"both"`` (default), ``"IPv4"``, or ``"IPv6"``.  When *unpack_ipv4*
       is ``True``, IPv4-mapped IPv6 addresses (e.g. ``::ffff:192.0.2.1``)
       are unpacked to plain IPv4.

   * - ``ArrayField(base_field, size=None)``
     - Homogeneous list of a scalar field type.  On PostgreSQL the column
       uses the native ``ARRAY`` type (e.g. ``INTEGER[]``, ``VARCHAR[]``);
       on other databases values are stored as JSON text.
       *base_field* accepts a Field instance (``IntegerField()``) or class
       (``IntegerField``, auto-instantiated with defaults).
       *size* caps the maximum number of elements at validation time.
       Available from ``openviper.db.fields``.
       See :doc:`array_fields` for full documentation.

   * - ``CurrencyField(max_digits=19, decimal_places=2, default_currency="USD")``
     - Monetary amount paired with an ISO 4217 currency code.  Creates two
       columns: a ``NUMERIC`` amount and a ``CHAR(3)`` currency code named
       ``<field>_currency``.  The amount column enables native SQL
       ``SUM``/``AVG`` aggregation.  Instance access returns a
       :class:`~openviper.contrib.fields.currencies.Money` value object
       with arithmetic operators and cross-currency guards.  Supports
       ``extra_currencies``, ``strict``, ``allow_negative``,
       ``currency_choices``, and ``currency_field_name`` options.
       Available from ``openviper.contrib.fields.currencies``.
       Requires ``pip install openviper[currencies]``.
       See :doc:`currency_field` for full documentation.

       .. code-block:: python

          from openviper.db import Model
          from openviper.contrib.fields.currencies import CurrencyField, Money

          class Product(Model):
              price = CurrencyField(max_digits=12, decimal_places=2, default_currency="USD")

          product = Product(price=Money("19.99", "USD"))
          product.price            # Money('19.99', 'USD')
          product.price_currency   # 'USD'

          # Native SQL aggregation
          total = await Product.objects.aggregate(Sum("price"))

``openviper.db.models.Index``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: Index(fields, name=None, condition=None)

   Database index declaration for ``Meta.indexes``.

   :param fields: List of column names to index.
   :param name: Optional index name.
   :param condition: Optional SQL ``WHERE`` clause for partial indexes.
     Validated against dangerous SQL patterns (semicolons, comments,
     DDL/DML keywords) to prevent statement injection.

   .. code-block:: python

      class User(Model):
          class Meta:
              indexes = [
                  Index(fields=["first_name", "last_name"], name="idx_user_names"),
                  Index(fields=["email"], condition="is_active = 1", name="idx_active_email"),
              ]

``openviper.db.models.Constraint``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: Constraint(name)

   Base class for database constraints declared in ``Meta.constraints``.

.. py:class:: CheckConstraint(name, check)

   Database ``CHECK`` constraint.  The *check* parameter is a raw SQL
   expression validated against dangerous SQL patterns to prevent statement
   injection.

   .. code-block:: python

      class Price(Model):
          amount = DecimalField(max_digits=10, decimal_places=2)

          class Meta:
              constraints = [
                  CheckConstraint(name="price_positive", check="amount > 0"),
              ]

.. py:class:: UniqueConstraint(name, fields)

   Database ``UNIQUE`` constraint spanning one or more columns.  Declared
   in ``Meta.constraints``.

   .. code-block:: python

      class Membership(Model):
          class Meta:
              constraints = [
                  UniqueConstraint(name="unique_member", fields=["user_id", "group_id"]),
              ]

``openviper.db.models.TextChoice``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: TextChoice

   A string-based :class:`~enum.Enum` for model field choices.  Use as
   ``choices=TextChoice`` on a :class:`CharField` or :class:`IntegerField`
   to define a closed set of valid values with display labels.

``openviper.db.connection``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: init_db(drop_first=False) -> Awaitable[None]

   Create all registered tables.  If *drop_first* is ``True``, drop all
   tables before recreating them.  Called automatically on startup.

.. py:function:: close_db() -> Awaitable[None]

   Dispose of the engine, close all pooled connections, and clean up
   stale per-event-loop locks.

.. py:function:: get_connection() -> AsyncConnection

   Return an async database connection.  If a per-request connection is
   active (via :func:`request_connection`), it is returned directly so that
   multiple ORM calls within a single request share the same underlying
   connection.  Otherwise a fresh connection is acquired from the pool.

.. py:function:: request_connection() -> AsyncContextManager[AsyncConnection]

   Pin a single pooled connection for the duration of a request.  All
   ``get_connection()`` calls inside this context return the *same*
   connection, eliminating per-query pool round-trips.

   .. code-block:: python

      async with request_connection() as conn:
          posts = await Post.objects.filter(published=True).all()
          count = await Post.objects.count()

.. py:function:: configure_db(database_url, echo=False) -> Awaitable[None]

   Explicitly configure the database engine.  Call before :func:`init_db`.
   Disposes any existing engine before replacing it so that pooled
   connections are not leaked.

.. py:function:: transaction(using=None, read_only=False) -> AsyncContextManager[AsyncConnection]

   Async context manager for a transaction pinned to a database alias.
   When *using* is provided, the transaction runs on the backend for that
   alias and pins the routing context.  If *read_only* is ``True`` and the
   alias is configured as read-only, the transaction is allowed.

   .. code-block:: python

      async with transaction(using="default"):
          await Post.objects.create(title="Hello")

.. py:function:: atomic() -> AsyncContextManager[AsyncConnection]

   Async context manager that wraps a block of ORM operations in a
   transaction.  On normal exit the transaction is committed; on any
   exception it is rolled back and the exception is re-raised.

   .. code-block:: python

      async with atomic():
          await Post.objects.create(title="Hello")
          await Tag.objects.create(name="python")

.. py:function:: reset_engine() -> None

   Drop all engine references without disposing pooled connections.  Used
   in test teardown to reset engine state between tests without incurring
   the overhead of a full ``close_db()`` / ``dispose()`` cycle.

.. py:function:: cleanup_stale_locks() -> None

   Remove per-event-loop lock entries for loops that are no longer running.
   Called automatically during engine disposal to prevent unbounded memory
   growth in long-running processes (test runners, workers).

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
     - Validates all fields.  Override to add custom business rules -
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

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ - simple model (``CharField``, ``BooleanField``, ``DateTimeField``)
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - ``UUIDField`` PK, ``DecimalField``, ``ImageField``, ``after_insert`` lifecycle hook
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - ``ForeignKey``, ``JSONField``, ``ImageField``, custom ``BaseUser``
   - `examples/fx/ <https://github.com/mymi14s/openviper/tree/master/examples/fx>`_ - root-layout project with models and schemas

Defining Models
~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.models import Model, AbstractModel
    from openviper.db import fields

    class TimestampMixin(AbstractModel):
        """Shared timestamp fields - no table created."""
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

Q() Objects - Complex Filters
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
        # select_related - one SQL JOIN, good for single FK always needed
        posts = await Post.objects.select_related("author").all()
        for post in posts:
            print(post.author.name)   # no extra DB query

        # prefetch_related - separate id__in query, good for large sets
        posts = await Post.objects.prefetch_related("author").all()
        for post in posts:
            print(post.author.name)   # cached from batch fetch

        # Lazy FK access (when neither is used) - await to load
        post = await Post.objects.get(id=1)
        author = await post.author   # issues SELECT on first access

bulk_create and bulk_update
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def example():
        # bulk_create - INSERT all in a single statement
        posts = [Post(title=f"Post {i}", body="...") for i in range(100)]
        await Post.objects.bulk_create(posts)

        # bulk_update - UPDATE in batches
        published_posts = await Post.objects.filter(is_published=False).all()
        for post in published_posts:
            post.is_published = True
        await Post.objects.bulk_update(published_posts, fields=["is_published"])

Large Dataset Iteration
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def example():
        # iterator - keyset pagination, one instance at a time
        async for post in Post.objects.filter(is_published=True).iterator(chunk_size=500):
            await process(post)

        # batch - OFFSET pagination, groups of instances
        async for batch in Post.objects.filter(is_published=True).batch(size=200):
            await index_search(batch)

        # id_batch - keyset pagination, groups of instances (stable during writes)
        async for batch in Post.objects.filter(is_published=True).id_batch(size=500):
            await process_batch(batch)

Transactions
~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.connection import transaction, atomic

    async def example():
        # transaction() pins all ORM operations to a specific alias
        async with transaction(using="default"):
            await Post.objects.create(title="Hello")
            await Tag.objects.create(name="python")

        # atomic() wraps a block in a commit/rollback transaction
        async with atomic():
            await Post.objects.create(title="Hello")
            await Tag.objects.create(name="python")

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

OpenViper uses a JSON-based schema synchronization system.  Each model
gets a JSON schema file in ``<app>/schemas/<ModelName>.json`` that
represents the desired database schema state.

Run ``openviper viperctl makemigrations .`` to detect model changes and
update the JSON schema files, then ``openviper viperctl migrate .`` to
apply them to the database.

The system is stateless and idempotent: ``migrate`` diffs the JSON
schemas against the live database via SQLAlchemy introspection and
applies only the delta.  Running ``migrate`` twice produces no changes
on the second run.

Supported databases: PostgreSQL, MariaDB/MySQL, MSSQL, Oracle, SQLite.

Supported schema operations:

- ``CreateTable`` - create a new table.
- ``DropTable`` - drop a table entirely (data loss; use with caution).
- ``AddColumn`` - add a new column to an existing table.
- ``RemoveColumn`` - drop a column from a table.
- ``RenameColumn`` - rename a column.  Detected automatically by
  ``makemigrations`` when a field is renamed (matched by type).
- ``AlterColumn`` - change column type or primary key status.
- ``CreateIndex`` - create a composite or named index.  Supports
  ``unique=True`` for unique indexes.
- ``RemoveIndex`` - drop a composite or named index.
- ``AddConstraint`` - add a ``CHECK`` or ``UNIQUE`` constraint.
- ``RemoveConstraint`` - remove a previously-added constraint.
- ``RunSQL`` - execute arbitrary SQL with optional bound parameters.

Type change validation:

``makemigrations`` validates column type changes before writing JSON
schemas.  Incompatible conversions (e.g., Integer to String) raise an
error unless ``--force`` is passed.  Narrowing changes (e.g.,
VARCHAR(200) to VARCHAR(50)) produce a warning.

Rename detection:

When a field is renamed, ``makemigrations`` matches the old column
name to the new one by type and stores ``old_name`` in the JSON schema.
At ``migrate`` time, this metadata triggers a ``RENAME COLUMN``
operation instead of drop + add, preserving existing data.

Data Patches
------------

For one-time data transformations that cannot be expressed as schema
changes, use the ``@db_patch`` decorator.  Patches are Python async
functions that run during ``migrate`` and are tracked to ensure each
runs exactly once.

.. code-block:: python

   from openviper.db.patches import db_patch

   @db_patch
   async def backfill_status():
       """Runs after schema sync (default)."""
       await User.objects.filter(status=None).update(status="active")

   @db_patch(post_migrate=False)
   async def read_old_fields():
       """Runs before schema sync - old schema still in place."""
       ...

   @db_patch(order=2)
   async def cleanup_permissions():
       """Runs after schema sync, ordered after other post patches."""
       ...

Patch phases:

- ``post_migrate=False`` (pre-migration): runs before schema sync.
  The old schema is still in the database, so patches can read fields
  that are about to be removed or renamed.
- ``post_migrate=True`` (default, post-migration): runs after schema
  sync.  The new schema is in place, so patches can use new fields.

Patches are discovered automatically from ``<app>/patches/*.py``
files.  Each patch runs exactly once, tracked by the
``openviper_patches`` database table.

``openviper.db.executor``
~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: bypass_permissions(*, reason=None) -> Generator[None]

   Context manager that disables row-level permission checks for the
   duration of the block.  Accepts an optional *reason* string for audit
   logging.

   .. code-block:: python

      from openviper.db.executor import bypass_permissions

      async with bypass_permissions(reason="system cleanup"):
          await SensitiveModel.objects.all()

.. py:function:: validate_regex_pattern(pattern) -> None

   Reject regex patterns that could cause catastrophic backtracking (ReDoS).
   Enforces a maximum length and blocks nested quantifier patterns.  Raises
   :class:`FieldError` on dangerous patterns.

.. py:function:: assert_safe_table_name(name) -> None

   Raise :class:`ValueError` if *name* contains characters outside the
   safe identifier set (``[a-zA-Z0-9_]``, must start with a letter or
   underscore).  Used to prevent SQL injection through table names.

.. py:function:: escape_like(value) -> str

   Escape LIKE metacharacters (``%`` and ``_``) in user-provided values.
   Prevents LIKE injection attacks where malicious input like ``%`` could
   match all rows.  Use with ``escape="\\"`` in the query.

   .. code-block:: python

      from openviper.db.executor import escape_like

      pattern = escape_like(user_input)
      results = await Product.objects.filter(name__contains=pattern).all()

``openviper.db.utils``
~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: BoundedDict(maxsize)

   :class:`collections.OrderedDict` subclass that evicts the oldest entries
   when exceeding *maxsize*.  Thread-safe via an internal lock.  Used as
   the compiled-statement cache for SQLAlchemy.

.. py:function:: validate_on_delete(action, context) -> str

   Validate that *action* is a supported ``ON DELETE`` action.  Accepts
   ``"CASCADE"``, ``"PROTECT"``, ``"RESTRICT"``, ``"SET_NULL"``,
   ``"SET_DEFAULT"``, ``"NO_ACTION"``, ``"DO_NOTHING"``, ``"SET NULL"``,
   and ``"SET DEFAULT"``.  Returns the normalised uppercased action.  Raises
   :class:`ValueError` on invalid actions.

.. py:function:: validate_sql_expression(value, field_name, context) -> str

   Reject SQL expressions containing destructive patterns (semicolons,
   SQL comments, DDL/DML keywords).  Used to validate ``condition``
   parameters on :class:`Index` and :class:`CheckConstraint`.  Returns
   *value* on success; raises :class:`ValueError` on dangerous input.

.. py:function:: validate_identifier(name, description) -> str

   Validate that *name* is a safe SQL identifier (letters, digits,
   underscores; must start with a letter or underscore).  Returns *name*
   on success; raises :class:`ValueError` on invalid input.

.. py:function:: quote_identifier(name, dialect) -> str

   Quote a table or column name based on the database dialect.  Uses
   backtick quoting for MySQL, square brackets for MSSQL, and double-quote
   quoting for PostgreSQL/SQLite/Oracle.

.. py:function:: sql_literal(value) -> str

   Format a Python value as a SQL literal.  Handles ``None`` → ``NULL``,
   booleans, numbers, and strings (with single-quote and backslash escaping).

.. py:function:: cast_to_pk_type(model_class, value) -> object

   Cast *value* to the Python type of *model_class*'s primary key field.
   Returns ``None`` unchanged.  Falls back to the raw value if the field's
   ``to_python`` conversion fails.

``openviper.db.exceptions``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

All database exceptions inherit from Python's built-in :class:`Exception`.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Exception
     - Description
   * - ``DatabaseConfigurationError``
     - Invalid ``DATABASES`` or routing configuration.
   * - ``DatabaseBackendNotFoundError``
     - Configured backend cannot be imported or found.
   * - ``DatabaseAliasNotFoundError``
     - Requested database alias is not configured.
   * - ``DatabaseReadOnlyError``
     - Write attempted on a read-only database alias.
   * - ``DatabaseRoutingError``
     - Router returned invalid alias or routing failed.
   * - ``DatabaseTransactionRoutingError``
     - Invalid routing behavior inside a transaction.
   * - ``DatabaseOperationNotSupportedError``
     - Backend does not support the requested operation.
   * - ``VirtualModelError``
     - Base error for virtual model operations.
   * - ``VirtualBackendNotFoundError``
     - Virtual model backend name is not registered.
   * - ``ReadOnlyVirtualModelError``
     - Write operation attempted on a read-only virtual model.
   * - ``UnsupportedVirtualQueryError``
     - Virtual backend cannot execute the requested query.
   * - ``VirtualBackendOperationError``
     - Virtual backend operation failed.
   * - ``SingleModelError``
     - Base error for single model operations.
   * - ``SingleModelDoesNotExist``
     - Requested single model instance does not exist.
   * - ``SingleModelAlreadyExistsError``
     - A single model instance already exists.
   * - ``SingleModelDeleteForbiddenError``
     - Delete attempted for single model data.
   * - ``SingleModelDuplicateForbiddenError``
     - Duplicate attempted for single model data.

``openviper.db.events``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:data:: model_event

   Module-level event dispatcher instance.  Use the ``@model_event.trigger``
   decorator to register handlers outside the model class.

   .. code-block:: python

      from openviper.db.events import model_event

      @model_event.trigger("myapp.models.Post.after_insert")
      async def on_post_created(post, event):
          print(f"New post: {post.title}")

.. py:data:: SUPPORTED_EVENTS

   :class:`frozenset` of all thirteen supported lifecycle event names:
   ``before_validate``, ``validate``, ``before_insert``, ``before_save``,
   ``after_insert``, ``on_update``, ``on_change``, ``on_delete``,
   ``after_delete``, ``pre_bulk_create``, ``post_bulk_create``,
   ``pre_bulk_update``, ``post_bulk_update``.

ManyToManyField API
~~~~~~~~~~~~~~~~~~~~

.. py:class:: ManyToManyField(to, through=None, related_name=None)

   Many-to-many relationship via a junction table.  When *through* is
   omitted, an auto-generated junction model is created.

   Accessing the field on an instance returns a
   :class:`~openviper.db.fields.ManyToManyManager` with the following methods:

   .. py:method:: all() -> Awaitable[list[Model]]

      Return all related objects.  Uses prefetch cache when available.

   .. py:method:: add(*objects) -> Awaitable[None]

      Add one or more objects to the relationship.  Raises
      :class:`ValueError` if the source instance is unsaved.

   .. py:method:: remove(*objects) -> Awaitable[None]

      Remove one or more objects from the relationship.

   .. py:method:: clear() -> Awaitable[None]

      Remove all objects from the relationship.

   .. py:method:: count() -> Awaitable[int]

      Return the count of related objects.

   .. py:method:: set(objects) -> Awaitable[None]

      Replace the full set of related objects.  Performs a minimal diff
      (removes only entries no longer wanted, adds only missing entries).

LazyFK - Lazy FK Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: LazyFK(fk_field, instance, fk_id)

   Awaitable proxy returned by :class:`ForeignKey` descriptor access when
   the related object is not yet loaded.  Supports transparent comparison,
   hashing, and string conversion so that code using raw FK ID values
   continues to work without awaiting.

   .. code-block:: python

      post = await Post.objects.get(id=1)
      author_proxy = post.author       # LazyFK - not yet loaded
      author = await post.author       # loads from DB
      print(author.username)

      # Comparison works without loading
      if post.author == 5:
          ...

      # Boolean check works without loading
      if post.author:
          ...

Virtual Models
--------------

A **Virtual Model** uses ``Meta.virtual = True`` and a ``Meta.backend`` string
to route data operations to a custom async storage adapter instead of the
SQL database.  Virtual models are useful for data that lives in external
APIs, in-memory stores, or read-only services.

.. code-block:: python

   from openviper.db import Model
   from openviper.db.fields import BooleanField, CharField
   from openviper.db.backends.base import VirtualBackend, VirtualBackendCapabilities

   class SettingsBackend(VirtualBackend):
       capabilities = VirtualBackendCapabilities(
           supports_create=True,
           supports_update=True,
           supports_delete=False,
           supports_filter=True,
           supports_count=True,
       )

       async def get(self, model_class, primary_key):
           ...

       async def list(self, model_class, query):
           ...

       async def create(self, model_class, data):
           ...

       async def update(self, model_class, primary_key, data):
           ...

       async def delete(self, model_class, primary_key):
           ...

   class RemoteSettings(Model):
       site_name = CharField(max_length=255)
       maintenance_mode = BooleanField(default=False)

       class Meta:
           virtual = True
           backend = "settings_api"

Virtual models can also be **single models** (``Meta.single = True``) for
singleton settings backed by an external API.  See :doc:`single_models` for
details on single model behaviour.

``VirtualBackendCapabilities``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: VirtualBackendCapabilities

   Declares which operations a virtual backend supports.  Unsupported
   operations raise :class:`UnsupportedVirtualQueryError` early.

   .. attribute:: supports_create
      :type: bool

      Whether ``create()`` is supported (default ``True``).

   .. attribute:: supports_update
      :type: bool

      Whether ``update()`` is supported (default ``True``).

   .. attribute:: supports_delete
      :type: bool

      Whether ``delete()`` is supported (default ``True``).

   .. attribute:: supports_filter
      :type: bool

      Whether ``filter()`` is supported (default ``True``).

   .. attribute:: supports_filter_ops
      :type: bool

      Whether advanced filter lookups (``__contains``, ``__gt``, etc.) are
      supported (default ``False``).

   .. attribute:: supports_order_by
      :type: bool

      Whether ``order_by()`` is supported (default ``True``).

   .. attribute:: supports_offset
      :type: bool

      Whether ``offset()`` is supported (default ``True``).

   .. attribute:: supports_limit
      :type: bool

      Whether ``limit()`` is supported (default ``True``).

   .. attribute:: supports_count
      :type: bool

      Whether ``count()`` is supported (default ``False``).

   .. attribute:: supports_distinct
      :type: bool

      Whether ``distinct()`` is supported (default ``False``).

   .. attribute:: supports_only
      :type: bool

      Whether ``only()`` is supported (default ``False``).

   .. attribute:: supports_defer
      :type: bool

      Whether ``defer()`` is supported (default ``False``).

   .. attribute:: supports_bulk_create
      :type: bool

      Whether ``bulk_create()`` is supported (default ``False``).

   .. attribute:: supports_bulk_update
      :type: bool

      Whether ``bulk_update()`` is supported (default ``False``).

   .. attribute:: supports_bulk_delete
      :type: bool

      Whether ``bulk_delete()`` is supported (default ``False``).

``VirtualBackend``
~~~~~~~~~~~~~~~~~~

.. py:class:: VirtualBackend

   Abstract base class for virtual model storage adapters.  Subclass and
   implement the required methods to connect models to REST APIs, caches,
   or other data sources.

   .. attribute:: capabilities
      :type: VirtualBackendCapabilities

      Declares which operations this backend supports.

   .. attribute:: read_only
      :type: bool

      When ``True``, all write operations raise
      :class:`ReadOnlyVirtualModelError`.

   .. method:: get(model_class, primary_key) -> Awaitable[Mapping | None]

      Return one record by primary key, or ``None`` if not found.

   .. method:: list(model_class, query) -> Awaitable[Sequence[Mapping]]

      Return records matching the :class:`QuerySpec`.

   .. method:: create(model_class, data) -> Awaitable[Mapping]

      Create and return one record.

   .. method:: update(model_class, primary_key, data) -> Awaitable[Mapping]

      Update and return one record.

   .. method:: delete(model_class, primary_key) -> Awaitable[None]

      Delete one record.

   .. method:: count(model_class, query) -> Awaitable[int]

      Return the total number of records matching *query*.  The default
      implementation materialises all rows and counts the list - override
      for efficient counting.
