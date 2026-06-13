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
        - ``True`` - set ``False`` in production
      * - ``ALLOWED_HOSTS``
        - ``tuple[str, ...]``
        - ``("localhost", "127.0.0.1")``
      * - ``INSTALLED_APPS``
        - ``tuple[str, ...]``
        - ``()`` - dotted paths to app modules
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
        - ``""`` - **must** be set via env var in production
      * - ``SECURE_SSL_REDIRECT``
        - ``bool``
        - ``False``
      * - ``SECURE_HSTS_SECONDS``
        - ``int``
        - ``0`` - seconds for HSTS header
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
        - ``False`` - deprecated; use CSP instead
      * - ``SECURE_CONTENT_SECURITY_POLICY``
        - ``ConfigMap | None``
        - ``None`` - CSP header directives dict

   **Database**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``DATABASE_URL``
        - ``str``
        - ``""`` - SQLAlchemy async URL e.g. ``"sqlite+aiosqlite:///db.sqlite3"``
      * - ``DATABASE_ECHO``
        - ``bool``
        - ``False`` - log all SQL statements
      * - ``DATABASE_POOL_SIZE``
        - ``int``
        - ``20``
      * - ``DATABASE_MAX_OVERFLOW``
        - ``int``
        - ``80``
      * - ``DATABASE_POOL_RECYCLE``
        - ``int``
        - ``900`` - seconds before a connection is recycled
      * - ``DATABASE_POOL_TIMEOUT``
        - ``int``
        - ``10`` - seconds to wait for a pool connection
      * - ``DATABASES``
        - ``ConfigMap``
        - Multi-database config; each alias maps to a dict with ``OPTIONS`` (``BACKEND`` is optional, defaults to ``DefaultDatabaseBackend``). Top-level ``ROUTERS`` and ``ROUTING`` keys control routing.

   **Cache**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``CACHES``
        - ``ConfigMap``
        - Alias-keyed cache backend config with ``BACKEND`` and ``OPTIONS`` (see :ref:`cache`)

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
        - ``False`` - set ``True`` in production (requires HTTPS)
      * - ``SESSION_COOKIE_HTTPONLY``
        - ``bool``
        - ``True`` - always ``True`` for XSS protection
      * - ``SESSION_COOKIE_SAMESITE``
        - ``str``
        - ``"Lax"`` - ``"Lax"``, ``"Strict"``, or ``"None"``
      * - ``SESSION_COOKIE_PATH``
        - ``str``
        - ``"/"``
      * - ``SESSION_COOKIE_DOMAIN``
        - ``str | None``
        - ``None`` - browser-determined domain
      * - ``USER_MODEL``
        - ``str``
        - ``"openviper.auth.models.User"``
      * - ``AUTH_SESSION_ENABLED``
        - ``bool``
        - ``True``
      * - ``SESSION_STORE``
        - ``str``
        - ``"database"`` - ``"database"`` or a dotted custom path
      * - ``AUTH_BACKENDS``
        - ``tuple[str, ...]``
        - JWT + Session backends
      * - ``DEFAULT_AUTHENTICATION_CLASSES``
        - ``tuple[str, ...]``
        - ``JWTAuthentication``, ``SessionAuthentication``
      * - ``DEFAULT_PERMISSION_CLASSES``
        - ``tuple[str, ...]``
        - ``()`` - views are public unless permissions are configured

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
        - ``False`` - must be ``False`` for double-submit cookie pattern
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
        - ``600`` - preflight cache in seconds

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
        - ``"local"`` - ``"local"`` or ``"s3"``
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
        - ``ConfigMap``
        - ``{}`` - set ``{"enable": 1, "path": "jinja_plugins"}`` to activate auto-discovery

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
        - ``"text"`` - ``"text"`` or ``"json"``
      * - ``LOGGING``
        - ``ConfigMap``
        - ``{}`` - full ``logging.config.dictConfig`` dict; overrides ``LOG_LEVEL``/``LOG_FORMAT``

   **Email**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``EMAIL``
        - ``ConfigMap``
        - Backend config dict; keys: ``backend``, ``host``, ``port``, ``use_tls``,
          ``use_ssl``, ``timeout``, ``username``, ``password``, ``from``,
          ``default_sender``, ``fail_silently``, ``background``

   **Rate Limiting**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``RATE_LIMIT_BACKEND``
        - ``str``
        - ``"memory"`` - ``"memory"`` or ``"redis"``
      * - ``RATE_LIMIT_REQUESTS``
        - ``int``
        - ``100``
      * - ``RATE_LIMIT_WINDOW``
        - ``int``
        - ``60`` - window in seconds
      * - ``RATE_LIMIT_BY``
        - ``str``
        - ``"ip"`` - ``"ip"``, ``"user"``, or ``"path"``

   **Background Tasks**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``TASKS``
        - ``ConfigMap``
        - ``{}`` - Dramatiq broker/worker configuration (see :doc:`tasks`)

   **Model Events**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``MODEL_EVENTS``
        - ``ConfigMap``
        - ``{}`` - per-model lifecycle hooks; keys are ``"module.ClassName"``
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
        - ``{}`` - lifecycle hooks for the OAuth2 flow; supported keys:
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
        - ``ConfigMap``
        - ``{}`` - provider-keyed configuration dicts

   **OpenAPI / Swagger**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``OPENAPI``
        - ``ConfigMap``
        - Dict consolidating all OpenAPI configuration. Keys: ``title``
          (``"OpenViper API"``), ``version`` (``"0.0.1"``), ``description``
          (``""``), ``docs_url`` (``"/open-api/docs"``), ``redoc_url``
          (``"/open-api/redoc"``), ``schema_url``
          (``"/open-api/openapi.json"``), ``enabled`` (``True``),
          ``admin_url`` (``None`` - admin routes stay hidden unless
          explicitly set, e.g. ``"/admin"``), ``exclude`` (``[]`` - route
          prefixes to omit, or ``"__ALL__"`` to disable entirely)

   **Country Field**

   .. list-table::
      :header-rows: 1
      :widths: 35 15 50

      * - Field
        - Type
        - Default / Notes
      * - ``COUNTRY_FIELD``
        - ``ConfigMap``
        - ``{"EXTRA_COUNTRIES": {}, "ENABLE_CACHE": True, "STRICT": True}``
          - configuration for :class:`~openviper.contrib.fields.countries.CountryField`

   .. py:method:: as_dict(mask_sensitive=True) -> ConfigMap

      Return settings as a plain dict.  Sensitive fields (e.g. ``SECRET_KEY``,
      ``DATABASE_URL``) are masked by default.

   .. py:method:: __getitem__(item: str) -> ConfigValue

      Bracket-access proxy: ``settings["DEBUG"]`` delegates to ``getattr``.

