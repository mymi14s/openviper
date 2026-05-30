.. _utils:

Utilities
=========

The ``openviper.utils`` package provides lightweight helper modules used
throughout the framework: timezone-aware datetime helpers, high-performance
data structures for HTTP primitives, a cached import utility, i18n
translation, logging configuration, and CLI module resolution.

Overview
--------

These utilities are building blocks for the rest of the framework.  Application
code can import them freely; they have no side effects on import.

Key Modules
-----------

``openviper.utils.timezone``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Timezone-aware datetime helpers that respect ``settings.USE_TZ`` and
``settings.TIME_ZONE``.

.. py:function:: now() -> datetime.datetime

   Return the current datetime.  If ``USE_TZ=True`` returns a UTC-aware
   datetime; otherwise returns a naive local datetime.

.. py:function:: get_current_timezone() -> zoneinfo.ZoneInfo

   Return a ``ZoneInfo`` instance for ``settings.TIME_ZONE``.

.. py:function:: get_settings() -> object

   Return the active settings proxy.  Used internally for
   backwards-compatible patching in tests.

.. py:function:: make_aware(value, timezone=None) -> datetime.datetime

   Attach *timezone* (defaults to ``get_current_timezone()``) to a naive
   *value*.  Raises ``ValueError`` if *value* is already aware.

.. py:function:: make_naive(value, timezone=None) -> datetime.datetime

   Remove timezone info from an aware *value* after converting to *timezone*.
   Raises ``ValueError`` if *value* is already naive.

.. py:function:: is_aware(value) -> bool

   Return ``True`` if *value* has a non-None UTC offset.

.. py:function:: is_naive(value) -> bool

   Return ``True`` if *value* has no UTC offset.

.. py:function:: localtime(value=None, timezone=None) -> datetime.datetime

   Convert an aware datetime to the configured timezone.  If *value* is
   ``None``, returns the current time in the configured timezone.  If
   *value* is naive, it is assumed to be in the configured timezone.

.. py:data:: utc

   The UTC ``datetime.timezone`` singleton (``datetime.UTC``).

``openviper.utils.datastructures``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

HTTP-oriented data structures backed by ``multidict`` C extensions for O(1)
lookups.

.. py:function:: check_no_crlf(value, label="Header value") -> None

   Raise ``ValueError`` if *value* contains CR or LF characters.
   Guards against HTTP response splitting.

.. py:function:: unique_keys(iterable) -> Iterator[str]

   Yield each key from *iterable* only once, preserving first-occurrence
   order.

.. py:function:: unique_items(iterable) -> Iterator[tuple[str, str]]

   Yield each ``(key, value)`` pair from *iterable* only once per key,
   preserving first-occurrence order.

.. py:class:: Headers(raw)

   Immutable, case-insensitive HTTP header map.

   - ``raw`` - list of ``[name_bytes, value_bytes]`` pairs (ASGI format).
   - ``.get(key, default=None)`` - case-insensitive lookup.
   - ``.getlist(key)`` - return all values for a header.
   - ``.raw`` - original bytes list as ``list[tuple[bytes, bytes]]``.

.. py:class:: MutableHeaders(raw=None)

   Mutable header map; used internally when constructing responses.

   - ``.set(key, value)`` - replace all values for *key*.
   - ``.append(key, value)`` - add a new header (allows duplicates).
   - ``.delete(key)`` - remove all entries for *key*.

.. py:class:: QueryParams(query_string)

   Immutable parsed query string.  Supports ``getlist(key)`` for repeated
   parameters.

.. py:class:: ImmutableMultiDict(data)

   Immutable multi-value dict for form data and file fields.

``openviper.utils.importlib``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: import_string(dotted_path) -> Callable[..., object]

   Import and return an object by its dotted Python path.  Results are
   cached to avoid repeated imports.  Failed imports are not cached so
   that transient ``sys.path`` issues do not permanently poison the cache.

   Raises ``ImportError`` if the module cannot be found or *dotted_path*
   has no dot separator.

.. py:function:: import_string_uncached(dotted_path) -> Callable[..., object]

   Import and return an object by its dotted Python path without caching.

.. py:function:: reset_import_cache() -> None

   Clear the import cache.  Primarily for tests.

.. py:data:: IMPORT_CACHE

   The ``dict[str, Callable[..., object]]`` used by ``import_string`` for
   caching.  Accessible for test introspection.

``openviper.utils.translation``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Context-variable-based internationalization using Python's ``gettext``
module.  Language is scoped per async task via ``contextvars``.

