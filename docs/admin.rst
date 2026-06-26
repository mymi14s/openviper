.. _admin:

Admin Panel
===========

The ``openviper.admin`` package provides a fully-featured, auto-generated
administration interface for OpenViper models.  Mount it at ``/admin`` in
``routes.py`` and all registered models are immediately accessible through
a Vue 3 SPA backed by a REST API.

Overview
--------

The admin panel is built around four components:

1. **ModelAdmin** - per-model display and behavior configuration.
2. **AdminRegistry** - central registry that maps model classes to their
   ``ModelAdmin`` instances.
3. **Admin Site** - the router factory (``get_admin_site()``) that mounts
   the API and SPA at a given URL prefix.
4. **AdminMiddleware** - ASGI middleware that enforces authentication on
   ``/admin/api/`` routes.

Models are registered in ``admin.py`` inside each installed app and
auto-discovered when the admin site is first accessed.

Key Classes & Functions
-----------------------

.. py:class:: openviper.admin.options.ModelAdmin(model_class)

   Configuration class for admin model behavior.  Subclass it to customize
   how a model appears in the admin panel.

   **List view attributes:**

   .. py:attribute:: list_display
      :type: list[str] | None

      Field names shown as columns in the list view.  Defaults to ``id``
      plus the first four fields.

   .. py:attribute:: list_display_links
      :type: list[str] | None

      Fields that are rendered as links to the detail view.  Defaults to
      the first field in ``list_display``.

   .. py:attribute:: list_filter
      :type: list[str] | None

      Fields shown in the sidebar filter panel.

   .. py:attribute:: list_editable
      :type: list[str] | None

      Fields that can be edited inline in the list view (without opening
      the detail form).

   .. py:attribute:: search_fields
      :type: list[str] | None

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
      :type: list[str] | bool | None

      FK fields to eager-load in the list view via ``select_related``.
      Set to ``True`` to auto-detect from FK fields in ``list_display``.

   .. py:attribute:: list_display_styles
      :type: dict[str, str] | None

      Per-column CSS class overrides for list view cells.

   .. py:attribute:: show_full_result_count
      :type: bool

      Whether to show the full count of matching rows (default: ``True``).

   **Form view attributes:**

   .. py:attribute:: fields
      :type: list[str] | None

      Explicit list of fields shown in the create/edit form.  When
      ``None`` all non-excluded, non-id fields are shown.

   .. py:attribute:: exclude
      :type: list[str] | None

      Fields to hide from the form (alternative to ``fields``).

   .. py:attribute:: readonly_fields
      :type: list[str] | None

      Fields displayed in the form but not editable.

   .. py:attribute:: fieldsets
      :type: list[tuple[str | None, dict]] | None

      Grouped form layout: list of ``(title, {"fields": [...], "classes": [...], "description": "..."})``
      tuples.  Set ``title=None`` for an untitled group.

   .. py:attribute:: form_fields
      :type: dict[str, dict] | None

      Per-field widget overrides, e.g.
      ``{"body": {"widget": "textarea", "rows": 10}}``.

   .. py:attribute:: sensitive_fields
      :type: list[str] | None

      Fields **never** exposed in API responses (default: ``["password"]``).
      Extend to include tokens, secrets, API keys, etc.

   **Actions:**

   .. py:attribute:: actions
      :type: list[Callable] | None

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

   .. py:method:: is_intrinsically_readonly(field) -> bool

      Return ``True`` if a field is auto-managed (AutoField, auto_now,
      auto_now_add) and should not be edited on create.

   .. py:method:: action_delete_selected(request, queryset) -> Awaitable[int]

      Built-in action: delete all objects in the queryset.  Returns the
      count of deleted objects.

   **Dynamic getter methods:**

   Each list/form attribute has a corresponding ``get_*`` method that
   accepts an optional ``request`` (and sometimes ``obj``) for
   request-aware overrides:

   - ``get_list_display(request=None)``
   - ``get_list_display_links(request=None)``
   - ``get_list_filter(request=None)``
   - ``get_search_fields(request=None)``
   - ``get_ordering(request=None)``
   - ``get_list_select_related(request=None)``
   - ``get_fields(request=None, obj=None)``
   - ``get_exclude(request=None, obj=None)``
   - ``get_sensitive_fields(request=None, obj=None)``
   - ``get_readonly_fields(request=None, obj=None)``
   - ``get_fieldsets(request=None, obj=None)``
   - ``get_form_field_config(field_name)``
   - ``get_actions(request=None)``
   - ``get_model_info(request=None)``
   - ``get_child_tables_info()``

