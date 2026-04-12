.. _db_tools:

db_tools — Database Backup & Restore
=====================================

The ``db_tools`` plugin adds ``backup-db`` and ``restore-db`` management
commands to any OpenViper project.  Commands are auto-registered via Python
entry-points — no changes to ``INSTALLED_APPS`` or ``settings.py`` are
required.

Installation
------------

.. code-block:: bash

   pip install openviper[db-tools]

System Requirements
-------------------

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
-----

Backup a database
~~~~~~~~~~~~~~~~~

.. code-block:: bash

   python viperctl.py backup-db

Back up to a custom directory:

.. code-block:: bash

   python viperctl.py backup-db --path /var/backups/myapp

Custom filename prefix:

.. code-block:: bash

   python viperctl.py backup-db --name myapp_prod

Specify a database URL explicitly:

.. code-block:: bash

   python viperctl.py backup-db --db postgresql://user:pass@host/mydb

Skip compression (produce a plain ``.sql`` file):

.. code-block:: bash

   python viperctl.py backup-db --no-compress

Restore a database
~~~~~~~~~~~~~~~~~~

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
-------------------

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
--------------

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

Example metadata file:

.. code-block:: json

   {
     "database_name": "appdb",
     "db_engine": "postgres",
     "timestamp": "2026-04-04T12:12:12.000000+00:00",
     "filename": "appdb_20260404-121212.tar.gz",
     "openviper_version": "1.0.0",
     "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
   }

Filename Format
---------------

Backup files are named automatically using UTC datetime:

.. code-block:: text

   {database_name}_{YYYYMMDD-HHMMSS}.tar.gz

Examples:

.. code-block:: text

   postgres_20260404-121212.tar.gz
   sqlite_20260404-121212.tar.gz

Examples
--------

Development workflow
~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Quick backup before running migrations
   python viperctl.py backup-db --path ./backups

   # Apply migrations
   python viperctl.py migrate

   # Roll back if needed
   python viperctl.py restore-db ./backups/sqlite_20260404-121212.tar.gz --force

Production PostgreSQL backup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   python viperctl.py backup-db \
       --db postgresql://appuser:password@db.prod.internal/appdb \
       --path /backups/daily \
       --name appdb_daily

Restore workflow
~~~~~~~~~~~~~~~~

.. code-block:: bash

   # List available backups
   ls /backups/daily/

   # Restore the most recent archive
   python viperctl.py restore-db \
       /backups/daily/appdb_daily_20260404-020000.tar.gz \
       --db postgresql://appuser:password@db.prod.internal/appdb \
       --force

Automation & Scheduling
-----------------------

Cron (Linux / macOS)
~~~~~~~~~~~~~~~~~~~~

Schedule a nightly PostgreSQL backup at 02:00 UTC:

.. code-block:: bash

   # crontab -e
   0 2 * * * cd /srv/myapp && /srv/venv/bin/python viperctl.py backup-db \
       --path /backups/nightly \
       --name myapp_nightly \
       >> /var/log/openviper_backup.log 2>&1

Verify the checksum outside a cron job before restoring:

.. code-block:: bash

   sha256sum -c <(python -c "
   import json, sys
   m = json.load(open(sys.argv[1]))
   print(m['checksum'] + '  ' + m['filename'])
   " /backups/nightly/myapp_nightly_20260404-020000.tar.gz.meta.json)

GitHub Actions
~~~~~~~~~~~~~~

.. code-block:: yaml

   - name: Backup database
     run: |
       pip install openviper[db-tools,postgres]
       python viperctl.py backup-db \
           --db "$DATABASE_URL" \
           --path ./backups \
           --name ci_backup
     env:
       DATABASE_URL: ${{ secrets.DATABASE_URL }}

Error Handling
--------------

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
-----------------------

``backup-db`` arguments
~~~~~~~~~~~~~~~~~~~~~~~

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
     - Custom filename prefix
   * - ``--db``
     - string
     - ``DATABASE_URL``
     - Database URL (overrides settings)
   * - ``--compress``
     - flag
     - ``True``
     - Compress to ``.tar.gz``; use ``--no-compress`` to disable

``restore-db`` arguments
~~~~~~~~~~~~~~~~~~~~~~~~

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
     - Allow overwriting the target database on restore
