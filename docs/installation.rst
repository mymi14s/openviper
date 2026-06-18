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
   * - ``geolocation``
     - ``pip install openviper[geolocation]``
     - ``shapely``, ``psycopg2-binary``
   * - ``ai``
     - ``pip install openviper[ai]``
     - ``openai``, ``anthropic``, ``google-genai``
   * - ``tasks``
     - ``pip install openviper[tasks]``
     - ``dramatiq``, ``croniter``, ``cron-descriptor``
   * - ``tasks-redis``
     - ``pip install openviper[tasks-redis]``
     - ``tasks`` + ``redis``
   * - ``tasks-rabbitmq``
     - ``pip install openviper[tasks-rabbitmq]``
     - ``tasks`` + ``pika``
   * - ``tasks-sqs``
     - ``pip install openviper[tasks-sqs]``
     - ``tasks`` + ``dramatiq-sqs``, ``boto3``
   * - ``tasks-postgresql``
     - ``pip install openviper[tasks-postgresql]``
     - ``tasks`` + ``dramatiq-pg``, ``psycopg2-binary``
   * - ``testing``
     - ``pip install openviper[testing]``
     - ``pytest``, ``pytest-asyncio``, ``httpx``
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
     - ``pytest``, ``pytest-asyncio``, ``pytest-xdist``, ``httpx``, ``ruff``, ``mypy``, ``pylint``, ``flake8``, ``radon``, ``bandit``, ``safety``, ``pre-commit``
   * - ``docs``
     - ``pip install openviper[docs]``
     - ``sphinx``, ``sphinx-rtd-theme``, ``sphinxcontrib-httpdomain``

.. note::

   The ``backup-db`` and ``restore-db`` management commands are included in the
   core package and do not require a separate install.

Multiple extras can be combined:

.. code-block:: bash

   pip install openviper[postgres,tasks-redis]


Database Configuration
----------------------

OpenViper uses a ``DATABASES`` dictionary in ``settings.py``:

.. code-block:: python

    DATABASES = {
        "default": {
            "BACKEND": "openviper.db.backends.DefaultDatabaseBackend",
            "OPTIONS": {
                "URL": "sqlite+aiosqlite:///./db.sqlite3",
                "ECHO": False,
                "POOL_SIZE": 20,
                "MAX_OVERFLOW": 80,
                "POOL_RECYCLE": 900,
                "POOL_TIMEOUT": 10,
            },
        },
    }

For PostgreSQL:

.. code-block:: python

    DATABASES = {
        "default": {
            "BACKEND": "openviper.db.backends.DefaultDatabaseBackend",
            "OPTIONS": {
                "URL": "postgresql+asyncpg://user:pass@localhost:5432/mydb",
                "POOL_SIZE": 20,
                "MAX_OVERFLOW": 80,
                "POOL_RECYCLE": 900,
                "POOL_TIMEOUT": 10,
                "PREPARED_STMT_CACHE": 256,
            },
        },
    }

The ``BACKEND`` key is optional.  When omitted, OpenViper uses the default
``DefaultDatabaseBackend`` (SQLAlchemy async engine).  The short name
``"sqlalchemy"`` is also accepted as an alias for
``"openviper.db.backends.DefaultDatabaseBackend"``.

Configuration keys can be placed either inside ``OPTIONS`` (nested format)
or directly in the alias dict (flat format).  Both are valid:

.. code-block:: python

    # Nested format (recommended):
    DATABASES = {
        "default": {
            "OPTIONS": {"URL": "postgresql+asyncpg://user:pass@localhost/db"},
        },
    }

    # Flat format (also supported):
    DATABASES = {
        "default": {
            "URL": "postgresql+asyncpg://user:pass@localhost/db",
        },
    }

Pool options:

.. list-table::
   :header-rows: 1
   :widths: 25 15 15 45

   * - Key
     - Default
     - Range
     - Description
   * - ``POOL_SIZE``
     - 20
     - 1-100
     - Number of persistent connections in the pool.
   * - ``MAX_OVERFLOW``
     - 80
     - 0-200
     - Additional connections allowed beyond ``POOL_SIZE``.
   * - ``POOL_RECYCLE``
     - 900
     - 60-86400
     - Recycle connections after this many seconds.
   * - ``POOL_TIMEOUT``
     - 10
     - 1-300
     - Seconds to wait for a connection from the pool.
   * - ``PREPARED_STMT_CACHE``
     - 256
     - 0-2048
     - asyncpg prepared-statement cache size (PostgreSQL only).
   * - ``ECHO``
     - False
     - -
     - Echo all SQL statements to the log.

Supported URL formats:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Database
     - URL format
   * - SQLite (dev)
     - ``sqlite+aiosqlite:///./db.sqlite3``
   * - PostgreSQL
     - ``postgresql+asyncpg://user:pass@localhost:5432/mydb``
   * - MariaDB / MySQL
     - ``mysql+aiomysql://user:pass@localhost:3306/mydb``

Custom database backends can be registered by dotted path:

.. code-block:: python

    DATABASES = {
        "default": {
            "BACKEND": "myapp.db.MyCustomBackend",
            "OPTIONS": {"URL": "custom://host/db"},
        },
    }

Message Broker Configuration
----------------------------