.. py:class:: openviper.admin.options.InlineModelAdmin(parent_model)

   Configuration for inline (nested) model editing.

   .. py:attribute:: model
      :type: type[Model]

      The related model class.  **Required.**

   .. py:attribute:: fk_name
      :type: str | None

      Name of the FK field on the inline model pointing back to the
      parent.  Auto-detected when there is exactly one FK.

   .. py:attribute:: extra_filters
      :type: dict | None

      Additional filters applied to the inline queryset.

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

   .. py:attribute:: show_change_link
      :type: bool

      Show a link to the full edit form for each inline row
      (default: ``False``).

.. py:class:: openviper.admin.options.TabularInline(parent_model)

   Subclass of :class:`InlineModelAdmin` rendered as a horizontal table.

.. py:class:: openviper.admin.options.StackedInline(parent_model)

   Subclass of :class:`InlineModelAdmin` rendered as vertical cards.

.. py:class:: openviper.admin.options.ChildTable(parent_model)

   Alias for :class:`TabularInline`.

.. py:class:: openviper.admin.registry.AdminRegistry

   Central registry for admin-managed models.

   .. py:method:: register(model_class, admin_class=None)

      Register *model_class* with an optional *admin_class*.  Uses the
      default :class:`ModelAdmin` when *admin_class* is ``None``.
      Raises :exc:`AlreadyRegistered` if the model is already registered.

   .. py:method:: unregister(model_class)

      Remove a model from the registry.
      Raises :exc:`NotRegistered` if the model is not registered.

   .. py:method:: is_registered(model_class) -> bool

      Return ``True`` if *model_class* is registered.

   .. py:method:: get_model_admin(model_class) -> ModelAdmin | None

      Return the :class:`ModelAdmin` instance for *model_class*, or
      ``None`` if not registered.

   .. py:method:: get_model_admin_by_name(model_name) -> ModelAdmin

      Return the :class:`ModelAdmin` instance by model class name
      (case-insensitive).  Raises :exc:`NotRegistered` if not found.

   .. py:method:: get_model_admin_by_app_and_name(app_label, model_name) -> ModelAdmin

      Return the :class:`ModelAdmin` instance by app label and model name.
      Raises :exc:`NotRegistered` if not found.

   .. py:method:: get_model_by_name(model_name) -> type[Model]

      Return the model class by name (case-insensitive).
      Raises :exc:`NotRegistered` if not found.

   .. py:method:: get_model_by_app_and_name(app_label, model_name) -> type[Model]

      Return the model class by app label and model name.
      Raises :exc:`NotRegistered` if not found.

   .. py:method:: get_all_models() -> list[tuple[type[Model], ModelAdmin]]

      Return all registered non-abstract models with their admin
      configurations.

   .. py:method:: get_models_grouped_by_app() -> dict[str, list[tuple[type[Model], ModelAdmin]]]

      Return registered models grouped by their app name.

   .. py:method:: auto_discover_from_installed_apps() -> None

      Import ``admin.py`` from each app in ``INSTALLED_APPS``.
      Idempotent - only runs once.

   .. py:method:: discover_from_app(app_name) -> None

      Import and register models from a single app's ``admin.py`` module.

.. py:exception:: openviper.admin.registry.AlreadyRegistered(ValueError)

   Raised when a model is registered more than once.

.. py:exception:: openviper.admin.registry.NotRegistered(ValueError)

   Raised when accessing an unregistered model.

.. py:function:: openviper.admin.site.get_admin_site() -> Router

   Create and return the complete admin site router, including:

   - REST API routes at ``/api/``
   - Extension manifest at ``/api/extensions/``
   - Extension file serving at ``/extensions/{app_name}/{path}`` (DEBUG only)
   - Static asset serving at ``/assets/{path}`` (DEBUG only)
   - SPA fallback for all other routes

   Calls :func:`~openviper.admin.discovery.autodiscover` before
   building the router.

