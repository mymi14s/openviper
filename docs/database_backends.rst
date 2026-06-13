.. _database_backends:

==========================
Database Backends
==========================

Overview
========

OpenViper exposes database extensibility through a ``DatabaseBackend`` API
that wraps the framework's existing SQLAlchemy-based connection, execution,
features, operations, introspection, and creation behaviour.

This feature does **not** replace SQLAlchemy.  SQLAlchemy remains the default
SQL dialect and execution foundation.  The backend API exposes OpenViper
integration points *around* SQLAlchemy so developers can customize, extend,
and instrument database behaviour.

How OpenViper Database Backends Work
=====================================

A ``DatabaseBackend`` is an OpenViper class that controls how a configured
SQL database alias creates engines, connections, transactions, and executes
statements.  It also exposes feature flags, operations, execution hooks,
introspection, test database creation, and optional client helpers.

Each configured database alias (``default``, ``replica``, etc.) is backed by
exactly one ``DatabaseBackend`` instance.

.. note::

   ``DatabaseBackend`` controls the **core SQL database layer**.
   ``VirtualBackend`` controls **per-model custom data sources** (REST APIs,
   in-memory stores, etc.).  If ``model._meta.virtual`` is ``True``, use
   ``VirtualBackend`` routing, not ``DatabaseBackend`` routing.

DATABASES Configuration
========================

The ``DATABASES`` setting is a dictionary mapping alias names to configuration
dictionaries.  See :doc:`installation` for the full configuration reference
including pool options, URL formats, and the nested vs flat config format.

A minimal configuration requires only a ``URL``:

.. code-block:: python

   DATABASES = {
       "default": {
           "OPTIONS": {
               "URL": "postgresql://user:pass@primary-db/app",
           },
       },
   }

Multi-database setups with read replicas are covered in
:doc:`database_routing`.

BACKEND is Optional
====================

The ``BACKEND`` key is optional when using the built-in SQLAlchemy backend.
When omitted, OpenViper uses ``DefaultDatabaseBackend`` (SQLAlchemy async
engine).  Use the short name ``"sqlalchemy"`` or the full dotted path
``"openviper.db.backends.DefaultDatabaseBackend"`` for the built-in backend.

.. code-block:: python

   # Omit BACKEND (uses DefaultDatabaseBackend):
   DATABASES = {
       "default": {
           "OPTIONS": {
               "URL": "postgresql+asyncpg://user:pass@localhost/app",
               "POOL_SIZE": 20,
           },
       },
   }

   # Short name (equivalent to omitting BACKEND):
   DATABASES = {
       "default": {
           "BACKEND": "sqlalchemy",
           "OPTIONS": {
               "URL": "postgresql+asyncpg://user:pass@localhost/app",
           },
       },
   }

   # Custom backend (BACKEND is required):
   DATABASES = {
       "default": {
           "BACKEND": "myproject.db.backends.MetricsDatabaseBackend",
           "OPTIONS": {
               "URL": "postgresql+asyncpg://user:pass@localhost/app",
           },
       },
   }

An empty ``BACKEND`` string raises ``DatabaseConfigurationError``.  A
non-string ``BACKEND`` value also raises ``DatabaseConfigurationError``.

Custom backend import paths must be under ``openviper.db.backends.`` or
``openviper.contrib.`` - other paths are rejected for security.

See :doc:`installation` for pool options, URL formats, and the nested
vs flat config format.

DatabaseBackend
===============

.. class:: DatabaseBackend(alias, config)

   Abstract base class for all database backends.

   .. attribute:: vendor

      Short vendor name (e.g. ``"postgresql"``, ``"mysql"``, ``"sqlite"``).

   .. attribute:: display_name

      Human-readable backend name.

   .. attribute:: features

      ``DatabaseFeatures`` instance for this backend.

   .. attribute:: operations

      ``DatabaseOperations`` instance for this backend.

   .. attribute:: execution

      ``DatabaseExecution`` instance for this backend.

   .. attribute:: introspection

      ``DatabaseIntrospection`` instance for this backend.

   .. attribute:: creation

      ``DatabaseCreation`` instance for this backend.

   .. attribute:: client

      ``DatabaseClient`` instance for this backend.

   .. method:: create_engine()

      Create and return the async SQLAlchemy engine for this alias.

   .. method:: connect()

      Return an async database connection.

   .. method:: disconnect()

      Dispose backend resources.

   .. method:: execute(statement, parameters=None)

      Execute a SQLAlchemy statement through the execution hooks.

   .. method:: transaction(using=None)

      Return a transaction context manager.

   .. attribute:: url

      The configured database URL for this alias.  Reads from
      ``OPTIONS.URL`` first (nested config format), then falls back to
      ``URL`` directly in the config dict (flat format).

   .. attribute:: is_read_only

      Whether this alias is configured as read-only.  Reads from
      ``OPTIONS.READ_ONLY`` first, then ``READ_ONLY`` directly.

   .. attribute:: role

      The configured role (``"primary"`` or ``"replica"``).  Reads from
      ``OPTIONS.ROLE`` first, then ``ROLE`` directly.

   .. method:: get_option(key, default=None)

      Resolve a configuration key from ``OPTIONS`` first (nested format),
      then from the alias config directly (flat format).  Use this in
      custom backends to read pool options, driver settings, or any
      user-supplied configuration.

      .. code-block:: python

         pool_size = backend.get_option("POOL_SIZE", 20)
         echo = backend.get_option("ECHO", False)

