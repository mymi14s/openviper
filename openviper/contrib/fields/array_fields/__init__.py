"""PostgreSQL-native array field for OpenViper ORM.

Provides :class:`ArrayField` for storing homogeneous lists of a scalar
base type.  On PostgreSQL the column uses the native ``ARRAY`` type; on
other backends values are serialised as JSON text.

Usage::

    from openviper.db import Model
    from openviper.db.fields import IntegerField, CharField
    from openviper.contrib.fields.array_fields import ArrayField

    class Article(Model):
        tags = ArrayField(CharField(max_length=50))
        scores = ArrayField(IntegerField(), null=True)
"""

from openviper.contrib.fields.array_fields.backends import (
    BaseArrayBackend,
    FallbackJsonBackend,
    PostgresArrayBackend,
    get_backend,
    reset_backend,
)
from openviper.contrib.fields.array_fields.base import ArrayField

__all__ = [
    "ArrayField",
    "BaseArrayBackend",
    "FallbackJsonBackend",
    "PostgresArrayBackend",
    "get_backend",
    "reset_backend",
]
