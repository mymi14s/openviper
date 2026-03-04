.. _orm:

==========
ORM System
==========

OpenViper ships an async-first ORM built on top of **SQLAlchemy Core**.
It provides a Django-inspired API while remaining fully compatible with
Python's ``async``/``await`` syntax throughout.

.. contents:: On this page
   :local:
   :depth: 2

----

Model Definition
-----------------

Every database-backed entity inherits from :class:`~openviper.db.models.Model`:

.. code-block:: python

   from openviper.db.models import Model
   from openviper.db.fields import (
       CharField, TextField, BooleanField,
       DateTimeField, ForeignKey, IntegerField
   )

   class Post(Model):
       title      = CharField(max_length=255)
       body       = TextField()
       published  = BooleanField(default=False)
       views      = IntegerField(default=0)
       created_at = DateTimeField(auto_now_add=True)
       updated_at = DateTimeField(auto_now=True)

       class Meta:
           table_name = "blog_posts"

The ``Meta`` inner class accepts:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Option
     - Description
   * - ``table_name``
     - Explicit database table name (auto-derived from class name if omitted)
   * - ``abstract``
     - If ``True``, no table is created; used as a mixin base

----

Fields
------

All fields live in :mod:`openviper.db.fields`.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Field
     - Description
   * - ``AutoField``
     - Auto-incrementing integer primary key (implicit on every model)
   * - ``IntegerField``
     - 32-bit signed integer
   * - ``BigIntegerField``
     - 64-bit signed integer
   * - ``PositiveIntegerField``
     - Non-negative integer with check constraint
   * - ``FloatField``
     - IEEE 754 floating-point
   * - ``DecimalField(max_digits, decimal_places)``
     - Fixed-precision decimal
   * - ``CharField(max_length)``
     - Variable-length string (VARCHAR)
   * - ``TextField``
     - Unbounded text
   * - ``BooleanField``
     - Boolean (stored as integer 0/1)
   * - ``DateTimeField``
     - Date + time; supports ``auto_now`` and ``auto_now_add``
   * - ``DateField``
     - Date only
   * - ``TimeField``
     - Time only
   * - ``BinaryField``
     - Large binary object (BLOB)
   * - ``UUIDField``
     - UUID stored as text
   * - ``JSONField``
     - JSON; automatically serialised and deserialised
   * - ``EmailField``
     - ``CharField`` with email-format validation
   * - ``SlugField``
     - URL-safe slug string
   * - ``URLField``
     - URL string
   * - ``IPAddressField``
     - IPv4 or IPv6 address
   * - ``FileField``
     - Upload file path
   * - ``ImageField``
     - Upload image path with extension validation
   * - ``ForeignKey(to, on_delete)``
     - Many-to-one foreign key relationship
   * - ``OneToOneField(to, on_delete)``
     - Unique foreign key (one-to-one)
   * - ``ManyToManyField(to)``
     - Many-to-many via auto-created junction table

**Common field kwargs:**

.. code-block:: python

   CharField(
       max_length  = 255,
       null        = False,   # allows NULL at DB level
       blank       = False,   # allows empty string at validation level
       unique      = False,   # UNIQUE constraint
       db_index    = False,   # create a DB index
       default     = None,    # Python default value
       db_column   = None,    # override the column name
       choices     = None,    # list of (value, label) tuples
       help_text   = "",      # descriptive text for forms/admin
   )

**DateTimeField extras:**

.. code-block:: python

   DateTimeField(
       auto_now_add = True,  # set to now() on INSERT, never updated
       auto_now     = True,  # set to now() on every INSERT / UPDATE
   )

----

Async Queries
--------------

All query-returning operations are coroutines.  You must ``await`` them.

Manager API
~~~~~~~~~~~

The :class:`~openviper.db.models.Manager` is accessed via
``ModelClass.objects``:

.. code-block:: python

   # Return all rows
   posts = await Post.objects.all()

   # Filter (all args are AND-ed)
   posts = await Post.objects.filter(published=True).all()

   # Exclude
   posts = await Post.objects.exclude(status="draft").all()

   # Get single row (raises DoesNotExist if zero rows)
   post = await Post.objects.get(id=42)

   # Get or None
   post = await Post.objects.get_or_none(slug="hello")

   # Create
   post = await Post.objects.create(title="Hello", body="World")

   # Get or create
   post, created = await Post.objects.get_or_create(
       slug="hello",
       defaults={"title": "Hello", "body": "World"}
   )

   # Bulk create
   posts = [Post(title=f"Post {i}") for i in range(100)]
   created = await Post.objects.bulk_create(posts)

QuerySet Chaining
~~~~~~~~~~~~~~~~~~

:class:`~openviper.db.models.QuerySet` methods return new ``QuerySet`` objects
and are evaluated lazily.  Call a terminal method (``all()``, ``get()``,
``count()``, etc.) to execute the query:

