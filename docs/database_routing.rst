.. _database_routing:

======================================
Database Routing and Read/Write Replicas
======================================

Overview
========

OpenViper supports multiple database aliases and a router system that
chooses which alias should handle a read, write, migration, or relation
operation.  This enables read/write splitting with replicas, per-app
database selection, and tenant-specific routing.

See :doc:`installation` for the full ``DATABASES`` configuration reference
including pool options, URL formats, and the nested vs flat config format.
See :doc:`database_backends` for backend registration and custom backends.

DATABASES ROUTERS Setting
==========================

``DATABASES['ROUTERS']`` is a list of import paths or router instances.
Routers are checked in order; the first non-``None`` result wins.

.. code-block:: python

   DATABASES = {
       "default": {
           "OPTIONS": {"URL": "postgresql+asyncpg://user:pass@primary/db"},
       },
       "ROUTERS": [
           "myproject.db.routers.PrimaryReplicaRouter",
       ],
       "ROUTING": {
           "primary_alias": "default",
           "replica_aliases": ["replica"],
       },
   }

Primary and Replica Databases
==============================

A **primary** database accepts both reads and writes.  A **replica**
database is typically read-only and receives a copy of the primary's
data via database replication.

Configure the ``ROLE`` key to declare each alias's role:

- ``"primary"`` - read/write (default)
- ``"replica"`` - typically read-only

Set ``READ_ONLY: True`` on replica aliases to prevent accidental writes.

PrimaryReplicaRouter
=====================

OpenViper includes a built-in ``PrimaryReplicaRouter``:

.. code-block:: python

   from openviper.db.routing import PrimaryReplicaRouter

   router = PrimaryReplicaRouter(
       primary_alias="default",
       replica_aliases=["replica"],
       read_your_writes=True,
       replica_selection="round_robin",
   )

Behaviour:

- **db_for_read**: Routes to a replica unless read-your-writes is active.
- **db_for_write**: Routes to the primary and marks the context as write-used.
- **allow_migrate**: Returns ``True`` only for the primary alias by default.
- **allow_relation**: Allows relations between primary and its replicas.

Read-Your-Writes
=================

After a write operation, subsequent reads in the same request context
are routed to the primary database to avoid replication lag bugs.

This is controlled by the ``read_your_writes`` flag on
``PrimaryReplicaRouter`` (default: ``True``).

The routing context is automatically reset at the end of each request
or test.

QuerySet.using
==============

Manually override the router for a specific query chain:

.. code-block:: python

   # Read from a specific replica
   users = await User.objects.using('replica').all()

   # Write to a specific alias
   await User.objects.using('default').create(email='a@example.com')

The ``using()`` method is preserved across cloned QuerySets:

.. code-block:: python

   qs = User.objects.using('replica').filter(is_active=True)
   # qs still uses 'replica'

Transactions
============

Use ``transaction()`` to pin a block of ORM operations to a specific
database alias:

.. code-block:: python

   from openviper.db.connection import transaction

   async with transaction(using='default'):
       await Post.objects.create(title="Hello")
       await Tag.objects.create(name="python")
       # Both committed on 'default'

Read-only transactions on replica aliases are allowed:

.. code-block:: python

   async with transaction(using='replica', read_only=True):
       posts = await Post.objects.using('replica').all()

Write transactions on read-only aliases raise ``DatabaseReadOnlyError``.

Migrations
===========

Migrations run on the primary (``default``) database by default.
Replicas do not receive migrations unless a router's ``allow_migrate``
explicitly allows it.

.. code-block:: bash

   openviper migrate
   openviper migrate --database default
   openviper migrate --database analytics

Admin Behaviour
================

Admin operations use the primary database by default for consistency.
Admin writes and deletes always go to primary.  This ensures data
integrity under replica routing.

Testing Multi-Database Routing
===============================

OpenViper provides testing helpers for multi-database setups:

.. code-block:: python

   from openviper.testing.database import (
       build_multi_database_config,
       setup_test_databases,
       teardown_test_databases,
       DatabaseAliasTracker,
   )

   # Build a test config with primary and replica
   config = build_multi_database_config(
       primary_url="sqlite+aiosqlite:///:memory:",
       replica_urls=["sqlite+aiosqlite:///:memory:"],
   )

   # Setup
   await setup_test_databases(config)

   # Track which alias was used
   tracker = DatabaseAliasTracker()
   tracker.record_read("replica", User)
   tracker.assert_db_used("replica", for_read=True)

   # Teardown
   await teardown_test_databases()

Best Practices
===============

- Always set ``READ_ONLY: True`` on replica aliases.
- Use ``read_your_writes=True`` to avoid replication lag bugs.
- Keep migrations on the primary database.
- Use ``.using()`` sparingly - let routers do the routing.
- Reset routing context in tests using ``reset_routing_context()``.
- Never log full database URLs with credentials.

Limitations
============

- ``DatabaseRouter`` is async - all router methods are coroutines.
- ``allow_relation`` only works for objects that carry a ``_db_alias``
  attribute (set by the ORM when routing is active).
- Replica selection strategies beyond ``first`` and ``round_robin`` are
  not yet implemented.