DatabaseFeatures
================

.. class:: DatabaseFeatures

   Declares database capabilities for a configured backend alias.

   .. attribute:: supports_transactions

   .. attribute:: supports_savepoints

   .. attribute:: supports_json

   .. attribute:: supports_uuid

   .. attribute:: supports_returning

   .. attribute:: supports_bulk_insert

   .. attribute:: supports_foreign_keys

   .. attribute:: supports_indexes

   .. attribute:: supports_partial_indexes

   .. attribute:: supports_check_constraints

   .. attribute:: supports_schema_comments

   .. attribute:: supports_read_only_connections

Feature flags by vendor
------------------------

The built-in ``SQLAlchemyFeatures`` class sets feature flags based on the
database vendor.  The following table shows which features are enabled for
each supported vendor:

.. list-table::
   :header-rows: 1
   :widths: 15 10 10 10 10 10 10 10 10 10 10 10

   * - Vendor
     - trans
     - savept
     - json
     - uuid
     - ret
     - bulk
     - fk
     - idx
     - partial
     - check
     - comments
   * - postgresql
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - mysql
     - ✓
     - ✓
     - ✓
     - ✗
     - ✗
     - ✓
     - ✓
     - ✓
     - ✗
     - ✓
     - ✓
   * - sqlite
     - ✓
     - ✓
     - ✓
     - ✗
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✗
   * - mssql
     - ✓
     - ✓
     - ✓
     - ✗
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - oracle
     - ✓
     - ✓
     - ✓
     - ✗
     - ✓
     - ✓
     - ✓
     - ✓
     - ✗
     - ✓
     - ✓

DatabaseOperations
==================

.. class:: DatabaseOperations

   Provides OpenViper-level database-specific behaviour above SQLAlchemy.
   This does **not** replace SQLAlchemy's compiler.

   .. method:: normalize_url(url)

      Translate a synchronous database URL to its async driver equivalent.

   .. method:: extract_vendor(url)

      Return a short vendor name derived from the database URL.

   .. method:: quote_identifier(name)

      Quote a SQL identifier if it contains special characters.

   .. method:: adapt_value(value)

      Adapt a Python value before execution.

DatabaseExecution
==================

.. class:: DatabaseExecution

   Execution hook layer for instrumentation, logging, retries, and tracing.

   .. method:: pre_execute(statement, parameters=None)

      Called before a statement is executed.

   .. method:: post_execute(statement, parameters=None, duration=None)

      Called after a statement completes successfully.

   .. method:: on_error(statement, parameters=None, error=None)

      Called when statement execution raises an exception.

   .. method:: execute(connection, statement, parameters=None)

      Execute a SQLAlchemy statement through the hook lifecycle.

DatabaseIntrospection
=====================

.. class:: DatabaseIntrospection

   Reads schema information from a configured database alias.

   .. method:: get_table_names(connection)

   .. method:: get_columns(connection, table_name)

   .. method:: get_indexes(connection, table_name)

   .. method:: get_constraints(connection, table_name)

   .. method:: get_foreign_keys(connection, table_name)

DatabaseCreation
================

.. class:: DatabaseCreation(backend)

   Creates, destroys, and clones test databases.

   .. method:: create_test_database(engine)

   .. method:: destroy_test_database(engine)

   .. method:: clone_test_database(source_engine, target_engine)

Default SQLAlchemy Backend
============================

The built-in ``DefaultDatabaseBackend`` wraps OpenViper's existing
SQLAlchemy async engine behaviour.  It is the default when ``BACKEND`` is
omitted.

It supports all pool options (``POOL_SIZE``, ``MAX_OVERFLOW``,
``POOL_RECYCLE``, ``POOL_TIMEOUT``, ``PREPARED_STMT_CACHE``, ``ECHO``),
automatic async driver detection, SQLite in-memory handling, and
per-request connection pinning.

Creating a Custom Backend
==========================

The most common way to extend the database layer is to subclass
``DefaultDatabaseBackend`` and override only the methods you need.  This
preserves all built-in engine creation, pool configuration, and connection
management while letting you add instrumentation, retry logic, or
dialect-specific behaviour.

