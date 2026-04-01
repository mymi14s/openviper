.. _conf:

Configuration
=============

The ``openviper.conf`` package provides OpenViper's typed settings system.
Settings are declared as frozen dataclasses, loaded from an environment variable,
and can be overridden by ``.env`` files or environment variables at runtime.

Overview
--------

Settings are defined by subclassing :class:`~openviper.conf.Settings` and decorating
the subclass with ``@dataclasses.dataclass(frozen=True)``.  The framework loads
settings from the module pointed to by the ``OPENVIPER_SETTINGS_MODULE`` environment
variable.

An alternative *programmatic* configuration path is available via
``settings.configure(obj)`` for tests and embedded use-cases.

Key Classes & Functions
-----------------------

.. py:class:: openviper.conf.Settings

   Base frozen dataclass for all project settings.  Subclass and decorate
   with ``@dataclasses.dataclass(frozen=True)`` to customise for your project.
   All fields are immutable after construction.

   **Project**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``PROJECT_NAME``
        - ``str``
        - ``"OpenViper Application"``
      * - ``VERSION``
        - ``str``
        - Framework version (auto-set)
      * - ``DEBUG``
        - ``bool``
        - ``True`` — set ``False`` in production
      * - ``ALLOWED_HOSTS``
        - ``tuple[str, ...]``
        - ``("localhost", "127.0.0.1")``
      * - ``INSTALLED_APPS``
        - ``tuple[str, ...]``
        - ``()`` — dotted paths to app modules
      * - ``USE_TZ``
        - ``bool``
        - ``True``
      * - ``TIME_ZONE``
        - ``str``
        - ``"UTC"``
      * - ``MIDDLEWARE``
        - ``tuple[str, ...]``
        - Security, CORS, Session, Auth middleware by default

   **Admin Panel**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``ADMIN_TITLE``
        - ``str``
        - ``"OpenViper Admin"``
      * - ``ADMIN_HEADER_TITLE``
        - ``str``
        - ``"OpenViper"``
      * - ``ADMIN_FOOTER_TITLE``
        - ``str``
        - ``"OpenViper Admin"``

   **Security**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``SECRET_KEY``
        - ``str``
        - ``""`` — **must** be set via env var in production
      * - ``SECURE_SSL_REDIRECT``
        - ``bool``
        - ``False``
      * - ``SECURE_HSTS_SECONDS``
        - ``int``
        - ``0`` — seconds for HSTS header
      * - ``SECURE_HSTS_INCLUDE_SUBDOMAINS``
        - ``bool``
        - ``False``
      * - ``SECURE_HSTS_PRELOAD``
        - ``bool``
        - ``False``
      * - ``SECURE_COOKIES``
        - ``bool``
        - ``False``
      * - ``X_FRAME_OPTIONS``
        - ``str``
        - ``"DENY"``
      * - ``SECURE_BROWSER_XSS_FILTER``
        - ``bool``
        - ``True``
      * - ``SECURE_CONTENT_SECURITY_POLICY``
        - ``dict[str, Any] | None``
        - ``None`` — CSP header directives dict

   **Database**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``DATABASE_URL``
        - ``str``
        - ``""`` — SQLAlchemy async URL e.g. ``"sqlite+aiosqlite:///db.sqlite3"``
      * - ``DATABASE_ECHO``
        - ``bool``
        - ``False`` — log all SQL statements
      * - ``DATABASE_POOL_SIZE``
        - ``int``
        - ``5``
      * - ``DATABASE_MAX_OVERFLOW``
        - ``int``
        - ``10``
      * - ``DATABASE_POOL_RECYCLE``
        - ``int``
        - ``3600`` — seconds before a connection is recycled
      * - ``DATABASE_POOL_TIMEOUT``
        - ``int``
        - ``10`` — seconds to wait for a connection from the pool
      * - ``DATABASE_PREPARED_STMT_CACHE``
        - ``int``
        - ``256`` — asyncpg prepared-statement cache size (0 to disable)

   **Cache**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``CACHE_BACKEND``
        - ``str``
        - ``"memory"`` — ``"memory"`` or ``"redis"``
      * - ``CACHE_URL``
        - ``str``
        - ``""`` — Redis URL when using the Redis backend
      * - ``CACHE_TTL``
        - ``int``
        - ``300`` — default TTL in seconds
      * - ``CACHES``
        - ``dict[str, Any]``
        - ``{}`` — alias-keyed cache backend config (see :ref:`cache`)

   **Authentication & Session**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``PASSWORD_HASHERS``
        - ``tuple[str, ...]``
        - ``("argon2", "bcrypt")``
      * - ``SESSION_COOKIE_NAME``
        - ``str``
        - ``"sessionid"``
      * - ``SESSION_TIMEOUT``
        - ``timedelta``
        - ``timedelta(hours=1)``
      * - ``SESSION_COOKIE_SECURE``
        - ``bool``
        - ``False`` — set ``True`` in production (requires HTTPS)
      * - ``SESSION_COOKIE_HTTPONLY``
        - ``bool``
        - ``True`` — always ``True`` for XSS protection
      * - ``SESSION_COOKIE_SAMESITE``
        - ``str``
        - ``"Lax"`` — ``"Lax"``, ``"Strict"``, or ``"None"``
      * - ``SESSION_COOKIE_PATH``
        - ``str``
        - ``"/"``
      * - ``SESSION_COOKIE_DOMAIN``
        - ``str | None``
        - ``None`` — browser-determined domain
      * - ``USER_MODEL``
        - ``str``
        - ``"openviper.auth.models.User"``
      * - ``AUTH_SESSION_ENABLED``
        - ``bool``
        - ``True``
      * - ``SESSION_STORE``
        - ``str``
        - ``"database"`` — ``"database"`` or a dotted custom path
      * - ``AUTH_BACKENDS``
        - ``tuple[str, ...]``
        - JWT + Session backends
      * - ``DEFAULT_AUTHENTICATION_CLASSES``
        - ``tuple[str, ...]``
        - ``JWTAuthentication``, ``SessionAuthentication``
      * - ``DEFAULT_PERMISSION_CLASSES``
        - ``tuple[str, ...]``
        - ``("openviper.http.permissions.IsAuthenticated",)``

   **JWT**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``JWT_ALGORITHM``
        - ``str``
        - ``"HS256"``
      * - ``JWT_ACCESS_TOKEN_EXPIRE``
        - ``timedelta``
        - ``timedelta(minutes=30)``
      * - ``JWT_REFRESH_TOKEN_EXPIRE``
        - ``timedelta``
        - ``timedelta(days=7)``

   **CSRF**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``CSRF_COOKIE_NAME``
        - ``str``
        - ``"csrftoken"``
      * - ``CSRF_COOKIE_SECURE``
        - ``bool``
        - ``False``
      * - ``CSRF_COOKIE_HTTPONLY``
        - ``bool``
        - ``False`` — must be ``False`` for double-submit cookie pattern
      * - ``CSRF_COOKIE_SAMESITE``
        - ``str``
        - ``"Lax"``
      * - ``CSRF_TRUSTED_ORIGINS``
        - ``tuple[str, ...]``
        - ``()``

   **CORS**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``CORS_ALLOWED_ORIGINS``
        - ``tuple[str, ...]``
        - ``()``
      * - ``CORS_ALLOW_CREDENTIALS``
        - ``bool``
        - ``False``
      * - ``CORS_ALLOWED_METHODS``
        - ``tuple[str, ...]``
        - ``("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")``
      * - ``CORS_ALLOWED_HEADERS``
        - ``tuple[str, ...]``
        - ``("*",)``
      * - ``CORS_EXPOSE_HEADERS``
        - ``tuple[str, ...]``
        - ``()``
      * - ``CORS_MAX_AGE``
        - ``int``
        - ``600`` — preflight cache in seconds

   **Static Files & Media**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``STATIC_URL``
        - ``str``
        - ``"/static/"``
      * - ``STATIC_ROOT``
        - ``str``
        - ``"./static/"``
      * - ``STATICFILES_DIRS``
        - ``tuple[str, ...]``
        - ``("static/",)``
      * - ``MEDIA_URL``
        - ``str``
        - ``"/media/"``
      * - ``MEDIA_ROOT``
        - ``str``
        - ``"./media/"``
      * - ``MEDIA_DIR``
        - ``str``
        - ``"./media/"``
      * - ``STATIC_STORAGE``
        - ``str``
        - ``"local"`` — ``"local"`` or ``"s3"``
      * - ``MEDIA_STORAGE``
        - ``str``
        - ``"local"``
      * - ``MAX_FILE_SIZE``
        - ``int``
        - ``10485760`` (10 MB)

   **Templates**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``TEMPLATES_DIR``
        - ``str``
        - ``"templates/"``
      * - ``TEMPLATE_AUTO_RELOAD``
        - ``bool``
        - ``True``
      * - ``JINJA_PLUGINS``
        - ``dict[str, Any]``
        - ``{}`` — set ``{"enable": 1, "path": "jinja_plugins"}`` to activate auto-discovery

   **Logging**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``LOG_LEVEL``
        - ``str``
        - ``"INFO"``
      * - ``LOG_FORMAT``
        - ``str``
        - ``"text"`` — ``"text"`` or ``"json"``

   **Email**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``EMAIL``
        - ``dict[str, Any]``
        - Backend config dict; keys: ``backend``, ``host``, ``port``, ``use_tls``,
          ``use_ssl``, ``timeout``, ``username``, ``password``, ``from``,
          ``default_sender``, ``fail_silently``, ``use_background_worker``

   **Rate Limiting**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``RATE_LIMIT_BACKEND``
        - ``str``
        - ``"memory"`` — ``"memory"`` or ``"redis"``
      * - ``RATE_LIMIT_REQUESTS``
        - ``int``
        - ``100``
      * - ``RATE_LIMIT_WINDOW``
        - ``int``
        - ``60`` — window in seconds
      * - ``RATE_LIMIT_BY``
        - ``str``
        - ``"ip"`` — ``"ip"``, ``"user"``, or ``"path"``

   **Background Tasks**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``TASKS``
        - ``dict[str, Any]``
        - ``{}`` — Dramatiq broker/worker configuration

   **Model Events**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``MODEL_EVENTS``
        - ``dict[str, Any]``
        - ``{}`` — per-model lifecycle hooks; keys are ``"module.ClassName"``
          paths, values map event names to lists of dotted callable paths.
          Supported events: ``before_validate``, ``validate``,
          ``before_insert``, ``before_save``, ``after_insert``, ``on_change``,
          ``on_update``, ``on_delete``, ``after_delete``.

   **OAuth2 Events**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``OAUTH2_EVENTS``
        - ``dict[str, str]``
        - ``{}`` — lifecycle hooks for the OAuth2 flow; supported keys:
          ``on_success``, ``on_fail``, ``on_error``, ``on_initial``

   **AI Integration**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``ENABLE_AI_PROVIDERS``
        - ``bool``
        - ``False``
      * - ``AI_PROVIDERS``
        - ``dict[str, Any]``
        - ``{}`` — provider-keyed configuration dicts

   **OpenAPI / Swagger**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``OPENAPI_TITLE``
        - ``str``
        - ``"OpenViper API"``
      * - ``OPENAPI_VERSION``
        - ``str``
        - ``"0.0.1"``
      * - ``OPENAPI_DOCS_URL``
        - ``str``
        - ``"/open-api/docs"``
      * - ``OPENAPI_REDOC_URL``
        - ``str``
        - ``"/open-api/redoc"``
      * - ``OPENAPI_SCHEMA_URL``
        - ``str``
        - ``"/open-api/openapi.json"``
      * - ``OPENAPI_ENABLED``
        - ``bool``
        - ``True``
      * - ``OPENAPI_EXCLUDE``
        - ``list[str] | str``
        - ``[]`` — route prefixes to omit from the schema, or ``"__ALL__"``
          to disable the OpenAPI router entirely

   **Country Field**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``COUNTRY_FIELD``
        - ``dict[str, Any]``
        - ``{"EXTRA_COUNTRIES": {}, "ENABLE_CACHE": True, "STRICT": True}``
          — configuration for :class:`~openviper.contrib.countries.CountryField`

   .. py:method:: as_dict(mask_sensitive=True) -> dict[str, Any]

      Return settings as a plain dict.  Sensitive fields (e.g. ``SECRET_KEY``,
      ``DATABASE_URL``) are masked by default.

