.. _settings:

==========================
Settings and Configuration
==========================

All OpenViper configuration lives in a **frozen dataclass** —
:class:`~openviper.conf.settings.Settings`.  Immutability prevents accidental
mutation at runtime.  Create a subclass in your project, populate it from
environment variables, and pass it to :func:`~openviper.conf.configure`.

.. contents:: On this page
   :local:
   :depth: 2

----

Creating Your Settings
-----------------------

.. code-block:: python

   # myproject/settings.py
   import os
   from datetime import timedelta
   from openviper.conf.settings import Settings


   class MySettings(Settings):
       # Override only what you need to change
       PROJECT_NAME = "My Blog"
       SECRET_KEY   = os.environ.get("SECRET_KEY", "change-me")
       DEBUG        = os.environ.get("DEBUG", "true").lower() == "true"

       DATABASE_URL = os.environ.get(
           "DATABASE_URL", "sqlite+aiosqlite:///./blog.sqlite3"
       )

       INSTALLED_APPS = (
           "openviper.auth",
           "blog",
       )

       ALLOWED_HOSTS = ("localhost", "127.0.0.1")


Then activate the settings before the ASGI app is built:

.. code-block:: python

   # myproject/asgi.py
   from openviper.conf import configure
   from myproject.settings import MySettings

   configure(MySettings())

   from openviper import OpenViper
   app = OpenViper(...)

----

Complete Reference
-------------------

Project
~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``PROJECT_NAME``
     - ``"OpenViper Application"``
   * - ``VERSION``
     - ``"0.0.1"``
   * - ``DEBUG``
     - ``True`` — **always set to** ``False`` in production
   * - ``ALLOWED_HOSTS``
     - ``("localhost", "127.0.0.1")``
   * - ``ROOT_URLCONF``
     - ``""`` — dotted path to the root router module
   * - ``INSTALLED_APPS``
     - ``()`` — tuple of app module paths
   * - ``USE_TZ``
     - ``True``
   * - ``TIME_ZONE``
     - ``"UTC"``
   * - ``MIDDLEWARE``
     - Built-in middleware stack (see :ref:`architecture`)
   * - ``SECRET_KEY``
     - ``"INSECURE-CHANGE-ME"`` — **must be overridden in production**

Admin
~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``ADMIN_TITLE``
     - ``"OpenViper Admin"``
   * - ``ADMIN_HEADER_TITLE``
     - ``"OpenViper"``
   * - ``ADMIN_FOOTER_TITLE``
     - ``"OpenViper Admin"``

Database
~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``DATABASE_URL``
     - ``""`` — SQLAlchemy connection string (required)
   * - ``DATABASE_ECHO``
     - ``False`` — log all SQL to stdout
   * - ``DATABASE_POOL_SIZE``
     - ``5``
   * - ``DATABASE_MAX_OVERFLOW``
     - ``10``
   * - ``DATABASE_POOL_RECYCLE``
     - ``3600`` (seconds)

Cache
~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``CACHE_BACKEND``
     - ``"memory"`` — in-process cache; use ``"redis"`` for distributed
   * - ``CACHE_URL``
     - ``""`` — Redis URL when ``CACHE_BACKEND = "redis"``
   * - ``CACHE_TTL``
     - ``300`` (seconds)

Authentication
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``USER_MODEL``
     - ``"openviper.auth.models.User"`` — dotted path to the user model
   * - ``PASSWORD_HASHERS``
     - ``("argon2", "bcrypt")``
   * - ``SESSION_COOKIE_NAME``
     - ``"sessionid"``
   * - ``SESSION_TIMEOUT``
     - ``timedelta(hours=1)``
   * - ``SESSION_COOKIE_SECURE``
     - ``False`` — set ``True`` in production (HTTPS)
   * - ``SESSION_COOKIE_HTTPONLY``
     - ``True``
   * - ``SESSION_COOKIE_SAMESITE``
     - ``"Lax"``

JWT
~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``JWT_ALGORITHM``
     - ``"HS256"``
   * - ``JWT_ACCESS_TOKEN_EXPIRE``
     - ``timedelta(hours=24)``
   * - ``JWT_REFRESH_TOKEN_EXPIRE``
     - ``timedelta(days=7)``