Actions System
--------------

.. py:class:: openviper.admin.actions.AdminAction

   Base class for admin batch actions.  Subclass to create custom
   actions that can be performed on multiple selected objects.

   .. py:attribute:: name
      :type: str

      Internal name for the action (defaults to lowercase class name).

   .. py:attribute:: description
      :type: str

      Human-readable description shown in the UI.

   .. py:attribute:: confirm_message
      :type: str | None

      Optional confirmation prompt displayed before execution.

   .. py:attribute:: permissions
      :type: list[str]

      Required permissions to execute this action.

   .. py:method:: execute(queryset, request, model_admin=None) -> Awaitable[ActionResult]

      Execute the action on the queryset.  Must be overridden.

   .. py:method:: has_permission(request) -> bool

      Check if the user has permission to run this action.

   .. py:method:: get_info() -> dict

      Return action metadata for API responses.

.. py:class:: openviper.admin.actions.DeleteSelectedAction

   Built-in action to delete selected objects.  Registered as
   ``"delete_selected"`` in the global action registry.

.. py:data:: openviper.admin.actions.action_registry

   Global ``dict[str, type[AdminAction]]`` mapping action names to their
   classes.

.. py:function:: openviper.admin.actions.register_action(action_class) -> type[AdminAction]

   Register a custom action class with the global registry.  Can be
   used as a decorator.

.. py:function:: openviper.admin.actions.get_action(name) -> AdminAction | None

   Return an action instance by name, or ``None`` if not found.

.. py:function:: openviper.admin.actions.get_available_actions(request) -> list[AdminAction]

   Return all actions the current user has permission to execute.

.. py:function:: openviper.admin.actions.action(description=None, confirm_message=None, permissions=None) -> Callable

   Decorator to create an :class:`AdminAction` from a function.  The
   decorated function may accept ``(queryset, request)`` or
   ``(model_admin, queryset, request)`` depending on the number of
   parameters.  Async functions are awaited automatically.

.. py:class:: openviper.admin.actions.ActionResult

   Dataclass returned by action execution.

   .. py:attribute:: success
      :type: bool

      Whether the action completed successfully.

   .. py:attribute:: count
      :type: int

      Number of objects affected.

   .. py:attribute:: message
      :type: str

      Human-readable result message.

   .. py:attribute:: errors
      :type: list[str] | None

      List of error messages, if any.

Change History
--------------

.. py:class:: openviper.admin.history.ChangeHistory

   Model for tracking changes to admin-managed objects.  Stores a record
   of every create, update, and delete operation performed through the
   admin interface.

   .. py:attribute:: model_name
      :type: CharField(max_length=100, db_index=True)

   .. py:attribute:: object_id
      :type: CharField(max_length=255, db_index=True)

   .. py:attribute:: object_repr
      :type: CharField(max_length=255)

   .. py:attribute:: action
      :type: CharField(max_length=10)

      One of ``"add"``, ``"change"``, or ``"delete"``.

   .. py:attribute:: changed_fields
      :type: TextField(null=True)

      JSON-encoded dict of field changes.

   .. py:attribute:: changed_by_id
      :type: CharField(max_length=255, null=True, db_index=True)

   .. py:attribute:: changed_by_username
      :type: CharField(max_length=150, null=True)

   .. py:attribute:: change_time
      :type: DateTimeField(auto_now_add=True)

   .. py:attribute:: change_message
      :type: TextField(null=True)

   .. py:method:: get_changed_fields_dict() -> dict

      Parse ``changed_fields`` JSON to a dict.

   .. py:classmethod:: get_for_object(model_name, object_id, limit=50) -> list[ChangeHistory]

      Get change history for a specific object, ordered by most recent
      first.

.. py:class:: openviper.admin.history.ChangeAction(StrEnum)

   Enum of change action types: ``ADD``, ``CHANGE``, ``DELETE``.

.. py:function:: openviper.admin.history.log_change(model_name, object_id, action, changes=None, user=None, object_repr=None, message=None) -> Awaitable[ChangeHistory]

   Create a change history record.

