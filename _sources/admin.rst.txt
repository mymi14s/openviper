.. _admin:

===============
Admin Interface
===============

OpenViper ships a fully featured admin panel backed by a **Vue SPA** frontend
and a **REST API** served at ``/admin/api/``.  Models are registered with the
admin just like Django, and the admin is auto-discovered from every app in
``INSTALLED_APPS``.

The working examples used throughout this page are from the bundled
``examples/todoapp/`` and ``examples/ai_moderation_platform/`` projects.

.. contents:: On this page
   :local:
   :depth: 2

----

Accessing the Admin
--------------------

Navigate to ``http://localhost:8000/admin`` after starting the development
server.  You must be logged in as a user with ``is_staff=True``.

Create a staff / superuser account:

.. code-block:: bash

   python viperctl.py createsuperuser

----

Standalone / Single-file Apps
-------------------------------

``examples/todoapp/`` is a self-contained single-file app that wires up the
admin manually instead of using ``viperctl.py``.

**Step 1 — Settings** (``examples/todoapp/settings.py``):

.. code-block:: python

   import dataclasses, os
   from datetime import timedelta
   from openviper.conf.settings import Settings

   @dataclasses.dataclass(frozen=True)
   class MiniAppSettings(Settings):
       PROJECT_NAME: str = "miniapp"
       DEBUG: bool = bool(int(os.environ.get("DEBUG", "1")))
       DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
       SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key")

       INSTALLED_APPS: tuple = ("openviper.auth", "openviper.admin")
       MIDDLEWARE: tuple = (
           "openviper.middleware.auth.AuthenticationMiddleware",
           "openviper.admin.middleware.AdminMiddleware",
       )
       TEMPLATES_DIR: str = "templates"
       SESSION_COOKIE_NAME: str = "sessionid"
       SESSION_TIMEOUT: timedelta = timedelta(hours=24)

**Step 2 — Bootstrap and mount the admin router** (``examples/todoapp/app.py``):

.. code-block:: python

   import os, sys
   sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
   os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "settings")

   import openviper
   openviper.setup(force=True)

   from openviper import OpenViper
   from openviper.admin import get_admin_site
   from openviper.db import init_db
   import models   # registers tables with SQLAlchemy metadata
   import admin    # triggers @register(...) calls

   app = OpenViper(title="Miniapp — Todo", version="1.0.0")
   app.include_router(get_admin_site(), prefix="/admin")

   @app.on_startup
   async def startup() -> None:
       await init_db()

**Step 3 — Run it**:

.. code-block:: bash

   cd examples/todoapp
   openviper run app

.. note::
   ``openviper.setup(force=True)`` is required in standalone scripts so that
   settings are loaded with the correct ``OPENVIPER_SETTINGS_MODULE`` before any
   OpenViper components are imported.

----

Registering Models
-------------------

Create an ``admin.py`` file in your app and register models with the
``@register`` decorator.

.. rubric:: Minimal registration (examples/todoapp/admin.py)

.. code-block:: python

   from openviper.admin import ModelAdmin, register
   from openviper.auth import get_user_model
   from models import Todo

   User = get_user_model()


   @register(User)
   class UserAdmin(ModelAdmin):
       list_display    = ["id", "username", "email", "is_active", "is_staff", "created_at"]
       search_fields   = ["username", "email"]
       list_filter     = ["is_active", "is_staff", "is_superuser"]
       readonly_fields = ["created_at"]
       exclude         = ["password"]
       ordering        = ["-created_at"]


   @register(Todo)
   class TodoAdmin(ModelAdmin):
       list_display    = ["id", "title", "done", "owner_id", "created_at"]
       list_filter     = ["done"]
       search_fields   = ["title"]
       readonly_fields = ["created_at"]
       ordering        = ["-created_at"]

.. rubric:: Richer registration with actions and child tables (examples/ai_moderation_platform/posts/admin.py)