.. py:function:: get_language() -> str

   Return the current active language code from the context variable.

.. py:function:: set_language(language) -> None

   Set the active language for the current async context.

.. py:function:: gettext(message) -> str

   Translate *message* immediately using the active language.

.. py:function:: ngettext(singular, plural, n) -> str

   Translate a message with plural forms using the active language.

.. py:function:: gettext_lazy(message) -> LazyString

   Return a ``LazyString`` that defers translation until it is evaluated
   (e.g. at template render time).

.. py:function:: get_translation_object(language) -> gettext.NullTranslations

   Retrieve or load a translation object for *language*.  Falls back to
   ``NullTranslations`` on ``OSError`` or ``ValueError``.

.. py:data:: translations_cache

   The ``dict[str, gettext.NullTranslations]`` mapping language codes to
   loaded translation objects.

.. py:data:: LOCALE_DIR

   Absolute path to the ``locale/`` directory.

.. py:data:: DEFAULT_DOMAIN

   gettext domain name (default: ``"messages"``).

.. py:class:: LazyString(message)

   A string-like object that defers its translation until it is actually
   used.  Supports ``str()``, ``len()``, ``bool()``, ``==``, ``+``, and
   ``%`` formatting.

``openviper.utils.logging``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Uvicorn logging configuration with timestamps.

.. py:function:: get_uvicorn_log_config() -> dict[str, object]

   Return a uvicorn logging configuration dict that includes timestamps
   in both default and access formatters.  Automatically patches
   ``uvicorn.config.LOGGING_CONFIG`` when uvicorn is installed.

``openviper.utils.module_resolver``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Resolves ``viperctl`` target arguments to concrete module locations for
flexible project layouts.

.. py:class:: ResolvedModule

   Frozen dataclass result of resolving a target argument.

   - ``app_label: str`` - importable app label.
   - ``app_path: Path`` - absolute filesystem path to the app directory.
   - ``is_root: bool`` - ``True`` when the target was ``"."``.
   - ``models_module: str`` - dotted import path for the models file.

.. py:function:: resolve_target(target, cwd=None) -> ResolvedModule

   Resolve a ``viperctl`` target string to a concrete module location.
   *target* is ``"."`` for CWD-as-app, or a module name like ``"todo"``.

   Raises ``click.ClickException`` if the target cannot be resolved.

.. py:function:: resolve_root(cwd) -> ResolvedModule

   Treat the CWD itself as the application module.

.. py:function:: resolve_module(target, cwd) -> ResolvedModule

   Resolve a named module directory inside *cwd*.

``openviper.utils.settings_discovery``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Auto-discovers ``settings.py`` for flexible project layouts so that
``viperctl`` can set ``OPENVIPER_SETTINGS_MODULE`` without a
pre-generated project scaffold.

.. py:function:: discover_settings_module(target, cwd=None, explicit=None) -> str | None

   Resolve a dotted settings module path.  Resolution priority:

   1. *explicit* - value from the ``--settings`` flag (returned as-is).
   2. Module settings - ``<target>/settings`` exists inside *cwd*.
   3. Root settings - ``settings`` directly in *cwd*.

   Returns a dotted Python module path, or ``None`` if no settings file
   was found.

Example Usage
-------------

Timezone Helpers
~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.utils import timezone

    # Current time (UTC-aware when USE_TZ=True)
    ts = timezone.now()

    # Convert a naive timestamp to the configured timezone
    import datetime
    naive = datetime.datetime(2024, 6, 1, 12, 0, 0)
    aware = timezone.make_aware(naive)

    # Check awareness
    print(timezone.is_aware(aware))   # True

Headers Usage
~~~~~~~~~~~~~

.. code-block:: python

    from openviper.utils.datastructures import Headers

    raw = [(b"content-type", b"application/json"), (b"x-request-id", b"abc123")]
    headers = Headers(raw)
    print(headers.get("content-type"))   # "application/json"
    print(headers.get("X-Request-ID"))   # "abc123"  (case-insensitive)

Dynamic Import
~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.utils.importlib import import_string

    StorageClass = import_string("myproject.storage.S3Storage")
    storage = StorageClass(bucket="my-bucket")

Translation
~~~~~~~~~~~

.. code-block:: python

    from openviper.utils.translation import gettext, set_language

    set_language("fr")
    msg = gettext("Welcome")

Module Resolution
~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.utils.module_resolver import resolve_target

    resolved = resolve_target("todo")
    print(resolved.app_label)       # "todo"
    print(resolved.models_module)    # "todo.models"