.. py:class:: openviper.conf.settings._LazySettings

   The ``settings`` singleton.  Attribute access triggers lazy loading of the
   settings module on first use.

   .. py:method:: configure(settings_obj: Settings) -> None

      Programmatically configure the settings.  Must be called before any
      attribute is first read.  Useful in tests and embedded applications.

.. py:function:: openviper.conf.settings.validate_settings(s, env) -> None

   Validate a :class:`Settings` instance for the given environment string
   (``"production"``, ``"development"``, etc.).  Raises
   :class:`~openviper.exceptions.SettingsValidationError` if required fields
   are missing or insecure values are found.

.. py:function:: openviper.conf.settings.generate_secret_key(length=64) -> str

   Generate a cryptographically random secret key suitable for ``SECRET_KEY``.

Example Usage
-------------

.. seealso::

   Every example project has its own ``settings.py`` — compare patterns:

   - `examples/todoapp/settings.py <https://github.com/mymi14s/openviper/tree/master/examples/todoapp/settings.py>`_ — minimal single-app settings
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — multi-app with ``AI_PROVIDERS``, ``TASKS``, ``MODEL_EVENTS``
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — ``TASKS``, ``AI_PROVIDERS``, ``EMAIL`` config

Defining Settings
~~~~~~~~~~~~~~~~~

