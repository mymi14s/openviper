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

   Base frozen dataclass for all project settings.

   Built-in fields include:

   - ``DEBUG: bool = False``
   - ``SECRET_KEY: str = ""``
   - ``DATABASE_URL: str = "sqlite+aiosqlite:///db.sqlite3"``
   - ``INSTALLED_APPS: tuple[str, ...] = ()``
   - ``ALLOWED_HOSTS: tuple[str, ...] = ("*",)``
   - ``MIDDLEWARE: tuple[str, ...] = ()``
   - ``TIME_ZONE: str = "UTC"``
   - ``USE_TZ: bool = True``
   - ``STATIC_URL: str = "/static/"``
   - ``STATIC_ROOT: str = "staticfiles"``
   - ``MEDIA_URL: str = "/media/"``
   - ``MEDIA_ROOT: str = "media"``
   - ``LOG_LEVEL: str = "INFO"``

   .. py:method:: as_dict(mask_sensitive=True) -> dict

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
