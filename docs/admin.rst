.. _admin:

Admin Panel
===========

The ``openviper.admin`` package provides a fully-featured, auto-generated
administration interface for OpenViper models.  Mount it at ``/admin`` in
``routes.py`` and all registered models are immediately accessible through
a React-based SPA backed by a REST API.

Overview
--------

The admin panel is built around three components:

1. **ModelAdmin** — per-model display and behavior configuration.
2. **AdminRegistry** — central registry that maps model classes to their
   ``ModelAdmin`` instances.
3. **Admin Site** — the router factory (``get_admin_site()``) that mounts
   the API and SPA at a given URL prefix.

Models are registered in ``admin.py`` inside each installed app and
auto-discovered when the admin site is first accessed.

Key Classes & Functions
-----------------------

.. py:class:: openviper.admin.options.ModelAdmin(model_class)

   Configuration class for admin model behavior.  Subclass it to customize
   how a model appears in the admin panel.

   **List view attributes:**

   .. py:attribute:: list_display
      :type: list[str]

      Field names shown as columns in the list view.  Defaults to ``id``
      plus the first four fields.

   .. py:attribute:: list_display_links
      :type: list[str] | None

      Fields that are rendered as links to the detail view.  Defaults to
      the first field in ``list_display``.

   .. py:attribute:: list_filter
      :type: list[str]

      Fields shown in the sidebar filter panel.

   .. py:attribute:: list_editable
      :type: list[str]

      Fields that can be edited inline in the list view (without opening
      the detail form).

   .. py:attribute:: search_fields
      :type: list[str]

      Fields searched when the admin search box is used.

   .. py:attribute:: ordering
      :type: str | list[str] | None

      Default ordering for the list view.  Prefix with ``-`` for descending.
      Defaults to ``["-id"]``.

   .. py:attribute:: list_per_page
      :type: int

      Rows per page in the list view (default: 25).

   .. py:attribute:: list_max_show_all
      :type: int

      Maximum rows shown when "Show all" is clicked (default: 200).

   .. py:attribute:: date_hierarchy
      :type: str | None

      A ``DateTimeField`` name used to drill down by year/month/day.

   .. py:attribute:: list_select_related
      :type: list[str] | bool

      FK fields to eager-load in the list view via ``select_related``.
      Set to ``True`` to auto-detect from FK fields in ``list_display``.

   **Form view attributes:**

   .. py:attribute:: fields
      :type: list[str] | None

      Explicit list of fields shown in the create/edit form.  When
      ``None`` all non-excluded, non-id fields are shown.

   .. py:attribute:: exclude
      :type: list[str] | None

      Fields to hide from the form (alternative to ``fields``).

   .. py:attribute:: readonly_fields
      :type: list[str]

      Fields displayed in the form but not editable.

   .. py:attribute:: fieldsets
      :type: list[tuple[str | None, dict]]

      Grouped form layout: list of ``(title, {"fields": [...], "classes": [...], "description": "..."})``
      tuples.  Set ``title=None`` for an untitled group.

   .. py:attribute:: form_fields
      :type: dict[str, dict]

      Per-field widget overrides, e.g.
      ``{"body": {"widget": "textarea", "rows": 10}}``.

   .. py:attribute:: list_display_styles
      :type: dict[str, str]

      Per-column CSS class overrides for list view cells.

   .. py:attribute:: sensitive_fields
      :type: list[str]

      Fields **never** exposed in API responses (default: ``["password"]``).
      Extend to include tokens, secrets, API keys, etc.

   **Actions:**

   .. py:attribute:: actions
      :type: list[Callable]

      List of callables (or method name strings) available as batch
      actions in the list view.  The built-in ``delete_selected`` action
      is always available.

   .. py:attribute:: actions_on_top
      :type: bool

      Show the action bar above the list (default: ``True``).

   .. py:attribute:: actions_on_bottom
      :type: bool

      Show the action bar below the list (default: ``False``).

   **Inlines:**

   .. py:attribute:: inlines
      :type: list[type[InlineModelAdmin]]

      Inline model admin classes for nested editing of related objects.

   .. py:attribute:: child_tables
      :type: list[type[ChildTable]]

      Alias for ``inlines`` using the tabular layout.

   **UI options:**

   .. py:attribute:: save_on_top
      :type: bool

      Show save buttons at the top of the form (default: ``False``).

   .. py:attribute:: preserve_filters
      :type: bool

      Keep current list filters active after editing (default: ``True``).

   **Permission methods:**

   .. py:method:: has_view_permission(request, obj=None) -> bool
   .. py:method:: has_add_permission(request) -> bool
   .. py:method:: has_change_permission(request, obj=None) -> bool
   .. py:method:: has_delete_permission(request, obj=None) -> bool

      All return ``True`` for staff or superuser by default.  Override to
      add object-level permission logic.

   **CRUD methods:**

   .. py:method:: save_model(request, obj, form_data, change=False) -> Awaitable[Model]

      Apply *form_data* to *obj* and call ``obj.save()``.  Override to add
      pre/post-save side effects.

   .. py:method:: delete_model(request, obj) -> Awaitable[None]

      Call ``obj.delete()``.  Override to add pre-delete logic.

