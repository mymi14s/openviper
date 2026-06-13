"""Virtual model backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from openviper.db.exceptions import ReadOnlyVirtualModelError, UnsupportedVirtualQueryError

if TYPE_CHECKING:
    from openviper.db.models import Model
    from openviper.db.queryspec import QuerySpec


@dataclass(frozen=True, slots=True)
class VirtualBackendCapabilities:
    """Supported virtual backend operations.

    Backends declare which operations they support so that the ORM can
    raise ``UnsupportedVirtualQueryError`` early instead of failing with
    an opaque backend error.
    """

    supports_create: bool = True
    supports_update: bool = True
    supports_delete: bool = True
    supports_filter: bool = True
    supports_filter_ops: bool = False
    supports_order_by: bool = True
    supports_offset: bool = True
    supports_limit: bool = True
    supports_count: bool = False
    supports_distinct: bool = False
    supports_only: bool = False
    supports_defer: bool = False
    supports_bulk_create: bool = False
    supports_bulk_update: bool = False
    supports_bulk_delete: bool = False


class VirtualBackend(ABC):
    """Async storage adapter for virtual model data."""

    capabilities: VirtualBackendCapabilities = VirtualBackendCapabilities()
    read_only: bool = False

    @abstractmethod
    async def get(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> Mapping[str, object] | None:
        """Return one record by primary key."""

    @abstractmethod
    async def list(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> Sequence[Mapping[str, object]]:
        """Return records matching the query spec."""

    @abstractmethod
    async def create(
        self,
        model_class: type[Model],
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Create and return one record."""

    @abstractmethod
    async def update(
        self,
        model_class: type[Model],
        primary_key: object,
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Update and return one record."""

    @abstractmethod
    async def delete(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> None:
        """Delete one record."""

    def check_write_allowed(self, operation: str) -> None:
        """Raise ``ReadOnlyVirtualModelError`` if this backend is read-only."""
        if self.read_only:
            raise ReadOnlyVirtualModelError(
                f"Cannot perform {operation} on read-only virtual backend '{type(self).__name__}'."
            )

    def check_capability(self, operation: str, capability: bool) -> None:
        """Raise ``UnsupportedVirtualQueryError`` if *capability* is ``False``."""
        if not capability:
            raise UnsupportedVirtualQueryError(
                f"Virtual backend '{type(self).__name__}' does not support {operation}."
            )

    async def count(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> int:
        """Return the total number of records matching *query*.

        Backends that can compute counts efficiently should override this
        method.  The default implementation materialises every row and
        counts the resulting list, which is correct but expensive.
        """
        self.check_capability("count", self.capabilities.supports_count)
        rows = await self.list(model_class, query)
        return len(rows)

    async def bulk_create(
        self,
        model_class: type[Model],
        data_list: Sequence[Mapping[str, object]],
    ) -> Sequence[Mapping[str, object]]:
        """Create multiple records in a single backend call.

        Backends that can batch inserts should override this method.
        The default implementation calls :meth:`create` for each item.
        """
        self.check_write_allowed("bulk_create")
        self.check_capability("bulk_create", self.capabilities.supports_bulk_create)
        return [await self.create(model_class, item) for item in data_list]

    async def bulk_update(
        self,
        model_class: type[Model],
        updates: Sequence[tuple[object, Mapping[str, object]]],
    ) -> int:
        """Update multiple records in a single backend call.

        *updates* is a sequence of ``(primary_key, data)`` pairs.
        Returns the number of records updated.

        Backends that can batch updates should override this method.
        The default implementation calls :meth:`update` for each item.
        """
        self.check_write_allowed("bulk_update")
        self.check_capability("bulk_update", self.capabilities.supports_bulk_update)
        for pk, data in updates:
            await self.update(model_class, pk, data)
        return len(updates)

    async def bulk_delete(
        self,
        model_class: type[Model],
        primary_keys: Sequence[object],
    ) -> int:
        """Delete multiple records in a single backend call.

        Returns the number of records deleted.

        Backends that can batch deletes should override this method.
        The default implementation calls :meth:`delete` for each key.
        """
        self.check_write_allowed("bulk_delete")
        self.check_capability("bulk_delete", self.capabilities.supports_bulk_delete)
        for pk in primary_keys:
            await self.delete(model_class, pk)
        return len(primary_keys)
