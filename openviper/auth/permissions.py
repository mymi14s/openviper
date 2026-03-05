"""Role-based permission enforcement logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openviper.core.context import current_user

if TYPE_CHECKING:
    from openviper.db.models import Model

# Module-level cache: "app_label.model_name" -> True (protected) / False (public).
# ContentType registrations are static (model structure never changes at runtime),
# so this is safe to cache for the lifetime of the process.
_CT_PERMISSION_CACHE: dict[str, bool] = {}


class PermissionError(Exception):  # noqa: A001
    """Raised when a user attempts an unauthorized action on a model."""

    pass


async def check_permission_for_model(
    model_cls: type[Model], action: str, ignore_permissions: bool = False
) -> None:
    """Check if the current request user is authorized to perform an action.

    Args:
        model_cls: The model class being accessed.
        action: 'create', 'read', 'write', 'update', or 'delete'.
        ignore_permissions: If True, bypass all permission checks.

    Raises:
        PermissionError: If the user is unauthenticated or unauthorized.
    """
    from openviper.core.context import ignore_permissions_ctx

    if ignore_permissions or ignore_permissions_ctx.get():
        return
    if getattr(model_cls, "_app_name", "") == "auth":
        return

    # 2. Public model check: If no roles are associated with the model in ContentTypePermission,
    # it is considered public and accessible to everyone.
    app_label = getattr(model_cls, "_app_name", "default")
    model_name = getattr(model_cls, "_model_name", model_cls.__name__)
    model_label = f"{app_label}.{model_name}"

    if model_label not in _CT_PERMISSION_CACHE:
        from openviper.auth.models import ContentType, ContentTypePermission

        content_type = await ContentType.objects.filter(
            app_label=app_label, model=model_name
        ).first()
        if content_type:
            ct_perms_count = await ContentTypePermission.objects.filter(
                content_type=content_type.pk
            ).count()
            _CT_PERMISSION_CACHE[model_label] = ct_perms_count > 0
        else:
            # No ContentType exists — model is public.
            _CT_PERMISSION_CACHE[model_label] = False

    if not _CT_PERMISSION_CACHE[model_label]:
        return

    # 3. Bypass check if no user context is set (e.g. CLI, management commands)
    user = current_user.get()
    if user is None:
        return

    # 4. Bypass check if user is a superuser
    if getattr(user, "is_superuser", False):
        return

    # 5. Enforce permissions
    if not await user.has_model_perm(model_label, action):
        raise PermissionError(f"Unauthorized: Access denied '{action}' on {model_label}")