.. py:class:: openviper.admin.options.InlineModelAdmin(parent_model)

   Configuration for inline (nested) model editing.

   .. py:attribute:: model
      :type: type[Model]

      The related model class.  **Required.**

   .. py:attribute:: fk_name
      :type: str | None

      Name of the FK field on the inline model pointing back to the
      parent.  Auto-detected when there is exactly one FK.

   .. py:attribute:: fields
      :type: list[str] | None

      Fields shown in the inline form.  Defaults to all model fields.

   .. py:attribute:: exclude
      :type: list[str] | None

      Fields to hide.

   .. py:attribute:: readonly_fields
      :type: list[str]

      Read-only fields.

   .. py:attribute:: extra
      :type: int

      Number of blank extra rows (default: 3).

   .. py:attribute:: max_num
      :type: int | None

      Maximum number of inline objects.

   .. py:attribute:: min_num
      :type: int | None

      Minimum number of inline objects.

   .. py:attribute:: can_delete
      :type: bool

      Show delete checkbox on each inline row (default: ``True``).

.. py:class:: openviper.admin.options.TabularInline(parent_model)

   Subclass of :class:`InlineModelAdmin` rendered as a horizontal table.

.. py:class:: openviper.admin.options.StackedInline(parent_model)

   Subclass of :class:`InlineModelAdmin` rendered as vertical cards.

.. py:class:: openviper.admin.options.ChildTable(parent_model)

   Alias for :class:`TabularInline`.

.. py:class:: openviper.admin.registry.AdminRegistry

   Central registry for admin-managed models.

   .. py:method:: register(model, admin_class=None)

      Register *model* with an optional *admin_class*.  Uses the default
      :class:`ModelAdmin` when *admin_class* is ``None``.

   .. py:method:: unregister(model)

      Remove a model from the registry.

   .. py:method:: is_registered(model) -> bool

      Return ``True`` if *model* is registered.

   .. py:method:: get_admin(model) -> ModelAdmin

      Return the :class:`ModelAdmin` instance for *model*.

.. py:function:: openviper.admin.site.get_admin_site() -> Router

   Create and return the complete admin site router, including:

   - REST API routes at ``/api/``
   - Static asset serving at ``/assets/`` (DEBUG only)
   - SPA fallback for all other routes

Example Usage
-------------

.. seealso::

   Working projects that use the admin panel:

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ — simple admin with ``@register``, ``list_display``, ``search_fields``
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — custom actions, ``ChildTable`` inlines, multi-app admin
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — ``unregister`` / re-register pattern, ``UserRoleInline``

Registering a Model
~~~~~~~~~~~~~~~~~~~~

Create ``myapp/admin.py``:

