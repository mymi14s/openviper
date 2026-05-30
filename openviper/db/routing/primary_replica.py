"""Built-in primary/replica database router for read/write splitting."""

from __future__ import annotations

import threading

from openviper.db.routing.base import DatabaseRouter
from openviper.db.routing.context import read_from_primary, write_used


class PrimaryReplicaRouter(DatabaseRouter):
    """Route reads to replicas and writes to the primary database.

    Configuration is provided via constructor arguments or
    ``DATABASE_ROUTING`` settings.

    Args:
        primary_alias: Alias for the primary (writable) database.
        replica_aliases: List of replica (read-only) aliases.
        read_your_writes: When ``True``, reads after a write in the
            same context go to primary to avoid replication lag.
        replica_selection: Strategy for choosing among replicas.
            Currently supports ``"first"`` and ``"round_robin"``.
        migrate_on_primary_only: When ``True``, ``allow_migrate``
            returns ``True`` only for the primary alias.
    """

    def __init__(
        self,
        primary_alias: str = "default",
        replica_aliases: list[str] | None = None,
        read_your_writes: bool = True,
        replica_selection: str = "first",
        migrate_on_primary_only: bool = True,
    ) -> None:
        self.primary_alias = primary_alias
        self.replica_aliases = list(replica_aliases or [])
        self.read_your_writes = read_your_writes
        self.replica_selection = replica_selection
        self.migrate_on_primary_only = migrate_on_primary_only
        self._rr_index: int = 0
        self._rr_lock: threading.Lock = threading.Lock()

    async def db_for_read(self, model_class: type, **hints: object) -> str | None:
        """Route reads to a replica unless read-your-writes is active."""
        if self.read_your_writes and (write_used.get() or read_from_primary.get()):
            return self.primary_alias

        if not self.replica_aliases:
            return self.primary_alias

        return self.select_replica()

    async def db_for_write(self, model_class: type, **hints: object) -> str | None:
        """Route writes to the primary database."""
        return self.primary_alias

    async def allow_relation(self, obj1: object, obj2: object, **hints: object) -> bool | None:
        """Allow relations between objects on primary and its replicas."""
        all_aliases = {self.primary_alias, *self.replica_aliases}
        obj1_alias = getattr(obj1, "_db_alias", self.primary_alias)
        obj2_alias = getattr(obj2, "_db_alias", self.primary_alias)
        if obj1_alias in all_aliases and obj2_alias in all_aliases:
            return True
        return None

    async def allow_migrate(
        self,
        db_alias: str,
        model_class: type | None = None,
        **hints: object,
    ) -> bool | None:
        """Allow migrations only on primary by default."""
        if self.migrate_on_primary_only:
            return db_alias == self.primary_alias
        return None

    def select_replica(self) -> str:
        """Choose a replica alias using the configured selection strategy."""
        if not self.replica_aliases:
            return self.primary_alias

        if self.replica_selection == "round_robin":
            with self._rr_lock:
                alias = self.replica_aliases[self._rr_index % len(self.replica_aliases)]
                self._rr_index += 1
            return alias

        return self.replica_aliases[0]