.. code-block:: python

   from openviper.admin import ActionResult, ChildTable, ModelAdmin, action, register
   from .models import Post, Comment, PostReport
   from moderation.models import ModerationLog


   class PostReportInline(ChildTable):
       model  = PostReport
       fields = ["reported_by", "reason"]


   class ModerationLogInline(ChildTable):
       model        = ModerationLog
       fk_name      = "object_id"
       extra_filters = {"content_type": "post"}
       fields       = ["classification", "confidence", "reason", "reviewed"]


   @register(Post)
   class PostAdmin(ModelAdmin):
       list_display  = ["id", "title", "author", "is_hidden", "likes_count", "created_at"]
       list_filter   = ["is_hidden", "created_at"]
       search_fields = ["title", "content"]
       actions       = ["mark_as_hidden", "mark_as_visible", "run_moderation"]
       child_tables  = [PostReportInline, ModerationLogInline]

       @action(description="Mark selected posts as hidden")
       async def mark_as_hidden(self, queryset, request):
           count = await queryset.update(is_hidden=True)
           return ActionResult(success=True, count=count,
                               message=f"Hidden {count} posts.")

       @action(description="Mark selected posts as visible")
       async def mark_as_visible(self, queryset, request):
           count = await queryset.update(is_hidden=False)
           return ActionResult(success=True, count=count,
                               message=f"Revealed {count} posts.")

       @action(description="Run AI moderation on selected posts")
       async def run_moderation(self, queryset, request):
           from posts.tasks import moderate
           posts = await queryset.all()
           for post in posts:
               moderate.send(post.id)
           return ActionResult(success=True, count=len(posts),
                               message=f"Queued moderation for {len(posts)} posts.")

``ModelAdmin`` options reference:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Description
   * - ``list_display``
     - Columns shown in the list view
   * - ``list_display_links``
     - Which ``list_display`` columns link to the detail view (default: first column)
   * - ``list_filter``
     - Sidebar filter facets
   * - ``list_editable``
     - Fields editable inline in the list view
   * - ``search_fields``
     - Fields searched by the search bar (``ILIKE '%query%'``)
   * - ``ordering``
     - Default sort order (prefix ``-`` for descending)
   * - ``readonly_fields``
     - Fields rendered as plain text (not editable)
   * - ``exclude``
     - Fields hidden from the edit form
   * - ``list_per_page``
     - Rows per page (default ``50``)
   * - ``actions``
     - List of bulk-action method names
   * - ``fieldsets``
     - Group the edit form into labelled sections
   * - ``sensitive_fields``
     - Fields excluded from API responses (default: ``["password"]``)
   * - ``child_tables``
     - Inline ``ChildTable`` classes for related models
   * - ``save_on_top``
     - Show the save button at the top of the form (default ``False``)
   * - ``preserve_filters``
     - Keep list-view filters when navigating back (default ``True``)

----

Auto-Discovery
---------------

Admin modules are discovered automatically from ``INSTALLED_APPS``.  OpenViper
imports ``<app>.admin`` for every installed app at startup.

In ``examples/ai_moderation_platform`` each sub-app (``posts``, ``moderation``,
``users``) has its own ``admin.py`` that is discovered automatically because
those apps are listed in ``INSTALLED_APPS``:

.. code-block:: python

   # ai_moderation_platform/ai_moderation_platform/settings.py
   INSTALLED_APPS = (
       "openviper.auth",
       "openviper.admin",
       "posts",
       "moderation",
       "users",
   )

As long as ``posts/admin.py`` exists and calls ``@register(Post)``, the model
appears in the admin — no explicit wiring needed.

----

Admin API Endpoints
--------------------

.. list-table::
   :header-rows: 1
   :widths: 10 45 45

   * - Method
     - Endpoint
     - Description
   * - ``GET``
     - ``/admin/api/models/``
     - All registered models grouped by app
   * - ``GET``
     - ``/admin/api/{app}/{model}/``
     - Paginated list view
   * - ``POST``
     - ``/admin/api/{app}/{model}/``
     - Create a new instance
   * - ``GET``
     - ``/admin/api/{app}/{model}/{id}/``
     - Retrieve single instance
   * - ``PUT``
     - ``/admin/api/{app}/{model}/{id}/``
     - Full update
   * - ``PATCH``
     - ``/admin/api/{app}/{model}/{id}/``
     - Partial update
   * - ``DELETE``
     - ``/admin/api/{app}/{model}/{id}/``
     - Delete instance
   * - ``POST``
     - ``/admin/api/{app}/{model}/bulk-action/``
     - Execute a bulk action on selected IDs

