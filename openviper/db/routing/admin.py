"""Admin database routing policy.

Ensures admin operations use the primary database for consistency
and safety.  Admin writes, deletes, and reads all go to primary
by default.
"""

from __future__ import annotations

from openviper.db.routing.base import DatabaseRouter


class AdminRouter(DatabaseRouter):
    """Route all admin model operations to the primary database.

    This router ensures that admin writes and reads use the
    primary (default) database for consistency.  It should be
    listed last in ``DATABASE_ROUTERS`` so that it only affects
    operations not already routed by other routers.
    """

    async def db_for_read(self, model_class: type, **hints: object) -> str | None:
        """Route admin reads to primary for consistency."""
        if hints.get("admin"):
            return "default"
        return None

    async def db_for_write(self, model_class: type, **hints: object) -> str | None:
        """Route admin writes to primary."""
        if hints.get("admin"):
            return "default"
        return None

    async def allow_migrate(
        self,
        db_alias: str,
        model_class: type | None = None,
        **hints: object,
    ) -> bool | None:
        """Allow migrations on primary for admin models."""
        return None