.. py:class:: openviper.conf.settings.LazySettings

   The ``settings`` singleton.  Attribute access triggers lazy loading of the
   settings module on first use.

   .. py:method:: configure(settings_obj: Settings) -> None

      Programmatically configure the settings.  Must be called before any
      attribute is first read.  Useful in tests and embedded applications.

   .. py:method:: _setup(*, force=False) -> None

      Load settings from ``OPENVIPER_SETTINGS_MODULE``.  *force* is
      keyword-only; when ``True``, re-run setup even if already configured.

   .. py:method:: __repr__() -> str

      Return a human-readable summary including the settings class name,
      ``PROJECT_NAME``, and ``DEBUG`` value.

.. py:function:: openviper.conf.settings.validate_settings(s, env) -> None

   Validate a :class:`Settings` instance for the given environment string
   (``"production"``, ``"development"``, etc.).  Raises
   :class:`~openviper.exceptions.SettingsValidationError` if required fields
   are missing or insecure values are found.

.. py:function:: openviper.conf.settings.generate_secret_key(length=64) -> str

   Generate a cryptographically random secret key suitable for ``SECRET_KEY``.

.. py:class:: openviper.conf.settings.JsonFormatter

   Minimal JSON log formatter with no third-party dependencies.
   Outputs log records as JSON objects with ``time``, ``level``,
   ``logger``, and ``message`` keys.