.. code-block:: python

   qs = Post.objects.filter(published=True).order_by("-created_at").limit(10).offset(0)

   posts = await qs.all()      # returns list[Post]
   count = await qs.count()    # returns int
   first = await qs.first()    # returns Post | None
   last  = await qs.last()     # returns Post | None
   exists = await qs.exists()  # returns bool

   # Bulk update
   updated = await Post.objects.filter(published=False).update(published=True)

   # Bulk delete
   deleted = await Post.objects.filter(created_at__lt=cutoff).delete()

Field Lookups
~~~~~~~~~~~~~~

Append lookup suffixes to field names with ``__`` (double-underscore):

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Lookup
     - SQL equivalent
   * - ``field=value`` / ``field__exact=value``
     - ``field = value``
   * - ``field__contains=value``
     - ``field LIKE '%value%'``
   * - ``field__icontains=value``
     - ``LOWER(field) LIKE '%value%'``
   * - ``field__startswith=value``
     - ``field LIKE 'value%'``
   * - ``field__endswith=value``
     - ``field LIKE '%value'``
   * - ``field__gt=value``
     - ``field > value``
   * - ``field__gte=value``
     - ``field >= value``
   * - ``field__lt=value``
     - ``field < value``
   * - ``field__lte=value``
     - ``field <= value``
   * - ``field__in=[v1, v2]``
     - ``field IN (v1, v2)``
   * - ``field__isnull=True``
     - ``field IS NULL``

.. code-block:: python

   await Post.objects.filter(title__icontains="python").all()
   await Post.objects.filter(views__gte=1000).all()
   await Post.objects.filter(created_at__lt=datetime(2024, 1, 1)).all()

Async Iteration
~~~~~~~~~~~~~~~~

Iterate over large result sets without loading all rows into memory:

.. code-block:: python

   async for post in Post.objects.filter(published=True):
       await process(post)

----

Instance Methods
-----------------

.. code-block:: python

   post = Post(title="Hello", body="World")

   # INSERT (or UPDATE if the instance already has a pk)
   await post.save()

   # UPDATE a single field without re-saving
   post.title = "Updated"
   await post.save()

   # Reload from the database
   await post.refresh_from_db()

   # DELETE
   await post.delete()

   # Transient properties
   post.pk           # primary key value
   post.content_type # "app.ModelName"
   post.has_changed  # True if any field differs from its DB value

----

Transactions
-------------

Use the SQLAlchemy connection context to run multiple statements in one
atomic transaction:

.. code-block:: python

   from openviper.db.connection import get_connection

   conn = await get_connection()
   async with conn.begin():
       post = await Post.objects.create(title="Atomic Post")
       await Tag.objects.create(name="python", post=post.pk)
       # Both committed together; any exception rolls back both.

----

Model Lifecycle Hooks
----------------------

Override async methods on the model to execute code at specific points
in the create / update / delete lifecycle:

.. code-block:: python

   class Post(Model):

       async def before_validate(self) -> None:
           """Called before validate() on every create and update."""

       async def validate(self) -> None:
           """Full field validation.  Raise ValueError to abort."""
           if not self.title:
               raise ValueError("title is required")

       async def before_insert(self) -> None:
           """Called only on INSERT, after validation."""

       async def before_save(self) -> None:
           """Called on every INSERT and UPDATE immediately before the SQL."""
           self.title = self.title.strip()

       async def after_insert(self) -> None:
           """Called after a successful INSERT."""
           await notify_new_post.send(post_id=self.pk)

       async def on_update(self) -> None:
           """Called after a successful UPDATE."""

       async def on_delete(self) -> None:
           """Called before a DELETE — raise to abort."""

       async def after_delete(self) -> None:
           """Called after a successful DELETE."""

       async def on_change(self, previous_state: dict) -> None:
           """Called after INSERT or UPDATE if values actually changed."""

**Execution order for create:**

.. code-block:: text

   before_validate → validate → before_insert → before_save
   → INSERT
   → after_insert → on_change

**Execution order for update:**

.. code-block:: text

   before_validate → validate → before_save
   → UPDATE
   → on_update → on_change

**Execution order for delete:**

.. code-block:: text

   on_delete → DELETE → after_delete

----

Model Events via Settings (MODEL_EVENTS)
-----------------------------------------

In addition to overriding lifecycle hook methods directly on the model class,
OpenViper lets you register external handler functions through the
``MODEL_EVENTS`` setting.  This keeps side-effect logic (notifications, cache
invalidation, search indexing, …) out of the model file and in dedicated
event modules.

Configuration format
~~~~~~~~~~~~~~~~~~~~~

In ``settings.py``, declare ``MODEL_EVENTS`` as a ``dataclasses.field`` with
a ``default_factory``:

.. code-block:: python

   import dataclasses
   from openviper.conf.settings import Settings


   class MySettings(Settings):

       MODEL_EVENTS: dict = dataclasses.field(
           default_factory=lambda: {
               "posts.models.Post": {
                   "after_insert": ["posts.events.create_likes"],
                   "after_delete": ["posts.events.cleanup_comments"],
                   "on_update":    ["posts.events.handle_post_update"],
               },
           }
       )

