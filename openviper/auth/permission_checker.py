"""ContentType-based permission checker implementation."""

from __future__ import annotations

from openviper.auth.models import ContentType, ContentTypePermission

# Module-level cache: "app_label.model_name" -> True (protected) / False (public).
# ContentType registrations are static (model structure never changes at runtime),
# so this is safe to cache for the lifetime of the process.
_CT_PERMISSION_CACHE: dict[str, bool] = {}


class ContentTypePermissionChecker:
    """Permission checker that uses ContentType and ContentTypePermission models."""

    async def is_model_protected(self, app_label: str, model_name: str) -> bool:
        """Check if a model has permission restrictions configured.

        Args:
            app_label: Application label (e.g., "myapp").
            model_name: Model name (e.g., "Post").

        Returns:
            True if the model has permission restrictions, False if public.
        """
        model_label = f"{app_label}.{model_name}"

        if model_label not in _CT_PERMISSION_CACHE:
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

        return _CT_PERMISSION_CACHE[model_label]


def get_permission_checker() -> ContentTypePermissionChecker:
    """Get the ContentType-based permission checker instance."""
    return ContentTypePermissionChecker()
