.. _installation:

============
Installation
============

Requirements
------------

* **Python** ≥ 3.14
* A supported **async database driver** (see below)

Installing OpenViper
--------------------

Install from PyPI using ``pip``:

.. code-block:: bash

   pip install openviper

Optional Extras
~~~~~~~~~~~~~~~

OpenViper ships optional feature sets as pip extras:

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Extra
     - Install command
     - Installs
   * - ``postgres``
     - ``pip install openviper[postgres]``
     - ``asyncpg``, ``psycopg2-binary``
   * - ``mariadb``
     - ``pip install openviper[mariadb]``
     - ``aiomysql``
   * - ``mssql``
     - ``pip install openviper[mssql]``
     - ``aioodbc``
   * - ``oracle``
     - ``pip install openviper[oracle]``
     - ``oracledb``
   * - ``tasks``
     - ``pip install openviper[tasks]``
     - ``dramatiq``, ``redis``
   * - ``geolocation``
     - ``pip install openviper[geolocation]``
     - ``shapely``, ``psycopg2-binary``
   * - ``ai``
     - ``pip install openviper[ai]``
     - ``openai``, ``anthropic``, ``google-genai``
   * - ``all``
     - ``pip install openviper[all]``
     - All of the above

Development Extras
~~~~~~~~~~~~~~~~~~

Additional extras for contributing to OpenViper or building documentation:

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Extra
     - Install command
     - Installs
   * - ``dev``
     - ``pip install openviper[dev]``
     - ``pytest``, ``pytest-asyncio``, ``pytest-cov``, ``pytest-xdist``, ``httpx``, ``black``, ``isort``, ``ruff``, ``mypy``, ``pylint``, ``flake8``, ``radon``, ``bandit``, ``safety``, ``pre-commit``
   * - ``docs``
     - ``pip install openviper[docs]``
     - ``sphinx``, ``sphinx-rtd-theme``, ``sphinxcontrib-httpdomain``

.. note::

   The ``backup-db`` and ``restore-db`` management commands are included in the
   core package and do not require a separate install.

Multiple extras can be combined:

.. code-block:: bash

   pip install openviper[postgres,tasks]


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

Background tasks and rate-limiting require Redis.
Install redis:

.. code-block:: bash

   sudo apt install redis # Linux
   brew install redis # MacOS
   sudo dnf install redis # Fedora


Set the URL via the
``CACHE_URL`` / broker settings in ``settings.py``:

.. code-block:: python

   CACHE_URL = "redis://localhost:6379/0"

   # Background Tasks
   TASKS: dict[str, Any] = dataclasses.field(
       default_factory=lambda: {
           "log_to_file": True,
           "log_level": "DEBUG",
           "log_format": "json",
           "log_dir": "logs",
           "broker": "redis",
           "url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
           "result_backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
        }
    )

Verifying the Installation
---------------------------

After installing, the ``openviper`` CLI should be available:

.. parsed-literal::

   openviper version
   # OpenViper |release|

You can also verify from Python:

.. parsed-literal::

   import openviper
   print(openviper.__version__)   # |release|

Development Server
------------------

OpenViper ships with **Uvicorn** as its ASGI server.  Start the development
server with either:

.. code-block:: bash

   # Via management command (from inside a project)
   python viperctl.py start-server --reload # --host 127.0.0.1 --port 8000

.. seealso::

   See the Uvicorn and Gunicorn documentation for production-grade deployment configuration.