CSRF
~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``CSRF_COOKIE_NAME``
     - ``"csrftoken"``
   * - ``CSRF_COOKIE_SECURE``
     - ``False``
   * - ``CSRF_COOKIE_HTTPONLY``
     - ``True``
   * - ``CSRF_COOKIE_SAMESITE``
     - ``"Lax"``
   * - ``CSRF_TRUSTED_ORIGINS``
     - ``()`` — tuple of trusted origin URLs

CORS
~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``CORS_ALLOWED_ORIGINS``
     - ``()`` — list of allowed origins; use ``("*",)`` to allow all
   * - ``CORS_ALLOW_CREDENTIALS``
     - ``True``
   * - ``CORS_ALLOWED_METHODS``
     - ``("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")``
   * - ``CORS_ALLOWED_HEADERS``
     - ``("*",)``
   * - ``CORS_MAX_AGE``
     - ``600`` (seconds)

Static Files
~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``STATIC_URL``
     - ``"/static/"``
   * - ``STATIC_ROOT``
     - ``"./static/"``
   * - ``STATICFILES_DIRS``
     - ``("static/",)``
   * - ``MEDIA_URL``
     - ``"/media/"``
   * - ``MEDIA_ROOT``
     - ``"./media/"``
   * - ``MAX_FILE_SIZE``
     - ``10485760`` (10 MB)

Templates
~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``TEMPLATES_DIR``
     - ``"templates/"``
   * - ``TEMPLATE_AUTO_RELOAD``
     - ``True``

Logging
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``LOG_LEVEL``
     - ``"INFO"``
   * - ``LOG_FORMAT``
     - ``"text"`` — alternatively ``"json"`` for structured logging

Rate Limiting
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``RATE_LIMIT_BACKEND``
     - ``"memory"``
   * - ``RATE_LIMIT_REQUESTS``
     - ``1_000_000`` per window
   * - ``RATE_LIMIT_WINDOW``
     - ``60`` (seconds)
   * - ``RATE_LIMIT_BY``
     - ``"ip"`` — alternatively ``"user"``

Background Tasks
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``TASKS``
     - ``{}`` — dict with ``broker_url``, ``result_url``, ``result_ttl``
   * - ``MODEL_EVENTS``
     - ``{}`` — model event → handler mapping (see :ref:`tasks`)

AI Providers
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``ENABLE_AI_PROVIDERS``
     - ``False``
   * - ``AI_PROVIDERS``
     - ``{}`` — provider config dict (see :ref:`ai_registry`)

OpenAPI
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Default / Description
   * - ``OPENAPI_TITLE``
     - ``"OpenViper API"``
   * - ``OPENAPI_VERSION``
     - ``"0.0.1"``
   * - ``OPENAPI_ENABLED``
     - ``True``
   * - ``OPENAPI_DOCS_URL``
     - ``"/open-api/docs"``
   * - ``OPENAPI_REDOC_URL``
     - ``"/open-api/redoc"``
   * - ``OPENAPI_SCHEMA_URL``
     - ``"/open-api/openapi.json"``

----

Using Environment Variables
-----------------------------

The recommended pattern is to read environment variables inside your
settings class:

.. code-block:: python

   import os
   from openviper.conf.settings import Settings


   class ProductionSettings(Settings):
       DEBUG        = False
       SECRET_KEY   = os.environ["SECRET_KEY"]
       DATABASE_URL = os.environ["DATABASE_URL"]
       CACHE_URL    = os.environ.get("REDIS_URL", "")
       ALLOWED_HOSTS = tuple(
           os.environ.get("ALLOWED_HOSTS", "example.com").split(",")
       )
       SESSION_COOKIE_SECURE = True
       CSRF_COOKIE_SECURE    = True

Use a ``.env`` file in development (loaded by a library such as
``python-dotenv``):

.. code-block:: bash

   SECRET_KEY=dev-secret-key
   DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3

----

Accessing Settings at Runtime
-------------------------------

.. code-block:: python

   from openviper.conf import settings

   print(settings.DEBUG)
   print(settings.DATABASE_URL)
   print(settings["SECRET_KEY"])     # dict-style access also works
