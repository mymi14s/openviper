"""MariaDB / MySQL feature flags.

MariaDB speaks the MySQL wire protocol and shares SQLAlchemy's
``mysql`` dialect, so it is registered under the ``mysql`` vendor name
in :mod:`openviper.db.backends.features`.
"""

from __future__ import annotations

from openviper.db.backends.features.base import DatabaseFeatures


class MariaDBFeatures(DatabaseFeatures):
    """Feature flags for MariaDB and MySQL."""

    supports_returning: bool = False
    supports_partial_indexes: bool = False
    supports_check_constraints: bool = True
    supports_schema_comments: bool = False
