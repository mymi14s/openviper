.. _core:

Core & CLI
==========

The ``openviper.core`` package contains internal machinery for application
bootstrapping, request-context variables, and the flexible app resolver.
The ``viperctl`` CLI command provides management operations (migrations,
console, worker, etc.) for projects with non-standard directory layouts.

Overview
--------

``openviper.core`` is not typically used directly in application code.  It
exposes the following building blocks:

- **AppResolver** - discovers app modules from ``INSTALLED_APPS`` regardless
  of whether they live as sub-packages or flat modules on ``sys.path``.
- **Context variables** - ``current_user``, ``ignore_permissions_ctx``,
  ``current_request``, ``request_perms_cache``, and ``current_router``
  ContextVars that flow through the async task tree for the duration of
  a single request.
- **FlexibleAdapter** - bootstraps ``OPENVIPER_SETTINGS_MODULE`` and runs
  management commands; used by the ``viperctl`` CLI entry point.
- **Email subsystem** - async email delivery with template rendering,
  attachment resolution (files, URLs, bytes), SSRF protection, MIME
  validation, and pluggable backends (console, SMTP).

The ``viperctl`` sub-command is exposed through the ``openviper`` CLI (see
:ref:`cli` for the full ``openviper`` command reference) and supports the
following management commands:

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
   * - ``console``
     - Open a Python REPL with models and settings pre-loaded.
   * - ``start-worker``
     - Start the background task worker in-process.
   * - ``collectstatic``
     - Collect static assets into ``STATIC_ROOT``.
   * - ``create-app``
     - Scaffold a new app package with models, views, and routes.
   * - ``create-provider``
     - Scaffold a new AI provider package with tests and README.
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

.. py:data:: openviper.core.context.current_request

   :class:`contextvars.ContextVar` holding the current HTTP request object
   for the active async task.

.. py:data:: openviper.core.context.request_perms_cache

   :class:`contextvars.ContextVar` (``dict | None``) caching per-request
   permission lookups.  Defaults to ``None`` (not a mutable dict) to prevent
   cross-request cache leakage.

.. py:data:: openviper.core.context.current_router

   :class:`contextvars.ContextVar` holding the active
   :class:`~openviper.http.routing.Router` instance so that response helpers
   (e.g. ``RedirectResponse``) can resolve named routes.

.. py:function:: openviper.core.email.sender.send_email(recipients, subject, ...) -> bool

   Primary entry point for sending email.  Supports immediate or background
   delivery, Jinja2 templates, Markdown rendering, and attachments.

.. py:class:: openviper.core.email.attachments.AttachmentData

   Normalized attachment payload with ``filename``, ``content`` (bytes),
   and ``mimetype`` fields.

.. py:function:: openviper.core.email.attachments.resolve_attachments(attachments) -> list[AttachmentData]

   Resolve a mixed list of attachment inputs (bytes, dicts, tuples, file paths,
   URLs) into a list of :class:`AttachmentData` instances.

.. py:function:: openviper.core.email.templates.render_template_content(template, context=None, template_dir="templates") -> tuple[str | None, str | None]

   Render a Jinja2 template and return ``(text, html)``.  Markdown templates
   (``.md``) produce both text and HTML; ``.html`` templates produce HTML only;
   ``.txt`` templates produce text only.

.. py:class:: openviper.core.email.backends.EmailBackend

   Protocol that backends must implement.  Provides ``send(message_data)``.

.. py:class:: openviper.core.email.backends.ConsoleBackend

   Prints the email message to stdout.  Useful for development.

.. py:class:: openviper.core.email.backends.SMTPBackend

   Sends email via SMTP using ``EMAIL_*`` settings.

.. py:function:: openviper.core.email.attachments.is_private_hostname(hostname) -> bool

   Return ``True`` if *hostname* resolves to a private, loopback, link-local,
   or reserved IP address.  Used to block SSRF attacks on URL attachments.

.. py:function:: openviper.core.email.attachments.detect_mimetype(filename, content, explicit) -> str

   Determine MIME type preferring explicit hint, then magic bytes, then file
   extension.  Validates explicit types against the ``type/subtype`` format
   required by RFC 2045 §5.1.

Example Usage
-------------

Running Management Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are **two ways** to run ``viperctl`` commands:

**Using ``openviper viperctl``** (works from any project directory):