.. py:function:: openviper.admin.history.get_change_history(model_name, object_id, limit=50) -> Awaitable[list[ChangeHistory]]

   Get change history for an object, most recent first.

.. py:function:: openviper.admin.history.get_recent_activity(limit=20) -> Awaitable[list[ChangeHistory]]

   Get recent change activity across all models.

.. py:function:: openviper.admin.history.compute_changes(old_data, new_data) -> dict[str, dict]

   Compute the differences between old and new field values.  Returns a
   dict mapping field names to ``{"old": ..., "new": ...}`` dicts.

.. py:function:: openviper.admin.history.normalize_for_compare(val) -> Any

   Normalize a value for change comparison.  Converts
   datetime/date/time objects to ISO strings so that comparisons between
   ORM-returned objects and coerced request values do not raise
   ``TypeError``.

Field Mapping
-------------

.. py:data:: openviper.admin.fields.FIELD_COMPONENT_MAP

   ``dict[str, str]`` mapping OpenViper field class names to Vue
   component types (e.g. ``"CharField"`` -> ``"text"``,
   ``"ForeignKey"`` -> ``"foreignkey"``).

.. py:function:: openviper.admin.fields.get_field_component_type(field) -> str

   Return the Vue component type for a model field.  Fields with
   ``choices`` always return ``"select"``.

.. py:function:: openviper.admin.fields.get_filter_choices(field) -> list[dict[str, str]]

   Return filter choices for a field, including lazy-loaded
   ``CountryField`` and ``CurrencyField`` data.

.. py:function:: openviper.admin.fields.get_field_widget_config(field) -> dict

   Return widget configuration for a field (required, readonly,
   choices, max_length, step, etc.).

.. py:function:: openviper.admin.fields.get_field_schema(field) -> dict

   Return the full schema dict for a field (type, component, config).

.. py:function:: openviper.admin.fields.get_field_schema_cached(...) -> dict

   LRU-cached version of field schema computation (up to 512 entries).

.. py:function:: openviper.admin.fields.coerce_field_value(field, value) -> Any

   Coerce a raw request value to the correct Python type for a given
   model field.

.. py:function:: openviper.admin.fields.serialize_default(field) -> Any

   Serialize a field's default value for API responses.

Middleware
----------

.. py:class:: openviper.admin.middleware.AdminMiddleware

   ASGI middleware that enforces authentication on ``/admin/api/``
   routes.  Non-HTTP requests and non-admin paths pass through
   unmodified.

   .. py:attribute:: ADMIN_PATH_PREFIX
      :type: str

      Path prefix to protect (default: ``"/admin/api/"``).

   .. py:attribute:: EXEMPT_PATHS
      :type: list[str]

      Paths that skip authentication:

      - ``/admin/api/auth/login/``
      - ``/admin/api/auth/refresh/``
      - ``/admin/api/auth/logout/``
      - ``/admin/api/config/``

   The middleware normalizes request paths (decodes percent-encoding,
   collapses double slashes, rejects path-traversal segments) before
   prefix matching.

Permissions
-----------

.. py:function:: openviper.admin.api.permissions.check_admin_access(request) -> bool

   Return ``True`` if the user is authenticated and has staff or
   superuser status.

.. py:function:: openviper.admin.api.permissions.check_model_permission(request, model_class, action) -> bool

   Check if the user has permission for a model action (``"view"``,
   ``"add"``, ``"change"``, ``"delete"``).  Superusers always pass.
   Staff users pass for basic CRUD.  Falls back to
   ``user.has_perm()`` for granular checks.

.. py:function:: openviper.admin.api.permissions.check_object_permission(request, obj, action) -> bool

   Check if the user has permission for a specific object.  Delegates
   to :func:`check_model_permission` for the object's model class.

.. py:class:: openviper.admin.api.permissions.PermissionChecker(request)

   Object-oriented interface for admin permission checks.

Serialization
-------------

.. py:function:: openviper.admin.api.serializers.serialize_instance(instance, model_admin, include_fields=None) -> dict

   Serialize a model instance to a dict.  Sensitive fields are excluded.