.. py:class:: openviper.conf.settings.OVDefaultHandler

   Sentinel ``StreamHandler`` subclass installed by
   :func:`configure_logging`.  Using a distinct subclass lets
   :func:`configure_logging` remove its own handler on a subsequent call
   without touching handlers added by the application or third-party
   libraries.

Package Exports
~~~~~~~~~~~~~~~

``openviper.conf`` re-exports the following from ``openviper.conf.settings``:

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Symbol
     - Description
   * - ``Settings``
     - Base frozen dataclass for all project settings
   * - ``settings``
     - Module-level ``LazySettings`` singleton
   * - ``validate_settings``
     - Validate a ``Settings`` instance for a given environment
   * - ``generate_secret_key``
     - Generate a cryptographically random secret key

Example Usage
-------------

.. seealso::

   Every example project has its own ``settings.py`` - compare patterns:

   - `examples/todoapp/settings.py <https://github.com/mymi14s/openviper/tree/master/examples/todoapp/settings.py>`_ - minimal single-app settings
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - multi-app with ``AI_PROVIDERS``, ``TASKS``, ``MODEL_EVENTS``
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - ``TASKS``, ``AI_PROVIDERS``, ``EMAIL`` config

Defining Settings
~~~~~~~~~~~~~~~~~

.. code-block:: python

    # myproject/settings.py
    import dataclasses
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        PROJECT_NAME: str = "MyBlog"
        DEBUG: bool = False
        SECRET_KEY: str = ""          # set via OPENVIPER_SECRET_KEY env var
        INSTALLED_APPS: tuple = (
            "myproject.blog",
            "myproject.users",
        )

    # Database configuration (nested format recommended):
    DATABASES = {
        "default": {
            "OPTIONS": {
                "URL": "sqlite+aiosqlite:///db.sqlite3",
            },
        },
    }

    # Or use the legacy flat format:
    # DATABASE_URL = "sqlite+aiosqlite:///db.sqlite3"

Then configure the environment:

.. code-block:: bash

    export OPENVIPER_SETTINGS_MODULE=myproject.settings
    export OPENVIPER_SECRET_KEY=your-secret-key-here

Accessing Settings
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.conf import settings

    print(settings.DEBUG)           # False
    print(settings.DATABASES)       # {"default": {"OPTIONS": {"URL": "..."}}}

