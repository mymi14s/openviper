"""Database router base class for alias selection."""

from __future__ import annotations


class DatabaseRouter:
    """Base class for database alias selection routers.

    Subclass and override ``db_for_read``, ``db_for_write``,
    ``allow_relation``, or ``allow_migrate`` to control which
    configured database alias handles each operation.

    Routers are checked in order.  The first non-``None`` return
    value wins.  If all routers return ``None``, the default
    alias is used.
    """

    async def db_for_read(self, model_class: type, **hints: object) -> str | None:
        """Return the database alias for a read operation.

        Return ``None`` to let the next router decide.
        """
        return None

    async def db_for_write(self, model_class: type, **hints: object) -> str | None:
        """Return the database alias for a write operation.

        Return ``None`` to let the next router decide.
        """
        return None

    async def allow_relation(self, obj1: object, obj2: object, **hints: object) -> bool | None:
        """Return whether a relation between two objects is allowed.

        Return ``True`` to allow, ``False`` to deny, or ``None`` to
        let the next router decide.
        """
        return None

    async def allow_migrate(
        self,
        db_alias: str,
        model_class: type | None = None,
        **hints: object,
    ) -> bool | None:
        """Return whether migrations are allowed on *db_alias*.

        Return ``True`` to allow, ``False`` to deny, or ``None`` to
        let the next router decide.
        """
        return None