.. code-block:: bash

    # Auto-detect project from CWD (use '.' for current directory)
    openviper viperctl makemigrations .
    openviper viperctl migrate .

    # Specify a module name explicitly
    openviper viperctl --settings myproject.settings makemigrations myapp

    # Interactive console
    openviper viperctl console .

    # Start a background task worker
    openviper viperctl start-worker .

    # Collect static files
    openviper viperctl collectstatic .

    # Start the development server
    openviper viperctl start-server .

**Using ``python viperctl.py``** (from a project with a ``viperctl.py`` script):

.. code-block:: bash

    # Generated by 'openviper create-project'
    cd myproject
    python viperctl.py makemigrations
    python viperctl.py migrate
    python viperctl.py console
    python viperctl.py start-server
    python viperctl.py start-worker

Both approaches are equivalent.  ``openviper viperctl`` auto-discovers
the project layout from the current working directory, while
``python viperctl.py`` uses the settings module configured in the script.

**Target resolution for ``openviper viperctl``:**

- ``.`` - auto-detect the project from the current working directory.
  Works for both root-layout projects (e.g. ``examples/fx``) and
  module-organized projects (e.g. ``examples/ai_moderation_platform``).
- ``myproject`` - a dotted module path resolved relative to the CWD.

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

Email Subsystem
---------------

The ``openviper.core.email`` package provides async email delivery with
template rendering, attachment resolution, pluggable backends, and background
queue support.

Sending Email
~~~~~~~~~~~~~

The primary entry point is :func:`~openviper.core.email.sender.send_email`:

.. code-block:: python

    from openviper.core.email import send_email

    # Plain-text email
    await send_email(
        recipients=["user@example.com"],
        subject="Welcome",
        text="Hello from OpenViper!",
    )

    # HTML + text with a Jinja2 template
    await send_email(
        recipients=["user@example.com"],
        subject="Order Confirmation",
        template="order_confirmation.html",
        context={"order_id": "ABC-123"},
    )

    # Background delivery (enqueued to a worker)
    await send_email(
        recipients=["admin@example.com"],
        subject="Report Ready",
        text="Your report is available.",
        background=True,
    )

Key parameters:

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Parameter
     - Type
     - Description
   * - ``recipients``
     - ``list[str] | str``
     - Required. One or more email addresses.
   * - ``subject``
     - ``str``
     - Required. Email subject line.
   * - ``text``
     - ``str | None``
     - Plain-text body. Required unless ``template`` is provided.
   * - ``html``
     - ``str | None``
     - HTML body. If omitted and ``template`` ends in ``.md``, HTML is generated.
   * - ``template``
     - ``str | None``
     - Jinja2 template name (resolved against ``TEMPLATES_DIR``).
   * - ``context``
     - ``dict | None``
     - Template context variables.
   * - ``attachments``
     - ``list | None``
     - List of attachments (see below).
   * - ``background``
     - ``bool | None``
     - ``True`` to enqueue, ``False`` to send immediately, ``None`` for auto.
   * - ``fail_silently``
     - ``bool | None``
     - Suppress exceptions on delivery failure.
   * - ``sender``
     - ``str | None``
     - Override the ``DEFAULT_FROM_EMAIL`` sender address.

Template Rendering
~~~~~~~~~~~~~~~~~~

:func:`~openviper.core.email.templates.render_template_content` resolves
Jinja2 templates and optionally renders Markdown to HTML:

.. code-block:: python

    from openviper.core.email.templates import render_template_content

    # Markdown template → (text, html)
    text, html = render_template_content("welcome.md", context={"name": "Ada"})

    # HTML-only template → (None, html)
    text, html = render_template_content("invoice.html", context={"total": 99.0})

    # Plain-text template → (text, None)
    text, html = render_template_content("receipt.txt", context={"id": "TX-42"})

**Security:** Template names are validated to prevent path traversal.  Null
bytes, ``..`` sequences, absolute paths, and double-encoded sequences
(``%252f``) are all rejected with :exc:`ValueError`.

Attachments
~~~~~~~~~~~~

:func:`~openviper.core.email.attachments.resolve_attachments` accepts a
flexible mix of attachment inputs:

.. code-block:: python

    from openviper.core.email import send_email, AttachmentData

    # Bytes payload
    await send_email(
        recipients=["user@example.com"],
        subject="Report",
        text="See attached.",
        attachments=[
            AttachmentData(filename="report.csv", content=b"a,b\n1,2"),
        ],
    )

    # File path (must be inside ATTACHMENT_ALLOWED_DIRS)
    await send_email(
        recipients=["user@example.com"],
        subject="Log",
        text="Attached.",
        attachments=["/var/app/uploads/debug.log"],
    )

    # URL attachment (fetched over HTTP/HTTPS)
    await send_email(
        recipients=["user@example.com"],
        subject="Data",
        text="Fetched from remote.",
        attachments=["https://example.com/data.csv"],
    )

    # Dict with explicit mimetype
    await send_email(
        recipients=["user@example.com"],
        subject="Chart",
        text="See chart.",
        attachments=[{"content": b"...", "filename": "chart.png", "mimetype": "image/png"}],
    )

