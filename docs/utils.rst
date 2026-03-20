.. _utils:

Utilities
=========

The ``openviper.utils`` package provides lightweight helper modules used
throughout the framework: timezone-aware datetime helpers, high-performance
data structures for HTTP primitives, and a cached import utility.

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

``openviper.utils.datastructures``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

HTTP-oriented data structures backed by ``multidict`` C extensions for O(1)
lookups.

.. py:class:: Headers(raw)

   Immutable, case-insensitive HTTP header map.

   - ``raw`` — list of ``[name_bytes, value_bytes]`` pairs (ASGI format).
   - ``.get(key, default=None)`` — case-insensitive lookup.
   - ``.getlist(key)`` — return all values for a header.

.. py:class:: MutableHeaders(raw=None)

   Mutable header map; used internally when constructing responses.

.. py:class:: QueryParams(query_string)

   Immutable parsed query string.  Supports ``getlist(key)`` for repeated
   parameters.

.. py:class:: ImmutableMultiDict(data)

   Immutable multi-value dict for form data and file fields.

``openviper.utils.importlib``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: import_string(dotted_path) -> Any

   Import and return an object by its dotted Python path.  Results are
   cached to avoid repeated imports.

   Raises ``ImportError`` if the module cannot be found.
   Raises ``AttributeError`` if the attribute does not exist on the module.

.. py:function:: reset_import_cache() -> None

   Clear the import cache.  Primarily for tests.

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