All endpoints require ``is_staff=True`` (enforced by
:class:`~openviper.admin.middleware.AdminMiddleware`).

----

Bulk Actions
-------------

The ``@action`` decorator (used in ``examples/ai_moderation_platform/posts/admin.py``
above) gives you full control over label, confirmation, and permissions:

.. code-block:: python

   from openviper.admin import ActionResult, action, register
   from .models import Post

   @register(Post)
   class PostAdmin(ModelAdmin):
       actions = ["run_moderation"]

       @action(description="Run AI moderation on selected posts")
       async def run_moderation(self, queryset, request):
           from posts.tasks import moderate
           posts = await queryset.all()
           for post in posts:
               moderate.send(post.id)   # enqueue Dramatiq task
           return ActionResult(
               success=True,
               count=len(posts),
               message=f"Queued moderation for {len(posts)} posts.",
           )

The ``mark_as_hidden`` / ``mark_as_visible`` actions from the same file show the
simpler pattern — ``queryset.update()`` returns the affected row count directly:

.. code-block:: python

   @action(description="Mark selected posts as hidden")
   async def mark_as_hidden(self, queryset, request):
       count = await queryset.update(is_hidden=True)
       return ActionResult(success=True, count=count,
                           message=f"Hidden {count} posts.")

----

Filtering and Search
---------------------

From ``examples/todoapp/admin.py``:

.. code-block:: python

   @register(Todo)
   class TodoAdmin(ModelAdmin):
       list_filter   = ["done"]          # sidebar checkbox filter on the done field
       search_fields = ["title"]         # ILIKE search across title

From ``examples/ai_moderation_platform/posts/admin.py``:

.. code-block:: python

   @register(Post)
   class PostAdmin(ModelAdmin):
       list_filter   = ["is_hidden", "created_at"]
       search_fields = ["title", "content"]   # full-text search across two fields

----

Unregistering Models
---------------------

.. code-block:: python

   from openviper.admin.registry import admin_registry
   from posts.models import Post

   admin_registry.unregister(Post)

----

History Tracking
-----------------

The admin records every create, update, and delete in an audit log
(``openviper.admin.history``). Each entry stores the action type, the user
who performed it, a JSON snapshot of changed fields, and a timestamp.  The
**History** tab on the object detail view surfaces this automatically.

.. code-block:: python

   from openviper.admin.history import get_history_for_object

   entries = await get_history_for_object(post)
   for entry in entries:
       print(entry.action, entry.user, entry.changed_fields, entry.created_at)

----

Role-Based Visibility
----------------------

Override ``get_queryset()`` to restrict which rows a user can see:

.. code-block:: python

   # Only the post author can see their own posts in the admin.
   @register(Post)
   class PostAdmin(ModelAdmin):
       def get_queryset(self):
           from openviper.core.context import get_current_user
           user = get_current_user()
           if user and not user.is_superuser:
               return Post.objects.filter(author_id=user.id)
           return Post.objects.all()

----

Admin Dashboard Capabilities
------------------------------

The Vue-based admin SPA provides:

* **Model list views** — pagination, sorting, search, and facet filters
* **Detail / edit forms** — generated automatically from model fields
* **Bulk action** execution — select rows + action drop-down
* **Child tables / inlines** — related model rows embedded in the detail view
  (e.g. ``PostReportInline`` and ``ModerationLogInline`` in the AI moderation example)
* **Change history** per instance — audit trail with field-level diffs
* **App grouping** in the sidebar navigation
* **Dark/light mode** toggle

The SPA assets are bundled and served statically from
``openviper/admin/static/admin/`` via
:class:`~openviper.staticfiles.handlers.StaticFilesMiddleware`.
