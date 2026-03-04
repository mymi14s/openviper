.. _cli:

============
CLI Commands
============

OpenViper provides two entry-points for command-line interaction:

1. **``openviper``** — the global CLI (available after ``pip install openviper``)
   for scaffolding new projects and apps, and for running apps directly with
   ``openviper run <app>`` e.g ``openviper run app.py``.
2. **``python viperctl.py``** — the per-project management command runner,
   similar to Django's ``viperctl.py``.

.. contents:: On this page
   :local:
   :depth: 2

----

Global CLI (``openviper``)
---------------------------

verify the installation:

.. code-block:: bash

   openviper version
   # OpenViper 0.0.1

``create-project``
~~~~~~~~~~~~~~~~~~

Scaffold a new OpenViper project:

.. code-block:: bash

   openviper create-project <name> [--directory DIR]

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Argument
     - Description
   * - ``<name>``
     - Project and top-level Python package name
   * - ``--directory, -d``
     - Parent directory in which to create the project (default: current directory)

Example:

.. code-block:: bash

   openviper create-project myblog --directory /home/user/projects
   # Creates /home/user/projects/myblog/

Generated layout:

.. code-block:: text

   myblog/
   ├── myblog/
   │   ├── __init__.py
   │   ├── asgi.py
   │   ├── settings.py
   │   └── routes.py
   └── viperctl.py

``create-app`` (global)
~~~~~~~~~~~~~~~~~~~~~~~~

Create a new app from outside the project directory:

.. code-block:: bash

   openviper create-app <name> [--directory DIR]

``run``
~~~~~~~

Start an OpenViper application directly with Uvicorn — no ``viperctl.py``
needed.  Useful for single-file apps and microservices.

.. code-block:: bash

   openviper run app
   openviper run app.py            # .py extension is stripped automatically
   openviper run myproject.asgi:app  # explicit module:attribute

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Description
   * - ``--host, -h``
     - Bind host (default ``127.0.0.1``)
   * - ``--port, -p``
     - Bind port (default ``8000``)
   * - ``--reload``
     - Enable auto-reload on file changes (forces ``--workers 1``)
   * - ``--workers, -w``
     - Number of Uvicorn worker processes (default ``1``; ignored when ``--reload`` is set)

The current working directory is added to ``sys.path`` automatically so bare
module names (e.g. ``app``) resolve without package prefixes.

Example — run the miniapp on a custom port with reload:

.. code-block:: bash

   cd examples/todoapp
   openviper run app --reload

``version``
~~~~~~~~~~~

.. code-block:: bash

   openviper version

----

Management Commands (``python viperctl.py``)
--------------------------------------------

All commands below are run from the project root (where ``viperctl.py`` lives).

``runserver``
~~~~~~~~~~~~~

Start the ASGI development server with Uvicorn:

.. code-block:: bash

   python viperctl.py runserver
   python viperctl.py runserver 0.0.0.0:8080

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Description
   * - ``<address>:<port>``
     - Bind address and port (default ``127.0.0.1:8000``)
   * - ``--reload / --no-reload``
     - Enable/disable auto-reload on code changes (default: enabled)
   * - ``--workers N``
     - Number of Uvicorn worker processes (default ``1``)

``runworker``
~~~~~~~~~~~~~

Start the Dramatiq background task worker:

.. code-block:: bash

   python viperctl.py runworker
   python viperctl.py runworker --queues emails,reports
   python viperctl.py runworker --threads 4

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Description
   * - ``--queues Q1,Q2``
     - Comma-separated list of queues to consume (default: all)
   * - ``--threads N``
     - Worker thread count per process (default ``8``)

``makemigrations``
~~~~~~~~~~~~~~~~~~

Detect model changes and generate migration files:

.. code-block:: bash

   python viperctl.py makemigrations
   python viperctl.py makemigrations blog
   python viperctl.py makemigrations blog --name add_slug_field
   python viperctl.py makemigrations blog --empty

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Description
   * - ``<app_name>``
     - Limit detection to a single app (optional)
   * - ``--name NAME``
     - Override the auto-generated migration filename suffix
   * - ``--empty``
     - Create an empty migration stub for manual SQL

