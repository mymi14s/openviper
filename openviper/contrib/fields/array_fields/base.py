"""PostgreSQL-native array field for OpenViper ORM.

Stores homogeneous lists of a scalar base type using PostgreSQL's ARRAY
column type.  Falls back to JSON serialisation on non-PostgreSQL backends.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from openviper.contrib.fields.array_fields.backends import get_backend
from openviper.db.fields import Field

if TYPE_CHECKING:
    import sqlalchemy as sa


class ArrayField(Field):
    """PostgreSQL-native array field storing homogeneous lists.

    Wraps a scalar *base_field* and maps to ``base_type[]`` on PostgreSQL
    or JSON on other database backends.

    Args:
        base_field: A :class:`~openviper.db.fields.Field` **instance** describing
            the element type (e.g. ``IntegerField()``, ``CharField(max_length=50)``).
            A Field **class** may also be passed and will be instantiated with
            default arguments (e.g. ``IntegerField`` becomes ``IntegerField()``).
        size: Optional maximum number of elements.  Enforced at the
            application level via :meth:`validate`.

    Raises:
        TypeError: If *base_field* is neither a Field instance nor a Field
            subclass.
    """

    _column_type = "TEXT"

    def __init__(
        self,
        base_field: type[Field] | Field,
        size: int | None = None,
        **kwargs: Any,
    ) -> None:
        if isinstance(base_field, type) and issubclass(base_field, Field):
            base_field = base_field()

        if not isinstance(base_field, Field):
            received = getattr(base_field, "__name__", type(base_field).__name__)
            msg = f"base_field must be a Field instance or Field subclass, got {received!r}."
            raise TypeError(msg)

        self.base_field = base_field
        self.size = size
        super().__init__(**kwargs)

    @property
    def base_column_type(self) -> str:
        """Public accessor for the base field's column type string."""
        return self.base_field._column_type

    @property
    def db_column_type(self) -> str:
        """Return the column type string for DDL generation.

        On PostgreSQL the type is derived from the base field's
        ``_column_type`` with ``[]`` appended.  On other backends the
        column is stored as JSON text.
        """
        backend = get_backend()
        return backend.column_ddl(self)

    def to_python(self, value: Any) -> list[Any] | None:
        """Convert a database value to a Python list.

        Accepts lists, tuples, JSON strings, and ``None``.  Each element
        is passed through ``base_field.to_python()`` for type coercion.
        """
        if value is None:
            return None

        if isinstance(value, (list, tuple)):
            return [self.base_field.to_python(item) for item in value]

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError, TypeError:
                return None
            if isinstance(parsed, list):
                return [self.base_field.to_python(item) for item in parsed]
            return None

        return None

    def to_db(self, value: Any) -> Any:
        """Prepare a Python list for database storage.

        On PostgreSQL the list is returned as-is (the asyncpg driver
        handles serialisation).  On other backends the list is JSON-encoded.
        Each element is passed through ``base_field.to_db()`` first.
        """
        if value is None:
            return None

        if not isinstance(value, (list, tuple)):
            msg = (
                f"Value for ArrayField '{self.name}' must be a list or tuple, "
                f"got {type(value).__name__!r}"
            )
            raise ValueError(msg)

        coerced = [self.base_field.to_db(item) for item in value]

        backend = get_backend()
        return backend.to_db(coerced)

    def validate(self, value: Any) -> None:
        """Validate the array and each element through the base field."""
        super().validate(value)
        if value is None:
            return
        if not isinstance(value, (list, tuple)):
            msg = f"ArrayField '{self.name}' expects a list or tuple, got {type(value).__name__!r}"
            raise ValueError(msg)
        if self.size is not None and len(value) > self.size:
            msg = (
                f"ArrayField '{self.name}' exceeds maximum size of {self.size} "
                f"(got {len(value)} elements)"
            )
            raise ValueError(msg)
        for item in value:
            self.base_field.validate(item)

    def get_sa_type(self) -> sa.types.TypeEngine[Any]:
        """Return the SQLAlchemy column type for this field."""
        backend = get_backend()
        return backend.get_sa_type(self)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(name={self.name!r}, base={self.base_field.__class__.__name__})"
        )
