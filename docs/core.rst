.. _core:

Core & CLI
==========

The ``openviper.core`` package contains internal machinery for application
bootstrapping, request-context variables, and the flexible app resolver.
The ``viperctl`` CLI command provides management operations (migrations,
shell, worker, etc.) for projects with non-standard directory layouts.

Overview
--------

``openviper.core`` is not typically used directly in application code.  It
exposes the following building blocks:

- **AppResolver** — discovers app modules from ``INSTALLED_APPS`` regardless
  of whether they live as sub-packages or flat modules on ``sys.path``.
- **Context variables** — ``current_user`` and ``ignore_permissions_ctx``
  ContextVars that flow through the async task tree for the duration of
  a single request.
- **FlexibleAdapter** — bootstraps ``OPENVIPER_SETTINGS_MODULE`` and runs
  management commands; used by the ``viperctl`` CLI entry point.

The ``viperctl`` sub-command is exposed through the ``openviper`` CLI and
supports the following management commands:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Command
     - Description
   * - ``makemigrations``
     - Generate new migration files for changed models.
   * - ``migrate``
     - Apply pending migrations to the database.
   * - ``createsuperuser``
     - Interactively create an admin superuser.
   * - ``changepassword``
     - Change a user's password interactively.
   * - ``shell``
     - Open a Python REPL with models and settings pre-loaded.
   * - ``runworker``
     - Start the background task worker in-process.
   * - ``collectstatic``
     - Collect static assets into ``STATIC_ROOT``.
   * - ``test``
     - Run the project test suite via pytest.
   * - ``backup-db``
     - Create a compressed database backup archive.
   * - ``restore-db``
     - Restore a database from a ``.tar.gz`` or ``.sql`` backup archive.

Key Classes & Functions
-----------------------

.. py:class:: openviper.core.app_resolver.AppResolver

   Resolves physical filesystem paths for each entry in ``INSTALLED_APPS``.
   Handles both package-style apps (``myproject.blog``) and flat modules.

   .. py:method:: get_app_dirs() -> list[Path]

      Return a list of resolved directories for all installed apps.

.. py:data:: openviper.core.context.current_user

   :class:`contextvars.ContextVar` holding the authenticated user for the
   current async task.  Set by
   :class:`~openviper.auth.middleware.AuthenticationMiddleware`.

.. py:data:: openviper.core.context.ignore_permissions_ctx

   :class:`contextvars.ContextVar` (``bool``) used by the ORM permission
   layer.  When ``True``, all model-level permission checks are bypassed for
   the current async task.

Example Usage
-------------

Running Management Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Generate and apply migrations
    openviper viperctl makemigrations .
    openviper viperctl migrate .

    # Custom settings module
    openviper viperctl --settings myproject.settings makemigrations myapp

    # Interactive shell
    openviper viperctl shell

    # Start a background task worker
    openviper viperctl runworker .

    # Collect static files
    openviper viperctl collectstatic .

Accessing the Current User in Async Code
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.core.context import current_user

    async def my_service_function() -> None:
        user = current_user.get()
        if user and user.is_authenticated:
            print(f"Called by: {user.username}")

Bypassing Permissions for Internal Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.db.executor import bypass_permissions
    from myapp.models import SensitiveRecord

    async def migrate_records() -> None:
        with bypass_permissions():
            records = await SensitiveRecord.objects.all()
            for record in records:
                await record.save()

----

Database Backup & Restore
--------------------------

The ``backup-db`` and ``restore-db`` commands are built-in management commands
available in every project via ``viperctl.py``.

System Requirements
~~~~~~~~~~~~~~~~~~~

Each database engine requires the corresponding native CLI tools to be
installed and available on ``PATH``:

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Engine
     - Required tools
     - Install hint
   * - PostgreSQL
     - ``pg_dump``, ``psql``
     - ``apt install postgresql-client`` / ``brew install libpq``
   * - MariaDB / MySQL
     - ``mysqldump``, ``mysql``
     - ``apt install mariadb-client`` / ``brew install mariadb``
   * - Oracle
     - ``expdp``, ``impdp``
     - Included with Oracle Instant Client
   * - SQL Server
     - ``sqlcmd``
     - ``apt install mssql-tools`` / ODBC driver package
   * - SQLite
     - *(none)*
     - SQLite is backed up by file copy — no extra tools needed

Usage
~~~~~

Backup a database:

.. code-block:: bash

   python viperctl.py backup-db

Back up to a custom directory:

.. code-block:: bash

   python viperctl.py backup-db --path /var/backups/myapp

Custom filename (without extension):

.. code-block:: bash

   python viperctl.py backup-db --name myapp_prod

Specify a database URL explicitly:

.. code-block:: bash

   python viperctl.py backup-db --db postgresql://user:pass@host/mydb

Skip compression (produce a plain ``.sql`` file):

.. code-block:: bash

   python viperctl.py backup-db --no-compress

Restore from an archive:

.. code-block:: bash

   python viperctl.py restore-db postgres_20260404-121212.tar.gz

Force overwrite of the existing database:

.. code-block:: bash

   python viperctl.py restore-db postgres_20260404-121212.tar.gz --force

Restore to an explicit database URL:

.. code-block:: bash

   python viperctl.py restore-db backup.tar.gz --db postgresql://user:pass@host/mydb

