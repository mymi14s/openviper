.. _cli:

Command-Line Interface
=======================

The ``openviper`` command provides project scaffolding and a development
server.  It is installed automatically with the framework and is the primary
entry point for creating new projects, generating app scaffolds, and running
the ASGI server.

Management commands (migrations, superuser creation, task workers, etc.) are
handled by the ``viperctl`` sub-command documented in :ref:`core`.

.. rubric:: Global options

.. code-block:: bash

   openviper --version          # print framework version
   openviper --help             # list all commands

----

create-project
--------------

Scaffold a new OpenViper project with settings, ASGI entry point, routes,
views, templates, and a ``.gitignore``.

.. code-block:: bash

   openviper create-project myblog

This creates the following layout:

.. code-block:: text

   myblog/
   ├── viperctl.py
   ├── .gitignore
   ├── static/
   ├── templates/
   │   └── home.html
   ├── tests/
   │   └── __init__.py
   └── myblog/
       ├── __init__.py
       ├── settings.py
       ├── asgi.py
       ├── routes.py
       └── views.py

**Arguments:**

.. list-table::
   :header-rows: 1
   :widths: 15 12 73

   * - Argument
     - Type
     - Description
   * - ``NAME``
     - string
     - Required. A valid Python identifier used as the project package name.

**Options:**

.. list-table::
   :header-rows: 1
   :widths: 20 12 20 48

   * - Option
     - Type
     - Default
     - Description
   * - ``--directory`` / ``-d``
     - string
     - CWD
     - Parent directory in which the project folder is created.

**Generated files:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - File
     - Purpose
   * - ``viperctl.py``
     - Per-project management CLI entry point (``python viperctl.py <command>``).
   * - ``<name>/settings.py``
     - Frozen dataclass subclassing :class:`~openviper.conf.Settings` with
       ``DATABASE_URL``, ``SECRET_KEY``, and ``INSTALLED_APPS`` pre-configured.
   * - ``<name>/asgi.py``
     - ASGI application module that bootstraps ``OPENVIPER_SETTINGS_MODULE``
       and creates the :class:`~openviper.app.OpenViper` instance.
   * - ``<name>/routes.py``
     - Top-level route definitions wiring admin and root routers.
   * - ``<name>/views.py``
     - Example async views (HTML home page and JSON API index).
   * - ``templates/home.html``
     - Starter Jinja2 template rendered by the home view.
   * - ``.gitignore``
     - Standard Python ``.gitignore`` (``__pycache__``, ``.env``, ``db.sqlite3``, etc.).

A cryptographically random ``SECRET_KEY`` is generated and embedded in
``settings.py`` for development.  **Set the ``SECRET_KEY`` environment
variable to a separate strong value in production.**

After scaffolding, start the development server:

.. code-block:: bash

   cd myblog
   python viperctl.py start-server

create-app
----------

Scaffold a new app package inside an existing OpenViper project.  Delegates
to ``viperctl create-app`` (see :ref:`core`).

.. code-block:: bash

   openviper create-app blog

**Arguments:**

.. list-table::
   :header-rows: 1
   :widths: 15 12 73

   * - Argument
     - Type
     - Description
   * - ``NAME``
     - string
     - Required. A valid Python identifier used as the app package name.

**Options:**

.. list-table::
   :header-rows: 1
   :widths: 20 12 20 48

   * - Option
     - Type
     - Default
     - Description
   * - ``--directory`` / ``-d``
     - string
     - CWD
     - Target directory containing the project.

run
---

Run an OpenViper ASGI application with uvicorn.

.. code-block:: bash

   openviper run app
   openviper run app.py
   openviper run myproject.asgi:app

The ``TARGET`` argument is resolved as follows:

- ``app.py`` is stripped to ``app`` (module import convention).
- ``module:attr`` syntax selects a specific ASGI callable; the default
  attribute is ``app``.
- The current working directory is added to ``sys.path`` so bare module
  names resolve without installation.

**Arguments:**

.. list-table::
   :header-rows: 1
   :widths: 15 12 73

   * - Argument
     - Type
     - Description
   * - ``TARGET``
     - string
     - Required. Module or ``module:attr`` containing the ASGI application.

**Options:**

.. list-table::
   :header-rows: 1
   :widths: 25 12 20 43

   * - Option
     - Type
     - Default
     - Description
   * - ``--host`` / ``-h``
     - string
     - ``127.0.0.1``
     - Bind address.
   * - ``--port`` / ``-p``
     - int
     - ``8000``
     - Bind port.
   * - ``--reload`` / ``--no-reload``
     - flag
     - ``True``
     - Auto-reload on file changes. When enabled, workers is forced to 1.
   * - ``--workers`` / ``-w``
     - int
     - ``1``
     - Number of worker processes (ignored when ``--reload`` is set).

**Examples:**

.. code-block:: bash

   # Development with auto-reload
   openviper run app --reload

   # Production with 4 workers
   openviper run myproject.asgi:app --no-reload --workers 4

   # Bind to all interfaces on port 8080
   openviper run app --host 0.0.0.0 --port 8080

version
-------

Print the installed OpenViper version.

.. code-block:: bash

   openviper version

viperctl (sub-command)
----------------------

Dispatches per-project management commands.  Full documentation is in
:ref:`core`.

.. code-block:: bash

   openviper viperctl makemigrations .
   openviper viperctl migrate .
   openviper viperctl --settings myproject.settings console

Supported commands: ``makemigrations``, ``migrate``, ``console``,
``start-server``, ``start-worker``, ``collectstatic``, ``test``,
``createsuperuser``, ``changepassword``.
