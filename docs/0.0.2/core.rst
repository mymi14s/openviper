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
