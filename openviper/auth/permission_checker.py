"""ContentType-based permission checker implementation."""

from __future__ import annotations

from openviper.auth.models import ContentType, ContentTypePermission

CT_PERMISSION_CACHE_MAXSIZE: int = 4096


CT_PERMISSION_CACHE: dict[str, bool] = {}


def evict_permission_cache_if_full() -> None:
    """Evict oldest entries when the permission cache exceeds its size bound.

    ContentType data is effectively static, so eviction is a safety net
    rather than a correctness concern.
    """
    if len(CT_PERMISSION_CACHE) <= CT_PERMISSION_CACHE_MAXSIZE:
        return
    batch = max(1, int(CT_PERMISSION_CACHE_MAXSIZE * 0.1))
    for key in list(CT_PERMISSION_CACHE.keys())[:batch]:
        del CT_PERMISSION_CACHE[key]


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

        if model_label not in CT_PERMISSION_CACHE:
            content_type = await ContentType.objects.filter(
                app_label=app_label, model=model_name
            ).first()
            if content_type:
                ct_perms_count = await ContentTypePermission.objects.filter(
                    content_type=content_type.pk
                ).count()
                CT_PERMISSION_CACHE[model_label] = ct_perms_count > 0
            else:
                # Intent: Missing content type means no protected object exists.
                CT_PERMISSION_CACHE[model_label] = False
            evict_permission_cache_if_full()

        return CT_PERMISSION_CACHE[model_label]


def get_permission_checker() -> ContentTypePermissionChecker:
    """Get the ContentType-based permission checker instance."""
    return ContentTypePermissionChecker()