.. code-block:: python

    # myproject/settings.py
    import dataclasses
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        PROJECT_NAME: str = "MyBlog"
        DATABASE_URL: str = "sqlite+aiosqlite:///db.sqlite3"
        DEBUG: bool = False
        SECRET_KEY: str = ""          # set via OPENVIPER_SECRET_KEY env var
        INSTALLED_APPS: tuple = (
            "myproject.blog",
            "myproject.users",
        )

Then configure the environment:

.. code-block:: bash

    export OPENVIPER_SETTINGS_MODULE=myproject.settings
    export OPENVIPER_SECRET_KEY=your-secret-key-here

Accessing Settings
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.conf import settings

    print(settings.DEBUG)           # False
    print(settings.DATABASE_URL)    # sqlite+aiosqlite:///db.sqlite3

Programmatic Configuration (Tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import dataclasses
    from openviper.conf import Settings
    from openviper.conf.settings import settings

    settings.configure(Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        SECRET_KEY="test-only-secret",
        DEBUG=True,
    ))

Environment Variable Overrides
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Any settings field can be overridden at runtime by setting an environment
variable named ``OPENVIPER_<FIELD_NAME>`` (uppercase).  For example:

.. code-block:: bash

    export OPENVIPER_DEBUG=true
    export OPENVIPER_LOG_LEVEL=DEBUG