.. py:function:: openviper.admin.api.serializers.serialize_value(value) -> Any

   Serialize a field value for JSON (handles datetime, UUID, Decimal,
   etc.).

.. py:function:: openviper.admin.api.serializers.serialize_for_list(instance, model_admin) -> dict

   Serialize a model instance for list view (only ``list_display``
   fields).

.. py:function:: openviper.admin.api.serializers.serialize_for_detail(instance, model_admin) -> dict

   Serialize a model instance for detail view (all non-sensitive
   fields).

``openviper.admin.api.views``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The REST API module provides CRUD operations, search, filtering, batch
actions, and CSV export for all admin-registered models.  It is mounted
automatically by :func:`~openviper.admin.site.get_admin_site` at
``/admin/api/``.

Key functions include:

.. py:function:: openviper.admin.api.views.sanitize_csv_cell(value) -> str

   Sanitize a cell value for safe CSV export.  Prevents CSV/formula
   injection by prefixing dangerous leading characters (``=``, ``+``,
   ``-``, ``@``, tab, CR) with a single quote.

``openviper.admin.types``
^^^^^^^^^^^^^^^^^^^^^^^^^

Shared structural type aliases for the admin package.

.. py:data:: JsonScalar

   Type alias: ``str | int | float | bool | None``.

.. py:data:: JsonValue

   Recursive type alias for valid JSON values.

.. py:data:: JsonObject

   Shorthand for ``dict[str, JsonValue]``.

Auto-Discovery
--------------

.. py:function:: openviper.admin.discovery.autodiscover() -> None

   Run admin auto-discovery.  Imports ``admin.py`` from all installed
   apps and registers auth models.  Called automatically by
   :func:`get_admin_site`.

.. py:function:: openviper.admin.discovery.discover_admin_modules() -> list[str]

   Discover and import ``admin.py`` from all installed apps.  Returns
   the list of app names where ``admin.py`` was found.

.. py:function:: openviper.admin.discovery.import_admin_module(app_name) -> bool

   Import the ``admin.py`` module from a single app.  Returns ``True``
   if the module was found and imported.

.. py:function:: openviper.admin.discovery.discover_extensions() -> list[dict]

   Discover ``admin_extensions/`` directories from all installed apps
   and collect all ``.js`` files found there.

REST API Reference
------------------

All API endpoints are mounted under ``/admin/api/``.  Authentication
endpoints are exempt from the admin middleware; all others require a
staff or superuser JWT.

**Auth endpoints:**

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Endpoint
     - Method
     - Description
   * - ``/auth/login/``
     - POST
     - Authenticate and receive JWT tokens.  Rate-limited (5 req/min).
   * - ``/auth/logout/``
     - POST
     - Revoke access and refresh tokens.
   * - ``/auth/refresh/``
     - POST
     - Refresh an access token using a valid refresh token.
   * - ``/auth/me/``
     - GET
     - Get current authenticated user info.
   * - ``/auth/change-password/``
     - POST
     - Change the current user's password.  Rate-limited (5 req/min).
   * - ``/auth/change-user-password/{user_id}/``
     - POST
     - Change another user's password (superuser only).  Rate-limited (5 req/min).

.. note::

   Both password-change endpoints rotate the session after a successful
   change.  All other sessions for the affected user are invalidated, and
   a new session cookie is issued for the current request.  This prevents
   session fixation and limits the window of opportunity for stolen session
   cookies.

**Config and dashboard:**

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Endpoint
     - Method
     - Description
   * - ``/config/``
     - GET
     - UI configuration (title, user model, etc.).
   * - ``/dashboard/``
     - GET
     - Dashboard statistics and recent activity.
   * - ``/extensions/``
     - GET
     - JSON manifest of discovered admin extensions.
   * - ``/plugins/``
     - GET
     - List available admin plugins (placeholder).

