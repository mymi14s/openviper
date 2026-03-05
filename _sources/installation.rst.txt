.. _installation:

============
Installation
============

Requirements
------------

* **Python** ≥ 3.14
* A supported **async database driver** (see below)
* **Redis** 6+ (required when using background tasks or the Dramatiq broker)
* **Uvicorn** (included as a dependency, used to serve the ASGI application)

Installing OpenViper
--------------------

Install from PyPI using ``pip``:

.. code-block:: bash

   pip install openviper

This installs the core framework with all mandatory dependencies.

Optional Extras
~~~~~~~~~~~~~~~

OpenViper ships optional dependency groups that you can install on demand:

.. code-block:: bash

   # PostgreSQL async driver (asyncpg)
   pip install "openviper[postgresql]"

   # MariaDB / MySQL async driver (aiomysql)
   pip install "openviper[mariadb]"

   # AI provider SDKs (openai, anthropic, google-generativeai, …)
   pip install "openviper[ai]"

   # Background task broker and worker (dramatiq + redis)
   pip install "openviper[tasks]"

   # Admin panel Vue SPA and API (already bundled but listed for clarity)
   pip install "openviper[admin]"

   # Everything at once
   pip install "openviper[all]"

Database URL Format
-------------------

OpenViper uses SQLAlchemy Core connection strings.  Set ``DATABASE_URL`` in your
``settings.py``:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Backend
     - DATABASE_URL example
   * - SQLite (dev)
     - ``sqlite+aiosqlite:///./db.sqlite3``
   * - PostgreSQL
     - ``postgresql+asyncpg://user:pass@localhost:5432/mydb``
   * - MariaDB / MySQL
     - ``mysql+aiomysql://user:pass@localhost:3306/mydb``

Redis Configuration
-------------------

Background tasks and rate-limiting require Redis.  Set the URL via the
``CACHE_URL`` / broker settings in ``settings.py``:

.. code-block:: python

   CACHE_URL = "redis://localhost:6379/0"

   TASKS = {
       "broker_url": "redis://localhost:6379/1",
   }

Verifying the Installation
---------------------------

After installing, the ``openviper`` CLI should be available:

.. code-block:: bash

   openviper version
   # OpenViper 0.0.1

You can also verify from Python:

.. code-block:: python

   import openviper
   print(openviper.__version__)   # 0.0.1

Development Server
------------------

OpenViper ships with **Uvicorn** as its ASGI server.  Start the development
server with either:

.. code-block:: bash

   # Via management command (from inside a project)
   python viperctl.py runserver

   # Or directly with uvicorn
   uvicorn myproject.asgi:app --reload --host 127.0.0.1 --port 8000

.. seealso::

   :ref:`deployment` for production-grade Uvicorn configuration.
