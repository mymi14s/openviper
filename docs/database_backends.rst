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
dictionaries.  Each alias must include at least a ``URL`` key.

.. code-block:: python

   DATABASES = {
       "default": {
           "URL": "postgresql://user:pass@primary-db/app",
           "ROLE": "primary",
       },
       "replica": {
           "URL": "postgresql://user:pass@replica-db/app",
           "ROLE": "replica",
           "READ_ONLY": True,
       },
   }

BACKEND is Optional
====================

The ``BACKEND`` key is **optional** in each alias config.  When omitted or
set to ``None``, OpenViper uses the default
``DefaultDatabaseBackend``.

.. code-block:: python

   # Both of these use DefaultDatabaseBackend:
   DATABASES = {
       "default": {
           "URL": "postgresql://user:pass@primary-db/app",
       },
   }

   DATABASES = {
       "default": {
           "BACKEND": "DefaultDatabaseBackend",
           "URL": "postgresql://user:pass@primary-db/app",
       },
   }

An empty ``BACKEND`` string raises ``DatabaseConfigurationError``.  A
non-string ``BACKEND`` value also raises ``DatabaseConfigurationError``.

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

Creating a Custom Backend
==========================

Subclass ``DatabaseBackend`` and override the methods you need:

.. code-block:: python

   from openviper.db.backends.database import DatabaseBackend
   from openviper.db.backends.execution import DatabaseExecution
   from collections.abc import Mapping
   from typing import Any
   import sqlalchemy as sa
   from sqlalchemy.ext.asyncio import AsyncEngine

   class MetricsExecution(DatabaseExecution):
       async def pre_execute(self, statement, parameters=None):
           # Start a metrics timer
           pass

       async def post_execute(self, statement, parameters=None, duration=None):
           # Record query duration
           pass

   class MetricsDatabaseBackend(DatabaseBackend):
       vendor = "sqlalchemy"
       display_name = "SQLAlchemy with Metrics"

       def create_execution(self):
           return MetricsExecution()

       async def create_engine(self) -> AsyncEngine:
           # Delegate to DefaultDatabaseBackend logic
           ...

       async def connect(self):
           ...

       async def disconnect(self):
           ...

       async def execute(self, statement, parameters=None):
           ...

       def transaction(self, using=None):
           ...

Then configure it:

.. code-block:: python

   DATABASES = {
       "default": {
           "BACKEND": "myproject.db.backends.MetricsDatabaseBackend",
           "URL": "postgresql://user:pass@localhost/app",
       },
   }

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
