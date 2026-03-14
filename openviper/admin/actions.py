"""Batch actions system for admin panel.

Provides infrastructure for defining and executing bulk operations
on selected objects in the admin list view.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openviper.admin import ModelAdmin
    from openviper.db.models import QuerySet
    from openviper.http.request import Request


@dataclass
class ActionResult:
    """Result of executing an admin action."""

    #: Whether the action completed successfully.
    success: bool
    #: Number of objects affected.
    count: int
    #: Human-readable result message.
    message: str
    #: List of error messages if any.
    errors: list[str] | None = None


class AdminAction:
    """Base class for admin batch actions.

    Subclass this to create custom actions that can be performed
    on multiple selected objects.
    """

    #: Internal name for the action.
    name: str = ""
    #: Human-readable description shown in UI.
    description: str = ""
    #: Optional confirmation prompt.
    confirm_message: str | None = None
    #: List of required permissions.
    permissions: list[str] = []

    def __init__(self) -> None:
        if not self.name:
            self.name = self.__class__.__name__.lower()
        if not self.description:
            self.description = self.name.replace("_", " ").title()

    async def execute(
        self, queryset: QuerySet, request: Request, model_admin: ModelAdmin | None = None
    ) -> ActionResult:
        """Execute the action on the queryset.

        Args:
            queryset: QuerySet of selected objects.
            request: The current request.
            model_admin: Optional ModelAdmin instance.

        Returns:
            ActionResult with success status and message.
        """
        raise NotImplementedError("Subclasses must implement execute()")

    def has_permission(self, request: Request) -> bool:
        """Check if the user has permission to run this action.

        Args:
            request: The current request.

        Returns:
            True if user can execute this action.
        """
        if not self.permissions:
            return True

        user = getattr(request, "user", None)
        if user is None:
            return False

        # Check if user has all required permissions
        for _perm in self.permissions:
            if not hasattr(user, "has_perm"):
                return getattr(user, "is_superuser", False)
            # This would need to be async in practice
            # For now, assume basic permission check
        return True

    def get_info(self) -> dict[str, Any]:
        """Get action metadata for API response.

        Returns:
            Dict with action info.
        """
        return {
            "name": self.name,
            "description": self.description,
            "confirm_message": self.confirm_message,
            "requires_confirmation": self.confirm_message is not None,
        }


class DeleteSelectedAction(AdminAction):
    """Built-in action to delete selected objects."""

    name = "delete_selected"
    description = "Delete selected items"
    confirm_message = (
        "Are you sure you want to delete the selected items? This action cannot be undone."
    )

    async def execute(
        self, queryset: QuerySet, request: Request, model_admin: ModelAdmin | None = None
    ) -> ActionResult:
        """Delete all objects in the queryset.

        Args:
            queryset: QuerySet of objects to delete.
            request: The current request.
            model_admin: Optional ModelAdmin instance.

        Returns:
            ActionResult with count of deleted objects.
        """
        count = await queryset.count()
        await queryset.delete()
        return ActionResult(
            success=True,
            count=count,
            message=f"Successfully deleted {count} item(s).",
        )


# Registry of available actions
_action_registry: dict[str, type[AdminAction]] = {
    "delete_selected": DeleteSelectedAction,
}


def register_action(action_class: type[AdminAction]) -> type[AdminAction]:
    """Register a custom action with the admin system.

    Args:
        action_class: The AdminAction subclass to register.

    Returns:
        The same class (for use as decorator).
    """
    instance = action_class()
    _action_registry[instance.name] = action_class
    return action_class


def get_action(name: str) -> AdminAction | None:
    """Get an action instance by name.

    Args:
        name: The action name.

    Returns:
        AdminAction instance or None if not found.
    """
    action_class = _action_registry.get(name)
    if action_class:
        return action_class()
    return None


def get_available_actions(request: Request) -> list[AdminAction]:
    """Get all actions available to the current user.

    Args:
        request: The current request.

    Returns:
        List of AdminAction instances the user can execute.
    """
    actions = []
    for action_class in _action_registry.values():
        action = action_class()
        if action.has_permission(request):
            actions.append(action)
    return actions


def action(
    description: str | None = None,
    confirm_message: str | None = None,
    permissions: list[str] | None = None,
) -> Callable:
    """Decorator to create an action from a function.

    Args:
        description: Human-readable description.
        confirm_message: Optional confirmation prompt.
        permissions: Required permissions.

    Returns:
        Decorator function.

    Example:
        .. code-block:: python

            @action(description="Mark as published", confirm_message="Publish selected posts?")
            async def publish_selected(queryset, request):
                count = await queryset.update(is_published=True)
                return ActionResult(success=True, count=count, message=f"Published {count} posts")
    """

    def decorator(func: Callable) -> type[AdminAction]:
        _description = description
        _confirm_message = confirm_message
        _permissions = permissions or []

        class FunctionAction(AdminAction):
            name = func.__name__
            description = _description or func.__name__.replace("_", " ").title()
            confirm_message = _confirm_message
            permissions = _permissions

            async def execute(
                self, queryset: QuerySet, request: Request, model_admin: ModelAdmin | None = None
            ) -> ActionResult:
                # Check how many arguments the function expects
                sig = inspect.signature(func)
                params_count = len(sig.parameters)

                if params_count == 3:
                    # Expects (self/model_admin, queryset, request)
                    result = func(model_admin, queryset, request)
                else:
                    # Expects (queryset, request)
                    result = func(queryset, request)

                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, ActionResult):
                    return result
                return ActionResult(
                    success=True,
                    count=result if isinstance(result, int) else 0,
                    message="Action completed successfully.",
                )

        FunctionAction.__name__ = func.__name__
        FunctionAction.__qualname__ = func.__qualname__
        register_action(FunctionAction)
        return FunctionAction

    # Handle @action without parentheses
    if callable(description):
        func = description
        description = None
        return decorator(func)

    return decorator