**Model CRUD (app-scoped routes):**

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Endpoint
     - Method
     - Description
   * - ``/models/``
     - GET
     - List all registered models with admin config.
   * - ``/models/{app}/{model}/``
     - GET
     - Get model configuration and metadata.
   * - ``/models/{app}/{model}/list/``
     - GET
     - List instances with pagination, search, filtering, sorting.
   * - ``/models/{app}/{model}/``
     - POST
     - Create a new instance (with inline children).
   * - ``/models/{app}/{model}/filters/``
     - GET
     - Get available filter options for a model.
   * - ``/models/{app}/{model}/{id}/``
     - GET
     - Get a single instance with model info and fieldsets.
   * - ``/models/{app}/{model}/{id}/``
     - PUT
     - Update an instance (with inline children and change logging).
   * - ``/models/{app}/{model}/{id}/``
     - DELETE
     - Delete an instance (with change logging).
   * - ``/models/{app}/{model}/bulk-action/``
     - POST
     - Execute a batch action on selected IDs.  Rate-limited (10 req/min).
   * - ``/models/{app}/{model}/export/``
     - GET
     - Export instances to CSV (with injection sanitization).
   * - ``/models/{app}/{model}/{id}/history/``
     - GET
     - Get change history for an instance.
   * - ``/models/{app}/{model}/fk-search/``
     - GET
     - ForeignKey autocomplete search.

**Model CRUD (legacy name-only routes):**

These routes use ``{model_name}`` without ``{app_label}`` and resolve
models by name alone.  They support the same operations as the
app-scoped routes above.

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Endpoint
     - Method
     - Description
   * - ``/models/{model}/``
     - GET
     - List instances with pagination, search, filtering.
   * - ``/models/{model}/``
     - POST
     - Create a new instance.
   * - ``/models/{model}/{id}/``
     - GET
     - Get a single instance.
   * - ``/models/{model}/{id}/``
     - PATCH
     - Partially update an instance.
   * - ``/models/{model}/{id}/``
     - DELETE
     - Delete an instance.
   * - ``/models/{model}/bulk-delete/``
     - POST
     - Delete multiple instances by ID.  Rate-limited (10 req/min).
   * - ``/models/{model}/bulk-action/``
     - POST
     - Execute a batch action.  Rate-limited (10 req/min).
   * - ``/models/{model}/search/``
     - GET
     - Search instances (delegates to list).
   * - ``/models/{model}/filters/``
     - GET
     - Get filter options.
   * - ``/models/{model}/export/``
     - POST
     - Export instances to CSV.
   * - ``/models/{model}/{id}/history/``
     - GET
     - Get change history.

**Global search:**

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Endpoint
     - Method
     - Description
   * - ``/search/``
     - GET
     - Search across all registered models.  Rate-limited (30 req/min).

**Query parameters for list endpoints:**

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Parameter
     - Description
   * - ``page``
     - Page number (default: 1).
   * - ``per_page`` / ``page_size``
     - Items per page (default: ``list_per_page``, max: 1000).
   * - ``q``
     - Search query (searches ``search_fields``).
   * - ``sort``
     - Sort field (prefix with ``-`` for descending).
   * - ``filter_{field}``
     - Filter by field value (one per field).

**CSV export security:**

CSV exports sanitize cell values to prevent formula injection in
spreadsheet applications.  Cells starting with ``=``, ``+``, ``-``,
``@``, tab, or carriage-return characters are prefixed with a single
quote to force text-mode rendering.

Decorators
----------

.. py:function:: openviper.admin.decorators.register(*models) -> Callable

   Decorator to register one or more models with the admin site.
   Each model is registered using the global ``admin`` registry
   singleton.

.. py:function:: openviper.admin.unregister(model_class) -> None

   Remove a model from the admin site registry.

Auth Model Auto-Registration
-----------------------------

The ``openviper.admin.auth_admin`` module automatically registers the
following models when :func:`~openviper.admin.discovery.autodiscover` runs:

- **User** - with ``UserAdmin`` (excludes password, read-only dates)
- **Permission** - with ``PermissionAdmin``
- **Role** - with ``RoleAdmin``
- **UserRole** - with ``UserRoleAdmin``
- **RolePermission** - with ``RolePermissionAdmin``
- **ChangeHistory** - with ``ChangeHistoryAdmin`` (read-only: no
  add/edit/delete)

All registrations use ``contextlib.suppress(AlreadyRegistered)`` so they
do not raise errors if the models are already registered by user code.

Example Usage
-------------