Background tasks require a message broker supported by Dramatiq.
OpenViper supports **Redis**, **RabbitMQ**, **Amazon SQS**, and **PostgreSQL**.

Redis
~~~~~

Install Redis:

.. code-block:: bash

   sudo apt install redis    # Linux (Debian/Ubuntu)
   brew install redis        # macOS
   sudo dnf install redis    # Fedora

Then set the broker and URL in ``settings.py``:

.. code-block:: python

   TASKS: dict[str, Any] = dataclasses.field(
       default_factory=lambda: {
           "enabled": 1,
           "broker": "redis",
           "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
           "backend_url": "",
           "logging": {
               "level": "INFO",
               "file": {
                   "log_dir": "logs",
                   "file_name": "tasks.log",
                   "log_format": "json",
                   "max_size": 10,
               },
               "database": {
                   "task": 1,
                   "periodic": 1,
               },
           },
        }
    )

RabbitMQ
~~~~~~~~

Install RabbitMQ:

.. code-block:: bash

   sudo apt install rabbitmq-server    # Linux (Debian/Ubuntu)
   brew install rabbitmq              # macOS
   sudo dnf install rabbitmq-server   # Fedora

Then set the broker and URL in ``settings.py``:

.. code-block:: python

   TASKS: dict[str, Any] = dataclasses.field(
       default_factory=lambda: {
           "enabled": 1,
           "broker": "rabbitmq",
           "broker_url": os.environ.get("AMQP_URL", "amqp://guest:guest@localhost:5672"),
           "backend_url": "",
           "logging": {
               "level": "INFO",
               "file": {
                   "log_dir": "logs",
                   "file_name": "tasks.log",
                   "log_format": "json",
                   "max_size": 10,
               },
               "database": {
                   "task": 1,
                   "periodic": 1,
               },
           },
        }
    )

.. note::

   The ``backend_url`` key enables result retrieval (e.g., fetching an
   actor's return value).  This currently requires a Redis URL regardless
   of which broker is selected.

Amazon SQS
~~~~~~~~~~

Install the SQS extra:

.. code-block:: bash

   pip install 'openviper[tasks-sqs]'

Configure in ``settings.py``:

.. code-block:: python

   TASKS: dict[str, Any] = dataclasses.field(
       default_factory=lambda: {
           "enabled": 1,
           "broker": "sqs",
           "broker_url": "",
           "sqs_namespace": "myapp",
           "sqs_endpoint_url": os.environ.get("SQS_ENDPOINT_URL", ""),
           "backend_url": "",
           "logging": {
               "level": "INFO",
               "file": {
                   "log_dir": "logs",
                   "file_name": "tasks.log",
                   "log_format": "json",
                   "max_size": 10,
               },
               "database": {
                   "task": 1,
                   "periodic": 1,
               },
           },
        }
    )

.. note::

   SQS uses AWS credentials configured via the standard ``boto3``
   credential chain (environment variables, IAM roles, etc.).  Set
   ``sqs_endpoint_url`` to use with ElasticMQ for local development.

PostgreSQL
~~~~~~~~~~

Install the PostgreSQL extra:

.. code-block:: bash

   pip install 'openviper[tasks-postgresql]'

Configure in ``settings.py``:

.. code-block:: python

   TASKS: dict[str, Any] = dataclasses.field(
       default_factory=lambda: {
           "enabled": 1,
           "broker": "postgresql",
           "broker_url": "postgresql://user:pass@localhost:5432/mydb",
           "pg_min_connections": 2,
           "pg_max_connections": 10,
           "backend_url": "",
           "logging": {
               "level": "INFO",
               "file": {
                   "log_dir": "logs",
                   "file_name": "tasks.log",
                   "log_format": "json",
                   "max_size": 10,
               },
               "database": {
                   "task": 1,
                   "periodic": 1,
               },
           },
        }
    )

Stub (Testing)
~~~~~~~~~~~~~~

The stub broker processes messages in-process without any external
dependency, making it ideal for unit and integration tests.  No extra
package is required - it ships with Dramatiq itself.

Configure in ``settings.py`` or your test configuration:

.. code-block:: python

   TASKS: dict[str, Any] = dataclasses.field(
       default_factory=lambda: {
           "enabled": 1,
           "broker": "stub",
           "backend_url": "",
           "logging": {
               "level": "INFO",
               "file": {
                   "log_dir": "logs",
                   "file_name": "tasks.log",
                   "log_format": "json",
                   "max_size": 10,
               },
               "database": {
                   "task": 1,
                   "periodic": 1,
               },
           },
        }
    )

.. note::

   The stub broker does not require a ``broker_url``.  It should only
   be used in testing environments, not in production.

Cache
~~~~~

Configure caching in ``settings.py`` using the ``CACHES`` dictionary:

.. code-block:: python

   CACHES = {
       "default": {
           "BACKEND": "openviper.cache.RedisCache",
           "OPTIONS": {"host": "localhost", "port": 6379, "db": 0},
       },
   }

For local development, the default ``InMemoryCache`` requires no
configuration:

.. code-block:: python

   CACHES = {
       "default": {
           "BACKEND": "openviper.cache.InMemoryCache",
           "OPTIONS": {"ttl": 300},
       },
   }

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
