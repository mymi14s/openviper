"""Optional database client helpers for CLI and shell access."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openviper.db.backends.database import DatabaseBackend


class DatabaseClient:
    """Optional helper for database shell and client commands.

    Backends that provide a CLI client (e.g. ``psql``, ``mysql``)
    should override ``client_command`` to return the executable
    and connection arguments.
    """

    def __init__(self, backend: DatabaseBackend) -> None:
        self.backend = backend

    def client_command(self) -> list[str]:
        """Return the shell command to open a database client.

        Default returns an empty list indicating no client is
        available for this backend.
        """
        return []

    def runshell(self) -> None:
        """Launch an interactive database client shell.

        Default implementation is a no-op.  Backends that support
        interactive shells should override this method.
        """