``migrate``
~~~~~~~~~~~

Apply pending migrations to the database:

.. code-block:: bash

   python viperctl.py migrate
   python viperctl.py migrate blog
   python viperctl.py migrate blog 0003
   python viperctl.py migrate blog --fake
   python viperctl.py migrate blog 0001 --fake-initial

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Description
   * - ``<app_name>``
     - Apply only a specific app's migrations
   * - ``<migration_name>``
     - Target migration (rolls back or forward to this state)
   * - ``--fake``
     - Mark migrations as applied without executing SQL
   * - ``--fake-initial``
     - Fake if tables already exist (idempotent initial migration)

``createsuperuser``
~~~~~~~~~~~~~~~~~~~

Create a superuser account interactively or non-interactively:

.. code-block:: bash

   python viperctl.py createsuperuser

   # Non-interactive
   python viperctl.py createsuperuser \
       --username admin \
       --email admin@example.com \
       --noinput

``changepassword``
~~~~~~~~~~~~~~~~~~

Change an existing user's password:

.. code-block:: bash

   python viperctl.py changepassword <username>

``shell``
~~~~~~~~~

Start an interactive Python shell with the OpenViper application context
pre-loaded (settings configured, ORM available):

.. code-block:: bash

   python viperctl.py shell

Inside the shell you can run async operations with ``asyncio.run()``:

.. code-block:: python

   import asyncio
   from blog.models import Post

   posts = asyncio.run(Post.objects.filter(published=True).all())

``test``
~~~~~~~~

Run the test suite:

.. code-block:: bash

   python viperctl.py test
   python viperctl.py test blog
   python viperctl.py test blog.tests.PostTestCase
   python viperctl.py test --verbosity 2
   python viperctl.py test --failfast

``collectstatic``
~~~~~~~~~~~~~~~~~

Collect all static files into ``STATIC_ROOT`` for production serving:

.. code-block:: bash

   python viperctl.py collectstatic

``create-app``
~~~~~~~~~~~~~~

Scaffold a new app within the current project:

.. code-block:: bash

   python viperctl.py create-app <name> [--directory DIR]

Generated layout:

.. code-block:: text

   <name>/
   ├── __init__.py
   ├── models.py
   ├── serializers.py
   ├── views.py
   ├── routes.py
   ├── admin.py
   ├── tasks.py
   └── migrations/
       └── __init__.py

``create-command``
~~~~~~~~~~~~~~~~~~

Scaffold a new management command:

.. code-block:: bash

   python viperctl.py create-command <name>

Creates ``<app>/management/commands/<name>.py`` with a ``BaseCommand``
subclass ready to implement.

``create-provider``
~~~~~~~~~~~~~~~~~~~

Scaffold a new AI provider stub:

.. code-block:: bash

   python viperctl.py create-provider <name>

Creates ``<name>_provider.py`` with a :class:`~openviper.ai.base.AIProvider`
subclass skeleton.

----

Writing Custom Management Commands
------------------------------------

Subclass :class:`~openviper.core.management.base.BaseCommand`:

.. code-block:: python

   # myapp/management/commands/seed_data.py
   from openviper.core.management.base import BaseCommand


   class Command(BaseCommand):
       help = "Seed the database with sample blog posts."

       def add_arguments(self, parser):
           parser.add_argument("--count", type=int, default=10)

       def handle(self, *args, **options):
           import asyncio
           from blog.models import Post

           count = options["count"]

           async def _seed():
               for i in range(count):
                   await Post.objects.create(
                       title=f"Sample Post {i + 1}",
                       body=f"Body of post {i + 1}.",
                       published=True,
                   )

           asyncio.run(_seed())
           self.stdout(self.style_success(f"Created {count} posts."))

Run it:

.. code-block:: bash

   python viperctl.py seed_data --count 5