Key format
~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Dict key / value
     - Description
   * - Outer key: ``"<dotted.path.to.ModelClass>"``
     - Fully qualified Python path to the model, e.g. ``"posts.models.Post"``
   * - Inner key: event name
     - One of ``after_insert``, ``after_delete``, ``on_update``, ``on_change``,
       ``before_save``, ``on_delete``, ``after_delete``, ``before_insert``
   * - Inner value: list of handler paths
     - List of fully-qualified ``"<dotted.path.to.function>"`` strings;
       multiple handlers per event are supported and called in order

Handler function signature
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each handler receives the model instance as its only argument.  Handlers
may be plain functions or async coroutines — both are accepted:

.. code-block:: python

   # posts/events.py

   async def create_likes(model, event) -> None:
       """Called automatically after every new Post is inserted."""
       from likes.models import LikeCounter
       await LikeCounter.objects.create(post=model.pk, count=0)


   async def cleanup_comments(model, event) -> None:
       """Called automatically after a Post is deleted."""
       from comments.models import Comment
       await Comment.objects.filter(post=model.pk).delete()


   async def handle_post_update(model, event) -> None:
       """Called automatically after a Post is updated."""
       # e.g. invalidate a cache entry
       print(f"Post {model.pk} updated — cache busted")

Multiple handlers per event
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Provide a list with more than one dotted path to chain handlers:

.. code-block:: python

   MODEL_EVENTS: dict = dataclasses.field(
       default_factory=lambda: {
           "posts.models.Post": {
               "after_insert": [
                   "posts.events.create_likes",
                   "posts.events.notify_subscribers",
                   "search.indexer.index_post",
               ],
           },
       }
   )

Handlers are executed in list order.  If one raises an exception the
remaining handlers for that event are skipped and the exception propagates.

Multiple models
~~~~~~~~~~~~~~~

Register events for as many models as needed in the same dict:

.. code-block:: python

   MODEL_EVENTS: dict = dataclasses.field(
       default_factory=lambda: {
           "posts.models.Post": {
               "after_insert": ["posts.events.create_likes"],
               "after_delete": ["posts.events.cleanup_comments"],
               "on_update":    ["posts.events.handle_post_update"],
           },
           "users.models.Profile": {
               "after_insert": ["users.events.send_welcome_email"],
               "on_change":    ["users.events.invalidate_profile_cache"],
           },
       }
   )

.. note::

   ``MODEL_EVENTS`` handlers fire **after** the corresponding model lifecycle
   hook method on the class itself.  If the model defines ``async def
   after_insert(self)`` *and* the settings register an ``after_insert``
   handler, the method runs first, then the settings-registered function.

.. seealso::

   :ref:`tasks` — firing background tasks from event handlers.

----

Migrations
-----------

OpenViper auto-generates migrations from your model definitions.

Create migrations:

.. code-block:: bash

   python viperctl.py makemigrations             # all apps
   python viperctl.py makemigrations blog        # single app
   python viperctl.py makemigrations --empty blog  # empty migration stub

Apply migrations:

.. code-block:: bash

   python viperctl.py migrate                    # all pending
   python viperctl.py migrate blog               # single app
   python viperctl.py migrate blog 0003          # target specific migration

Generated migration files live in ``<app>/migrations/`` and are versioned
alongside your code.

----

Protected ORM (Role-Based Enforcement)
-----------------------------------------

The Protected ORM enforces row-level access rules transparently at the query
level.  Rules are declared in ``settings.py`` under ``INSTALLED_APPS`` conventions
or directly as model metadata, then applied when ``ignore_permissions=False``
(the default for all end-user code paths).

How it works
~~~~~~~~~~~~~

1. A request arrives; ``AuthenticationMiddleware`` sets ``request.user``.
2. The view calls ``Post.objects.filter(...).all()`` — no explicit permission
   check needed.
3. Before executing SQL, the ORM checks the user's roles against the model's
   access rules and either injects additional ``WHERE`` clauses or raises
   :class:`~openviper.exceptions.PermissionDenied`.

Bypassing for internal / admin operations:

.. code-block:: python

   # Skip permission enforcement for a trusted internal path
   posts = await Post.objects.filter(published=True, ignore_permissions=True).all()
   await post.save(ignore_permissions=True)
   await post.delete(ignore_permissions=True)

.. warning::

   Only bypass ``ignore_permissions`` in trusted internal code paths (worker
   tasks, migrations, management commands).  Never expose it to user input.

Defining Role Rules
~~~~~~~~~~~~~~~~~~~~

Role rules are configured in ``settings.py`` via the ``MODEL_EVENTS`` dict or
by overriding ``validate()`` / decorator-based permission checks in views.
Use :func:`openviper.auth.decorators.permission_required` to guard views:

.. code-block:: python

   from openviper.auth.decorators import permission_required

   @permission_required("blog.post.create")
   async def create_post(request):
       data = await request.json()
       post = await Post.objects.create(**data)
       return JSONResponse(post._to_dict(), status_code=201)

.. seealso::

   :ref:`authentication` for the full role and permission system.