.. seealso::

   Working projects that use the admin panel:

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ - simple admin with ``@register``, ``list_display``, ``search_fields``
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - custom actions, ``ChildTable`` inlines, multi-app admin
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - ``unregister`` / re-register pattern, ``UserRoleInline``

Registering a Model
^^^^^^^^^^^^^^^^^^^

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
        list_select_related = ["author"]

    @register(Comment)
    class CommentAdmin(ModelAdmin):
        pass

Mounting the Admin Site
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # routes.py
    from openviper.admin.site import get_admin_site

    route_paths = [
        ("/", main_router),
        ("/admin", get_admin_site()),
    ]

Now visit ``http://localhost:8000/admin/`` to access the admin panel.

Custom Actions
^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^

.. code-block:: python

    from openviper.admin import register, ModelAdmin, ChildTable
    from openviper.admin.options import StackedInline
    from myapp.models import Post, Comment, Tag

    class CommentInline(ChildTable):
        model = Comment
        fk_name = "post"
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
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    @register(Post)
    class PostAdmin(ModelAdmin):
        def has_delete_permission(self, request=None, obj=None):
            if request is None:
                return True
            user = getattr(request, "user", None)
            return getattr(user, "is_superuser", False)

        def has_change_permission(self, request=None, obj=None):
            if request is None or obj is None:
                return True
            user = getattr(request, "user", None)
            if getattr(user, "is_superuser", False):
                return True
            return obj.author_id == getattr(user, "pk", None)

Overriding save_model
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    @register(Post)
    class PostAdmin(ModelAdmin):
        async def save_model(self, request, obj, form_data, change=False):
            if not change:
                obj.author_id = request.user.pk
            return await super().save_model(request, obj, form_data, change)

Sensitive Fields
^^^^^^^^^^^^^^^^

.. code-block:: python

    from openviper.admin import register, ModelAdmin
    from openviper.auth import get_user_model

    User = get_user_model()

    @register(User)
    class UserAdmin(ModelAdmin):
        list_display = ["id", "username", "email", "is_active"]
        sensitive_fields = [
            "password",
            "api_key",
            "refresh_token",
        ]
        readonly_fields = ["created_at", "last_login"]

Unregistering a Model
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from openviper.admin import unregister
    from myapp.models import LegacyModel

    unregister(LegacyModel)

Global Search
^^^^^^^^^^^^^^

The ``/admin/api/search/`` endpoint searches across all registered
models concurrently.  It uses each model's ``search_fields`` (or falls
back to common field names like ``name``, ``title``, ``username``,
``email``) and returns up to 5 results per model, capped at 50 total.

.. code-block:: python

    # Frontend usage
    GET /admin/api/search/?q=john

    # Response
    {
        "results": [
            {"id": 1, "display": "John Doe", "model_name": "user", "app_label": "auth"},
            {"id": 42, "display": "John's Post", "model_name": "post", "app_label": "blog"}
        ]
    }

Admin Extensions
^^^^^^^^^^^^^^^^

Apps can provide drop-in JavaScript extensions for the admin SPA by
creating an ``admin_extensions/`` directory inside the app package.
Only ``.js`` and ``.vue`` files are served.  Extension files are only
available in DEBUG mode.

.. code-block:: text

    myapp/
        admin_extensions/
            dashboard_widget.js
            custom_chart.vue

The extension manifest is available at ``/admin/api/extensions/`` and
individual files at ``/admin/extensions/{app_name}/{path}``.

Authentication Decorator
^^^^^^^^^^^^^^^^^^^^^^^^

All admin API routes are protected by the ``@require_admin`` decorator,
which verifies that the request user is an authenticated admin (staff or
superuser) before the handler runs.  Routes that do not require
authentication (``/auth/login``, ``/auth/logout``, ``/auth/refresh``)
intentionally omit the decorator.

.. py:function:: openviper.admin.api.permissions.require_admin(func)

   Decorator that enforces admin access on an async route handler.

   Raises:
       PermissionDenied: If the request user is not an authenticated admin.

.. code-block:: python

    from openviper.admin.api.permissions import require_admin

    @router.get("/models/")
    @require_admin
    async def list_models(request: Request) -> JSONResponse:
        ...
