"""ModelAdmin options class - configuration for model admin behavior.

The ModelAdmin class provides configuration options for
how models are displayed and edited in the admin panel.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from openviper.admin.fields import get_field_schema

if TYPE_CHECKING:
    from openviper.db.models import Model
    from openviper.http.request import Request

logger = logging.getLogger(__name__)


class ModelAdmin:
    """Configuration class for admin model behavior. Subclass this to customize how a model appears in the admin panel.

    Example::

        class PostAdmin(ModelAdmin):
            list_display = ["title", "author", "created_at", "is_published"]
            list_filter = ["is_published", "created_at"]
            search_fields = ["title", "body"]
            readonly_fields = ["created_at", "updated_at"]
            fieldsets = [
                ("Content", {"fields": ["title", "body"]}),
                ("Meta", {"fields": ["author", "is_published"], "classes": ["collapse"]}),
            ]
    """

    # List view configuration
    list_display: list[str] = []
    list_display_links: list[str] | None = None
    list_filter: list[str] = []
    list_editable: list[str] = []
    search_fields: list[str] = []
    ordering: str | list[str] | None = None
    list_per_page: int = 25
    list_max_show_all: int = 200
    date_hierarchy: str | None = None

    # Form configuration
    fields: list[str] | None = None
    exclude: list[str] | None = None
    readonly_fields: list[str] = []
    fieldsets: list[tuple[str | None, dict[str, Any]]] | None = None
    form_fields: dict[str, dict[str, Any]] = {}

    # Security: fields that should never be serialized/exposed in API responses
    sensitive_fields: list[str] = [
        "password",
    ]

    # Actions
    actions: list[Callable] = []
    actions_on_top: bool = True
    actions_on_bottom: bool = False

    # UI options
    save_on_top: bool = False
    preserve_filters: bool = True
    show_full_result_count: bool = True

    # Inlines (nested model editing)
    inlines: list[type[InlineModelAdmin]] = []
    child_tables: list[type[ChildTable]] = []

    def __init__(self, model_class: type[Model]) -> None:
        """Initialize ModelAdmin with the model it manages.

        Args:
            model_class: The model class this admin manages.
        """
        self.model = model_class
        self._model_name = model_class.__name__
        self._app_name = getattr(model_class, "_app_name", "default")
        self._table_name = getattr(model_class, "_table_name", "")
        self._fields = getattr(model_class, "_fields", {})

    # -- List view methods -------------------------------------------------

    def get_list_display(self, request: Request | None = None) -> list[str]:
        """Get fields to display in list view.

        Args:
            request: The current request (for dynamic display).

        Returns:
            List of field names to display.
        """
        if self.list_display:
            return list(self.list_display)
        # Default: show pk and first few fields
        field_names = list(self._fields.keys())[:5]
        return ["id"] + field_names if "id" not in field_names else field_names

    def get_list_display_links(self, request: Request | None = None) -> list[str]:
        """Get fields that should be links to detail view.

        Args:
            request: The current request.

        Returns:
            List of field names that should be clickable links.
        """
        if self.list_display_links is not None:
            return list(self.list_display_links)
        # Default: first field in list_display
        display = self.get_list_display(request)
        return [display[0]] if display else []

    def get_list_filter(self, request: Request | None = None) -> list[str]:
        """Get fields to filter by in list view.

        Args:
            request: The current request.

        Returns:
            List of field names for filtering.
        """
        return list(self.list_filter)

    def get_search_fields(self, request: Request | None = None) -> list[str]:
        """Get fields to search across.

        Args:
            request: The current request.

        Returns:
            List of field names for full-text search.
        """
        return list(self.search_fields)

    def get_ordering(self, request: Request | None = None) -> list[str]:
        """Get default ordering for list view.

        Args:
            request: The current request.

        Returns:
            List of field names (prefixed with - for descending).
        """
        if self.ordering:
            if isinstance(self.ordering, str):
                return [self.ordering]
            return list(self.ordering)
        return ["-id"]

    # ── Form view methods ─────────────────────────────────────────────────

    def get_fields(self, request: Request | None = None, obj: Model | None = None) -> list[str]:
        """Get fields to show in the form.

        Args:
            request: The current request.
            obj: The object being edited (None for create).

        Returns:
            List of field names to show in form.
        """
        if self.fields is not None:
            return list(self.fields)
        # All fields except excluded and auto-fields
        all_fields = list(self._fields.keys())
        excluded = self.get_exclude(request, obj)
        return [f for f in all_fields if f not in excluded and f != "id"]

    def get_exclude(self, request: Request | None = None, obj: Model | None = None) -> list[str]:
        """Get fields to exclude from the form.

        Args:
            request: The current request.
            obj: The object being edited.

        Returns:
            List of field names to exclude.
        """
        return list(self.exclude or [])

    def get_sensitive_fields(
        self, request: Request | None = None, obj: Model | None = None
    ) -> list[str]:
        """Get fields that should never be serialized/exposed in API responses.

        These fields (like password) are excluded from all data responses
        to prevent exposure of sensitive data.

        Args:
            request: The current request.
            obj: The object being viewed/edited.

        Returns:
            List of field names that should never be exposed.
        """
        if self.sensitive_fields is not None:
            return list(self.sensitive_fields)

        # Default sensitive fields
        default_sensitive = [
            "password",
            "token",
            "secret",
            "key",
            "api_key",
            "access_token",
            "refresh_token",
        ]
        return [
            f
            for f in getattr(obj or self.model, "_fields", {}).keys()
            if any(s in f.lower() for s in default_sensitive)
        ]

    def get_readonly_fields(
        self, request: Request | None = None, obj: Model | None = None
    ) -> list[str]:
        """Get fields that should be read-only.

        Args:
            request: The current request.
            obj: The object being edited.

        Returns:
            List of field names that cannot be edited.
        """
        return list(self.readonly_fields)

    def get_fieldsets(
        self, request: Request | None = None, obj: Model | None = None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        """Get fieldsets for form grouping.

        Args:
            request: The current request.
            obj: The object being edited.

        Returns:
            List of (title, options) tuples for field grouping.
        """
        if self.fieldsets:
            return list(self.fieldsets)
        # Default: single fieldset with all fields
        fields = self.get_fields(request, obj)
        return [(None, {"fields": fields})]

    def get_form_field_config(self, field_name: str) -> dict[str, Any]:
        """Get custom configuration for a form field.

        Args:
            field_name: The field to get config for.

        Returns:
            Dict of field widget configuration.
        """
        return self.form_fields.get(field_name, {})

    # -- Permission methods ------------------------------------------------

    def has_view_permission(self, request: Request | None = None, obj: Model | None = None) -> bool:
        """Check if user can view this model.

        Args:
            request: The current request.
            obj: The specific object (for object-level permissions).

        Returns:
            True if user has view permission.
        """
        if request is None:
            return True
        user = getattr(request, "user", None)
        if user is None:
            return False
        # Staff or superuser can view
        return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)

    def has_add_permission(self, request: Request | None = None) -> bool:
        """Check if user can add new instances.

        Args:
            request: The current request.

        Returns:
            True if user has add permission.
        """
        if request is None:
            return True
        user = getattr(request, "user", None)
        if user is None:
            return False
        return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)

    def has_change_permission(
        self, request: Request | None = None, obj: Model | None = None
    ) -> bool:
        """Check if user can change instances.

        Args:
            request: The current request.
            obj: The specific object.

        Returns:
            True if user has change permission.
        """
        if request is None:
            return True
        user = getattr(request, "user", None)
        if user is None:
            return False
        return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)

    def has_delete_permission(
        self, request: Request | None = None, obj: Model | None = None
    ) -> bool:
        """Check if user can delete instances.

        Args:
            request: The current request.
            obj: The specific object.

        Returns:
            True if user has delete permission.
        """
        if request is None:
            return True
        user = getattr(request, "user", None)
        if user is None:
            return False
        return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)

    # ── CRUD methods ──────────────────────────────────────────────────────

    async def save_model(
        self,
        request: Request,
        obj: Model,
        form_data: dict[str, Any],
        change: bool = False,
    ) -> Model:
        """Save a model instance.

        Args:
            request: The current request.
            obj: The model instance to save.
            form_data: The form data submitted.
            change: True if editing, False if creating.

        Returns:
            The saved model instance.
        """
        # Apply form data to object
        for field_name, value in form_data.items():
            if field_name not in self.get_readonly_fields(request, obj):
                setattr(obj, field_name, value)
        await obj.save()
        return obj

    async def delete_model(self, request: Request, obj: Model) -> None:
        """Delete a model instance.

        Args:
            request: The current request.
            obj: The model instance to delete.
        """
        await obj.delete()

    # ── Actions ───────────────────────────────────────────────────────────

    def get_actions(self, request: Request | None = None) -> dict[str, Callable]:
        """Get available actions for this model.

        Args:
            request: The current request.

        Returns:
            Dict mapping action names to callables.
        """
        actions = {}
        # Built-in delete action
        actions["delete_selected"] = self._action_delete_selected
        # Custom actions
        for action_name_or_func in self.actions:
            if isinstance(action_name_or_func, str):
                # Resolve string name to method
                func = getattr(self, action_name_or_func, None)
                if func and callable(func):
                    actions[action_name_or_func] = func
                else:
                    logger.warning(
                        f"Action '{action_name_or_func}' not found on {self.__class__.__name__}"
                    )
            else:
                # Use provided callable
                name = getattr(action_name_or_func, "__name__", str(action_name_or_func))
                actions[name] = action_name_or_func
        return actions

    async def _action_delete_selected(self, request: Request, queryset: Any) -> int:
        """Built-in action: delete selected objects.

        Args:
            request: The current request.
            queryset: The queryset of selected objects.

        Returns:
            Number of deleted objects.
        """
        count = await queryset.count()
        await queryset.delete()
        return count

    # ── Metadata ──────────────────────────────────────────────────────────

    def get_model_info(self, request: Any = None) -> dict[str, Any]:
        """Get metadata about this model for the API.

        Returns:
            Dict with model information.
        """

        # Get sensitive fields to exclude from model info
        sensitive_fields = self.get_sensitive_fields()
        excluded_fields = self.get_exclude()

        fields_info = {}
        for field_name, field in self._fields.items():
            # Skip sensitive and excluded fields
            if field_name in sensitive_fields or field_name in excluded_fields:
                continue
            fields_info[field_name] = get_field_schema(field)

        # Get fieldsets and filter out sensitive/excluded fields
        raw_fieldsets = self.get_fieldsets()
        filtered_fieldsets = []
        for name, options in raw_fieldsets:
            filtered_fields = [
                f
                for f in options.get("fields", [])
                if f not in sensitive_fields and f not in excluded_fields
            ]
            if filtered_fields:
                filtered_fieldsets.append(
                    {
                        "name": name,
                        "fields": filtered_fields,
                        "classes": options.get("classes", []),
                        "description": options.get("description", ""),
                    }
                )

        return {
            "name": self._model_name,
            "app": self._app_name,
            "table": self._table_name,
            "verbose_name": self._model_name,
            "verbose_name_plural": f"{self._model_name}s",
            "fields": fields_info,
            "fieldsets": filtered_fieldsets if filtered_fieldsets else None,
            "list_display": self.get_list_display(),
            "list_filter": self.get_list_filter(),
            "search_fields": self.get_search_fields(),
            "ordering": self.get_ordering(),
            "list_per_page": self.list_per_page,
            "readonly_fields": list(self.readonly_fields),
            "actions": list(self.get_actions().keys()),
            "child_tables": self.get_child_tables_info(),
            "permissions": {
                "add": bool(self.has_add_permission(request)),
                "change": bool(self.has_change_permission(request)),
                "delete": bool(self.has_delete_permission(request)),
                "view": bool(self.has_view_permission(request)),
            },
        }

    def get_child_tables_info(self) -> list[dict[str, Any]]:
        """Get metadata for all registered child tables."""
        child_tables = []
        for inline_class in self.child_tables or self.inlines:
            inline = inline_class(self.model)
            child_model = inline.model

            # Get field schema for the child model
            fields = getattr(child_model, "_fields", {})
            inline_fields = inline.fields or list(fields.keys())
            if "id" not in inline_fields:
                inline_fields = ["id"] + inline_fields

            fields_schema = {}
            for field_name in inline_fields:
                if field_name in fields:
                    fields_schema[field_name] = get_field_schema(fields[field_name])

            child_tables.append(
                {
                    "name": child_model.__name__.lower()
                    + "_set",  # Default related name convention
                    "label": getattr(inline, "label", child_model.__name__ + "s"),
                    "model": child_model.__name__,
                    "fk_name": inline.fk_name,
                    "fields": fields_schema,
                    "display_fields": inline_fields,
                    "readonly_fields": list(inline.readonly_fields),
                }
            )
        return child_tables

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self._model_name}>"


class InlineModelAdmin:
    """Configuration for inline (nested) model editing.

    Used to edit related models on the same page as the parent.
    """

    model: type[Model]
    fk_name: str | None = None
    extra_filters: dict[str, Any] | None = None
    fields: list[str] | None = None
    exclude: list[str] | None = None
    readonly_fields: list[str] = []
    extra: int = 3
    max_num: int | None = None
    min_num: int | None = None
    can_delete: bool = True
    show_change_link: bool = False

    def __init__(self, parent_model: type[Model]) -> None:
        self.parent_model = parent_model


class TabularInline(InlineModelAdmin):
    """Tabular inline display (horizontal table)."""

    template = "tabular"


class StackedInline(InlineModelAdmin):
    """Stacked inline display (vertical cards)."""

    template = "stacked"


class ChildTable(TabularInline):
    """Alias for TabularInline, matching the requested nomenclature."""

    pass