Programmatic Configuration (Tests)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import dataclasses
    from openviper.conf import Settings
    from openviper.conf.settings import settings

    settings.configure(Settings(
        DATABASES={
            "default": {
                "OPTIONS": {"URL": "sqlite+aiosqlite:///:memory:"},
            },
        },
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

Internal API Reference
----------------------

The following symbols are public but intended for framework internals,
advanced customisation, or testing.

.. py:function:: openviper.conf.settings.cast_bool(v: str) -> bool

   Cast a string to ``bool``.  Truthy values: ``"1"``, ``"true"``, ``"yes"``, ``"on"``.

.. py:function:: openviper.conf.settings.cast_tuple(v: str) -> tuple[str, ...]

   Cast a comma-separated string to a ``tuple`` of stripped values.

.. py:function:: openviper.conf.settings.cast_timedelta(v: str) -> timedelta

   Cast a string (seconds) to a ``timedelta``.

.. py:function:: openviper.conf.settings.cast_env_value(current: EnvValue, raw: str) -> EnvValue | None

   Cast *raw* env-var string to the same type as *current*.  Returns ``None``
   for complex types (dicts, etc.) that cannot be cast from a string.

.. py:function:: openviper.conf.settings.auto_include_project_app(instance: Settings, module_path: str) -> Settings

   Prepend the top-level project package to ``INSTALLED_APPS`` if absent.

.. py:function:: openviper.conf.settings.apply_env_overrides(instance: Settings) -> Settings

   Return a new ``Settings`` with environment variable overrides applied.

.. py:function:: openviper.conf.settings.configure_logging(instance: Settings) -> None

   Apply logging configuration derived from a ``Settings`` instance.

.. py:function:: openviper.conf.settings.load_settings_from_module(module_path: str) -> Settings | None

   Import *module_path* and return a :class:`Settings` instance from it.
   Returns ``None`` when *module_path* is empty or when the special
   ``"settings"`` module cannot be found (graceful fallback).

.. py:function:: openviper.conf.settings.validate_production(s: Settings, errors: list[str]) -> None

   Append production-specific validation errors to *errors*.

.. py:function:: openviper.conf.settings.validate_production_security(s: Settings, errors: list[str]) -> None

   Append production security-header validation errors to *errors*.

.. py:function:: openviper.conf.settings.validate_production_cookies(s: Settings, errors: list[str]) -> None

   Append production cookie validation errors to *errors*.

.. py:function:: openviper.conf.settings.validate_production_api(s: Settings, errors: list[str]) -> None

   Append production API exposure validation errors to *errors*.

.. py:function:: openviper.conf.settings.is_insecure_secret_key(key: str) -> bool

   Return ``True`` if *key* is empty or matches a known insecure value.

.. py:data:: openviper.conf.settings.INSECURE_SECRET_KEYS

   ``frozenset`` of known insecure ``SECRET_KEY`` values.

.. py:data:: openviper.conf.settings.MIN_SECRET_KEY_LENGTH

   ``Final[int]`` - minimum ``SECRET_KEY`` length enforced by
   :func:`validate_production` (default: ``50``).

.. py:data:: openviper.conf.settings.MIN_HSTS_SECONDS

   ``Final[int]`` - minimum ``SECURE_HSTS_SECONDS`` enforced by
   :func:`validate_production_security` (default: ``31536000``, 1 year).

.. py:data:: openviper.conf.settings.SENSITIVE_FIELDS

   ``frozenset`` of field names that are masked by ``as_dict()``.

.. py:data:: openviper.conf.settings.INSECURE_JWT_ALGORITHMS

   ``frozenset`` of JWT algorithm names rejected by ``validate_settings()``.

.. py:data:: openviper.conf.settings.ENV_CASTERS

   ``dict`` mapping types to caster callables for environment variable parsing.

.. py:data:: openviper.conf.settings.MODULE_CACHE

   ``dict[str, types.ModuleType]`` caching imported settings modules.

.. py:data:: openviper.conf.settings.SETTINGS_CLASS_CACHE

   ``dict[str, type[Settings]]`` caching resolved settings classes.

.. py:data:: openviper.conf.settings.FIELD_METADATA_CACHE

   ``dict[type, list[tuple[str, type]]]`` caching field metadata per class.

.. py:data:: openviper.conf.settings.DOTENV_LOADED

   ``bool`` flag tracking whether ``.env`` has been loaded to avoid
   redundant I/O.

.. py:data:: openviper.conf.settings.DOTENV_LOADED

   ``bool`` tracking whether ``.env`` has been loaded.

.. py:data:: openviper.conf.settings.dotenv_path

   ``str`` path to the discovered ``.env`` file.

.. py:data:: openviper.conf.settings.framework_version

   ``str`` - the current OpenViper framework version string.

.. py:class:: openviper.conf.settings.JsonFormatter(logging.Formatter)

   Minimal JSON log formatter with no third-party dependencies.

.. py:class:: openviper.conf.settings.OVDefaultHandler(logging.StreamHandler[io.TextIOWrapper])

   Sentinel ``StreamHandler`` installed by ``configure_logging()``.
   Using a distinct subclass lets ``configure_logging`` remove its own
   handler on a subsequent call without touching user-added handlers.

Type Aliases
~~~~~~~~~~~~

.. py:data:: openviper.conf.types.ConfigValue

   Union of valid configuration field value types:
   ``str | int | float | bool | None | timedelta | tuple[str, ...] | list[str] | dict[str, ConfigValue]``

.. py:data:: openviper.conf.types.ConfigMap

   ``dict[str, ConfigValue]`` - configuration mapping type.

.. py:data:: openviper.conf.types.EnvValue

   Union of types that can be cast from environment variable strings:
   ``bool | int | float | str | tuple[str, ...] | timedelta``