.. code-block:: python

   from openviper.db.backends.sqlalchemy import DefaultDatabaseBackend
   from openviper.db.backends.execution import DatabaseExecution
   from collections.abc import Mapping
   from typing import Any

   class MetricsExecution(DatabaseExecution):
       """Execution hooks that record query timing."""

       async def pre_execute(self, statement, parameters=None):
           # Start a metrics timer
           pass

       async def post_execute(self, statement, parameters=None, duration=None):
           # Record query duration
           pass

   class MetricsDatabaseBackend(DefaultDatabaseBackend):
       """Backend that adds metrics instrumentation on top of SQLAlchemy."""

       display_name = "SQLAlchemy with Metrics"

       def create_execution(self):
           return MetricsExecution()

   # Register it in settings:
   DATABASES = {
       "default": {
           "BACKEND": "myproject.db.backends.MetricsDatabaseBackend",
           "OPTIONS": {
               "URL": "postgresql+asyncpg://user:pass@localhost/app",
               "POOL_SIZE": 20,
           },
       },
   }

For advanced use cases where you need full control over engine creation,
subclass ``DatabaseBackend`` directly.  You must implement all abstract
methods:

.. code-block:: python

   from openviper.db.backends.database import DatabaseBackend
   from collections.abc import Mapping
   from typing import Any
   import sqlalchemy as sa
   from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
   from contextlib import asynccontextmanager
   from collections.abc import AsyncGenerator

   class CustomDatabaseBackend(DatabaseBackend):
       vendor = "custom"
       display_name = "Custom Database"

       async def create_engine(self) -> AsyncEngine:
           url = self.url
           echo = bool(self.get_option("ECHO", False))
           # Build engine with custom pool or driver settings
           return sa.ext.asyncio.create_async_engine(url, echo=echo)

       async def connect(self) -> AsyncConnection:
           engine = await self.create_engine()
           return engine.connect()

       async def disconnect(self) -> None:
           # Dispose engine and clean up resources
           pass

       async def execute(self, statement, parameters=None):
           engine = await self.create_engine()
           async with engine.connect() as conn:
               return await self.execution.execute(conn, statement, parameters)

       def transaction(self, using=None):
           return self.atomic()

       @asynccontextmanager
       async def atomic(self) -> AsyncGenerator[AsyncConnection, None]:
           engine = await self.create_engine()
           async with engine.begin() as conn:
               yield conn

   # Register it:
   DATABASES = {
       "default": {
           "BACKEND": "myproject.db.backends.CustomDatabaseBackend",
           "OPTIONS": {
               "URL": "custom://host/db",
           },
       },
   }

Config access in backends
-------------------------

Use :meth:`DatabaseBackend.get_option` to read configuration values from
the ``OPTIONS`` dict (nested format) or directly from the alias config
(flat format).  It resolves ``OPTIONS.<key>`` first, then falls back to
the top-level key:

.. code-block:: python

   class MyBackend(DefaultDatabaseBackend):
       async def create_engine(self):
           # Reads from OPTIONS.POOL_SIZE, then POOL_SIZE, then default 20
           pool_size = int(self.get_option("POOL_SIZE", 20))
           echo = bool(self.get_option("ECHO", False))
           ...

Properties :attr:`url`, :attr:`is_read_only`, and :attr:`role` also
resolve from ``OPTIONS`` first, then from the flat config:

.. code-block:: python

   backend = MyBackend("default", {
       "OPTIONS": {"URL": "postgresql+asyncpg://user:pass@localhost/db"},
       "ROLE": "primary",
   })
   backend.url          # "postgresql+asyncpg://user:pass@localhost/db"
   backend.role          # "primary"
   backend.is_read_only  # False

Instrumentation Example
========================

The ``DatabaseExecution`` hooks are the primary extension point for
instrumentation.  Override ``pre_execute`` and ``post_execute`` to add
timing, tracing spans, or audit logging.  Override ``on_error`` to add
error metrics or custom error mapping.

Testing a Backend
==================

Use the ``DatabaseCreation`` component to create and destroy test databases
per alias.  See :doc:`database_routing` for multi-database testing helpers.

Security Notes
===============

- Never log full database URLs containing credentials.
- Never expose database passwords in error messages.
- Prevent writes to ``READ_ONLY`` aliases.
- Use parameterized SQL execution via SQLAlchemy.
- Do not bypass SQLAlchemy safety mechanisms.

Limitations
============

- ``DatabaseBackend`` does not replace SQLAlchemy's SQL compiler.
- Custom backends must still use SQLAlchemy's async engine API.
- The backend API is designed for OpenViper integration points, not
  for implementing entirely new database protocols.
