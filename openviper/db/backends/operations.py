"""Database operations layer for backend-specific behavior."""

from __future__ import annotations

from urllib.parse import urlparse


class DatabaseOperations:
    """OpenViper-level database-specific behaviour above SQLAlchemy.

    This does not replace SQLAlchemy's compiler.  It provides
    integration points for URL normalization, value adaptation,
    and backend-specific utility methods that the ORM or migrations
    may need beyond what SQLAlchemy's dialect system offers.
    """

    URL_REPLACEMENTS: dict[str, str] = {
        "sqlite:///": "sqlite+aiosqlite:///",
        "sqlite://": "sqlite+aiosqlite://",
        "postgresql://": "postgresql+asyncpg://",
        "postgres://": "postgresql+asyncpg://",
        "mysql://": "mysql+aiomysql://",
        "mariadb://": "mysql+aiomysql://",
        "oracle://": "oracle+oracledb_async://",
        "mssql://": "mssql+aioodbc://",
    }

    def normalize_url(self, url: str) -> str:
        """Translate a synchronous database URL to its async driver equivalent.

        If the URL already contains an async driver prefix (e.g.
        ``postgresql+asyncpg://``), it is returned unchanged.
        """
        for old, new in self.URL_REPLACEMENTS.items():
            if url.startswith(old):
                return new + url[len(old) :]
        return url

    def extract_vendor(self, url: str) -> str:
        """Return a short vendor name derived from the database URL.

        Useful for selecting dialect-specific code paths without
        importing the driver.
        """
        parsed = urlparse(url)
        scheme = parsed.scheme.split("+")[0]
        vendor_map: dict[str, str] = {
            "postgresql": "postgresql",
            "postgres": "postgresql",
            "mysql": "mysql",
            "mariadb": "mysql",
            "sqlite": "sqlite",
            "oracle": "oracle",
            "mssql": "mssql",
        }
        return vendor_map.get(scheme, scheme)

    def quote_identifier(self, name: str) -> str:
        """Quote a SQL identifier if it contains special characters.

        Default implementation uses double-quote quoting per the
        SQL standard.  Backends that require different quoting (e.g.
        MySQL backticks) should override this method.
        """
        if name.isidentifier():
            return name
        return f'"{name}"'

    def adapt_value(self, value: object) -> object:
        """Adapt a Python value before execution.

        Override in backend subclasses to handle dialect-specific
        type coercion (e.g. UUID → string for SQLite).
        """
        return value
