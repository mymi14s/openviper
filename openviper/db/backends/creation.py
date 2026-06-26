"""Test database creation and destruction for backend alias."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openviper.db.backends.database import DatabaseBackend

logger = logging.getLogger(__name__)


class DatabaseCreation:
    """Creates and destroys test databases for a configured alias.

    Used by OpenViper TestKit, pytest multi-database fixtures, and
    test database isolation.
    """

    def __init__(self, backend: DatabaseBackend) -> None:
        self.backend = backend