.. _attachment-security:

Attachment Security
~~~~~~~~~~~~~~~~~~

The attachment subsystem enforces multiple security layers:

**File path restrictions.**  ``ATTACHMENT_ALLOWED_DIRS`` is a module-level list
that gates which directories are safe for file attachments.  When empty
(the default), file attachments are **disabled entirely** - calling
:func:`~openviper.core.email.attachments.resolve_file_attachment` raises
:exc:`ValueError`.  Populate it with trusted directories:

.. code-block:: python

    from openviper.core.email import attachments

    attachments.ATTACHMENT_ALLOWED_DIRS = ["/var/app/uploads", "/tmp/attachments"]

All paths are resolved (``Path.resolve()``) and checked with
``is_relative_to()`` to prevent ``..`` traversal and symlink attacks.

**SSRF protection.**  URL attachments are validated before any network request:

- Only ``http`` and ``https`` schemes are allowed.
- :func:`~openviper.core.email.attachments.is_private_hostname` resolves the
  hostname and blocks private/loopback/link-local/reserved IP ranges.
- :func:`~openviper.core.email.attachments.NoRedirectHandler` rejects HTTP
  redirects so every target is validated before access.
- :func:`~openviper.core.email.attachments.validate_public_ip_address` checks
  the connected peer address to block DNS-rebinding attacks.
- Responses larger than ``MAX_ATTACHMENT_BYTES`` (25 MiB by default) are
  rejected.

**MIME type validation.**  Explicit MIME types passed via the ``mimetype``
key or tuple third element are validated against the ``type/subtype`` format
required by RFC 2045 §5.1.  Invalid values (e.g. ``"image"`` or
``"/png"``) raise :exc:`ValueError`.

**CRLF injection.**  Filenames are stripped of ``\\r`` and ``\\n`` characters
to prevent header injection in the generated MIME messages.

**Email address validation.**  Control characters (``\\x00``–``\\x1f``,
``\\x7f``) in recipient addresses are rejected by
:func:`~openviper.core.email.sender.normalize_addresses`.

Delivery Backends
~~~~~~~~~~~~~~~~~

Two built-in backends are provided:

- :class:`~openviper.core.email.backends.ConsoleBackend` - prints the message
  to stdout (useful for development).
- :class:`~openviper.core.email.backends.SMTPBackend` - sends via SMTP using
  the ``EMAIL_*`` settings.

The backend is selected via the ``EMAIL_BACKEND`` setting key (defaults to
``"console"``).  Custom backends can implement the
:class:`~openviper.core.email.backends.EmailBackend` protocol.

Background Queue
~~~~~~~~~~~~~~~~

When ``background=True`` is passed to :func:`~openviper.core.email.sender.send_email`,
the message is serialized and enqueued for a worker process:

.. code-block:: python

    from openviper.core.email.queue import enqueue_email_job, worker_available

    if worker_available():
        await send_email(..., background=True)   # enqueued
    else:
        await send_email(..., background=False)   # immediate fallback

:func:`~openviper.core.email.queue.enqueue_email_job` serializes the
:class:`~openviper.core.email.message.EmailMessageData` payload and dispatches
it to the configured task broker.

Context Variables
~~~~~~~~~~~~~~~~~

The email subsystem uses the following module-level configuration:

.. py:data:: openviper.core.email.attachments.ATTACHMENT_ALLOWED_DIRS

   A ``list[str]`` of directory paths that are safe for file attachment
   resolution.  When empty (the default), file attachments are disabled
   entirely.  Populate with trusted directories before using file-path
   attachments.

.. py:data:: openviper.core.email.attachments.MAX_ATTACHMENT_BYTES

   Maximum size (in bytes) for a single attachment.  Defaults to 25 MiB.
   Attachments exceeding this limit raise :exc:`ValueError`.

.. py:data:: openviper.core.email.attachments.ALLOWED_URL_SCHEMES

   A ``set`` of permitted URL schemes for remote attachments.  Defaults to
   ``{"http", "https"}``.

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
     - SQLite is backed up by file copy - no extra tools needed

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
