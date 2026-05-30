"""Backend-neutral query data for virtual models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum


class FilterOp(Enum):
    """Comparison operators for virtual model filter expressions.

    Each member maps to a standard SQL/ORM lookup type so that backends can
    translate filter clauses without interpreting arbitrary string suffixes.
    """

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    ICONTAINS = "icontains"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    IS_NULL = "is_null"


@dataclass(frozen=True, slots=True)
class FilterClause:
    """A single filter predicate for virtual model queries.

    Attributes:
        field: Column or field name.
        op: Comparison operator.
        value: Right-hand operand.  For ``IN`` / ``NOT_IN`` this should be
            a sequence of values.  For ``IS_NULL`` it should be a bool
            (``True`` → ``IS NULL``, ``False`` → ``IS NOT NULL``).
    """

    field: str
    op: FilterOp
    value: object


@dataclass(slots=True)
class QuerySpec:
    """Supported virtual query operations.

    Attributes:
        filters: Simple equality filters ``{field: value}``.
        filter_clauses: Structured filter predicates supporting comparison
            operators beyond equality.  Backends that declare
            ``supports_filter_ops`` must handle these; others may ignore
            them and fall back to ``filters``.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip.
        order_by: Ordering specification (``"field"`` ascending,
            ``"-field"`` descending).
        distinct: When ``True``, deduplicate result rows.
        only_fields: When set, restrict the backend to returning only these
            columns.  Backends that do not declare ``supports_only`` must
            return all columns and let the ORM strip extras client-side.
        defer_fields: When set, exclude these columns from the backend
            result.  Backends that do not declare ``supports_defer`` must
            return all columns and let the ORM strip extras client-side.
    """

    filters: Mapping[str, object] = field(default_factory=dict)
    filter_clauses: Sequence[FilterClause] = field(default_factory=tuple)
    limit: int | None = None
    offset: int | None = None
    order_by: Sequence[str] | None = None
    distinct: bool = False
    only_fields: Sequence[str] = field(default_factory=tuple)
    defer_fields: Sequence[str] = field(default_factory=tuple)