Restore from a plain SQL file:

.. code-block:: bash

   python viperctl.py restore-db backup.sql --db sqlite:///db.sqlite3

Supported Databases
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Engine
     - Backup Method
     - Restore Method
   * - SQLite
     - File copy (async)
     - File copy
   * - PostgreSQL
     - ``pg_dump --format=plain``
     - ``psql``
   * - MariaDB / MySQL
     - ``mysqldump``
     - ``mysql``
   * - Oracle
     - ``expdp`` (Data Pump)
     - ``impdp``
   * - SQL Server
     - ``sqlcmd BACKUP DATABASE``
     - ``sqlcmd RESTORE DATABASE``

Archive Format
~~~~~~~~~~~~~~

Each compressed backup produces a ``.tar.gz`` file containing:

.. code-block:: text

   postgres_20260404-121212.tar.gz
   └── backup.sql        # database dump or raw file copy

A sidecar metadata file is written alongside the archive:

.. code-block:: text

   postgres_20260404-121212.tar.gz.meta.json

.. list-table:: Metadata fields
   :header-rows: 1
   :widths: 25 75

   * - Field
     - Description
   * - ``database_name``
     - Logical name derived from the database URL
   * - ``db_engine``
     - Engine identifier (``sqlite``, ``postgres``, …)
   * - ``timestamp``
     - UTC ISO-8601 timestamp when the backup was taken
   * - ``filename``
     - Archive filename
   * - ``openviper_version``
     - Version of OpenViper used to create the backup
   * - ``checksum``
     - SHA-256 hex digest of the archive

Backup files are named automatically using UTC datetime:

.. code-block:: text

   {database_name}_{YYYYMMDD-HHMMSS}.tar.gz

Example filenames:

.. code-block:: text

   postgres_20260404-121212.tar.gz
   sqlite_20260404-121212.tar.gz

Workflow Examples
~~~~~~~~~~~~~~~~~

Backup before migrations:

.. code-block:: bash

   python viperctl.py backup-db --path ./backups
   python viperctl.py migrate
   # Roll back if needed:
   python viperctl.py restore-db ./backups/sqlite_20260404-121212.tar.gz --force

Production PostgreSQL backup:

.. code-block:: bash

   python viperctl.py backup-db \\
       --db postgresql://appuser:password@db.prod.internal/appdb \\
       --path /backups/daily \\
       --name appdb_daily

Restore workflow:

.. code-block:: bash

   python viperctl.py restore-db \\
       /backups/daily/appdb_daily_20260404-020000.tar.gz \\
       --db postgresql://appuser:password@db.prod.internal/appdb \\
       --force

Scheduled nightly backup (cron):

.. code-block:: bash

   # crontab -e
   0 2 * * * cd /srv/myapp && /srv/venv/bin/python viperctl.py backup-db \\
       --path /backups/nightly \\
       --name myapp_nightly \\
       >> /var/log/openviper_backup.log 2>&1

Error Handling
~~~~~~~~~~~~~~

Both commands exit with code ``1`` on failure and print an error message
to stderr.

.. list-table:: Common errors
   :header-rows: 1
   :widths: 45 55

   * - Error
     - Cause / fix
   * - ``No DATABASE_URL configured``
     - No ``DATABASE_URL`` in settings and ``--db`` not supplied.
   * - ``Unsupported database scheme '<scheme>'``
     - URL prefix not in the engine registry. Check the URL format.
   * - ``Backup file not found``
     - The path supplied to ``restore-db`` does not exist.
   * - ``No 'backup.sql' member found in archive``
     - Archive is corrupt or was not created by ``backup-db``.
   * - ``pg_dump`` / ``psql`` exits non-zero
     - PostgreSQL client tools not on ``PATH``, or wrong credentials.
   * - ``mysqldump`` / ``mysql`` exits non-zero
     - MariaDB/MySQL client tools not on ``PATH``, or wrong credentials.
   * - ``Path traversal detected``
     - ``--path`` or ``file`` argument contains ``..`` sequences.

Configuration Reference
~~~~~~~~~~~~~~~~~~~~~~~

``backup-db`` arguments:

.. list-table::
   :header-rows: 1
   :widths: 15 12 20 53

   * - Argument
     - Type
     - Default
     - Description
   * - ``--path``
     - string
     - ``./backup``
     - Directory to store backup archives
   * - ``--name``
     - string
     - auto-generated
     - Custom filename (without extension); defaults to ``{db_name}_{YYYYMMDD-HHMMSS}``
   * - ``--db``
     - string
     - ``DATABASE_URL``
     - Database URL (overrides settings)
   * - ``--compress`` / ``--no-compress``
     - flag
     - ``True``
     - Compress to ``.tar.gz``; use ``--no-compress`` for a plain ``.sql`` file

``restore-db`` arguments:

.. list-table::
   :header-rows: 1
   :widths: 15 12 20 53

   * - Argument
     - Type
     - Default
     - Description
   * - ``file``
     - string
     - *(required)*
     - Path to a ``.tar.gz`` or ``.sql`` backup file
   * - ``--db``
     - string
     - ``DATABASE_URL``
     - Database URL (overrides settings)
   * - ``--force``
     - flag
     - ``False``
     - Allow overwriting the target database without prompting