.. code-block:: python

    from openviper.admin import register, ModelAdmin
    from myapp.models import Post, Comment

    @register(Post)
    class PostAdmin(ModelAdmin):
        list_display = ["title", "author", "is_published", "created_at"]
        list_display_links = ["title"]
        list_filter = ["is_published", "created_at"]
        list_editable = ["is_published"]
        search_fields = ["title", "body"]
        ordering = "-created_at"
        list_per_page = 50
        readonly_fields = ["created_at", "updated_at"]
        sensitive_fields = ["password", "internal_token"]
        fieldsets = [
            ("Content", {"fields": ["title", "body"]}),
            ("Publishing", {
                "fields": ["author", "is_published"],
                "description": "Controls when the post is visible",
            }),
            ("Timestamps", {
                "fields": ["created_at", "updated_at"],
                "classes": ["collapse"],
            }),
        ]
        date_hierarchy = "created_at"
        list_select_related = ["author"]   # or True for auto-detect

    @register(Comment)
    class CommentAdmin(ModelAdmin):
        pass

Mounting the Admin Site
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # routes.py
    from openviper.admin.site import get_admin_site

    route_paths = [
        ("/", main_router),
        ("/admin", get_admin_site()),
    ]

Now visit ``http://localhost:8000/admin/`` to access the admin panel.

Custom Actions
~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.admin import register, ModelAdmin, action, ActionResult
    from myapp.models import Post

    @register(Post)
    class PostAdmin(ModelAdmin):
        actions = ["publish_posts", "archive_posts"]
        list_display = ["title", "is_published", "is_archived"]

        @action(description="Publish selected posts")
        async def publish_posts(self, queryset, request):
            count = await queryset.update(is_published=True)
            return ActionResult(success=True, count=count, message=f"Published {count} posts.")

        @action(description="Archive selected posts")
        async def archive_posts(self, queryset, request):
            count = await queryset.update(is_archived=True, is_published=False)
            return ActionResult(success=True, count=count, message=f"Archived {count} posts.")

Inline Editing
~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.admin import register, ModelAdmin, ChildTable
    from openviper.admin.options import StackedInline
    from myapp.models import Post, Comment, Tag

    class CommentInline(ChildTable):
        model = Comment
        fk_name = "post"       # FK on Comment pointing to Post
        fields = ["author", "body", "created_at"]
        readonly_fields = ["created_at"]
        extra = 1
        max_num = 20
        can_delete = True

    class TagInline(StackedInline):
        model = Tag
        fields = ["name", "slug"]

    @register(Post)
    class PostAdmin(ModelAdmin):
        inlines = [CommentInline, TagInline]

Overriding Permissions
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @register(Post)
    class PostAdmin(ModelAdmin):
        def has_delete_permission(self, request=None, obj=None):
            # Only superusers can delete posts
            if request is None:
                return True
            user = getattr(request, "user", None)
            return getattr(user, "is_superuser", False)

        def has_change_permission(self, request=None, obj=None):
            # Users can only edit their own posts
            if request is None or obj is None:
                return True
            user = getattr(request, "user", None)
            if getattr(user, "is_superuser", False):
                return True
            return obj.author_id == getattr(user, "pk", None)

Overriding save_model
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @register(Post)
    class PostAdmin(ModelAdmin):
        async def save_model(self, request, obj, form_data, change=False):
            if not change:
                # Set author automatically on create
                obj.author_id = request.user.pk
            return await super().save_model(request, obj, form_data, change)

Sensitive Fields
~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.admin import register, ModelAdmin
    from openviper.auth import get_user_model

    User = get_user_model()

    @register(User)
    class UserAdmin(ModelAdmin):
        list_display = ["id", "username", "email", "is_active"]
        # 'password' is hidden by default; extend for other secrets:
        sensitive_fields = [
            "password",
            "api_key",
            "refresh_token",
        ]
        readonly_fields = ["created_at", "last_login"]
