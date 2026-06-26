"""Database feature flags for backend capability detection.

The base :class:`DatabaseFeatures` declares conservative defaults.
Each supported dialect ships its own module under this package so that
dialect-specific capability overrides can be authored, tested, and
imported independently of every other dialect.

Resolution of the correct feature set for a configured alias is handled
by :func:`get_features_for_vendor`, which maps a normalized vendor name
to the appropriate :class:`DatabaseFeatures` subclass instance.
"""

from __future__ import annotations

from openviper.db.backends.features.base import DatabaseFeatures
from openviper.db.backends.features.mariadb import MariaDBFeatures
from openviper.db.backends.features.mssql import MSSQLFeatures
from openviper.db.backends.features.oracle import OracleFeatures
from openviper.db.backends.features.postgres import PostgreSQLFeatures
from openviper.db.backends.features.sqlite import SQLiteFeatures

__all__ = [
    "DatabaseFeatures",
    "MariaDBFeatures",
    "MSSQLFeatures",
    "OracleFeatures",
    "PostgreSQLFeatures",
    "SQLiteFeatures",
    "get_features_for_vendor",
]

_VENDOR_FEATURES: dict[str, type[DatabaseFeatures]] = {
    "postgresql": PostgreSQLFeatures,
    "mysql": MariaDBFeatures,
    "mariadb": MariaDBFeatures,
    "sqlite": SQLiteFeatures,
    "mssql": MSSQLFeatures,
    "oracle": OracleFeatures,
}


def get_features_for_vendor(vendor: str) -> DatabaseFeatures:
    """Return the :class:`DatabaseFeatures` instance for *vendor*.

    Unknown vendors fall back to the conservative :class:`DatabaseFeatures`
    defaults so that misconfigured aliases never raise at feature lookup
    time; they simply advertise the lowest common denominator of support.
    """
    feature_cls = _VENDOR_FEATURES.get(vendor, DatabaseFeatures)
    return feature_cls()
