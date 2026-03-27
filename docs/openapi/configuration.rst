.. _openapi-configuration:

OpenAPI Configuration
=====================

This page documents all settings that control OpenAPI schema generation and
documentation endpoint access in OpenViper.

.. contents:: On this page
   :local:
   :depth: 2

----

OPENAPI_EXCLUDE
---------------

**Type:** ``str | list[str]``
**Default:** ``[]``

Controls OpenAPI access and route exclusion.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Value
     - Behaviour
   * - ``[]`` (default)
     - No routes excluded; docs endpoints active.
   * - ``"__ALL__"``
     - Docs router **not** registered; all docs URLs return 404.
   * - ``list[str]``
     - Routes whose path starts with any listed prefix are removed from the
       generated schema. Docs endpoints remain accessible.

----

Disable OpenAPI
---------------

Set ``OPENAPI_EXCLUDE = "__ALL__"`` to prevent the docs and schema endpoints
from being registered at startup:

.. code-block:: python

    # settings.py

    OPENAPI_EXCLUDE = "__ALL__"

After applying this setting:

* ``GET /open-api/openapi.json`` → **404**
* ``GET /open-api/docs`` → **404**
* ``GET /open-api/redoc`` → **404**

This is the recommended setting for production deployments.

----

Exclude Routes
--------------

Pass a list of route prefixes (without the leading ``/``) to hide specific
paths from the schema while keeping the docs pages accessible:

.. code-block:: python

    # Remove /admin/* routes from the schema
    OPENAPI_EXCLUDE = ["admin"]

.. code-block:: python

    # Remove /admin/* and /blogs/* routes
    OPENAPI_EXCLUDE = ["admin", "blogs"]

.. code-block:: python

    # Remove /admin/*, /blogs/*, and /internal/* routes
    OPENAPI_EXCLUDE = ["admin", "blogs", "internal"]

----

Prefix Matching
---------------

The prefix matching applied by ``OPENAPI_EXCLUDE`` follows these rules:

Case-insensitive
    ``"Admin"`` and ``"admin"`` produce identical results.

Leading-slash normalised
    ``"/admin"`` and ``"admin"`` are both valid and equivalent.

Whole-segment matching
    A prefix of ``"blogs"`` excludes ``/blogs`` and ``/blogs/posts`` but
    **does not** exclude ``/blogsearch`` or ``/blog``.

----

Examples
--------

Disable OpenAPI entirely in production
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # myproject/settings.py

    OPENAPI_EXCLUDE = "__ALL__"

Remove admin routes from public schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    OPENAPI_EXCLUDE = ["admin"]

Remove multiple prefixes
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    OPENAPI_EXCLUDE = ["admin", "blogs"]

Remove multiple prefixes including internal and health-check routes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    OPENAPI_EXCLUDE = ["admin", "blogs", "internal", "health"]

----

Other OpenAPI Settings
----------------------

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Setting
     - Default
     - Description
   * - ``OPENAPI_ENABLED``
     - ``True``
     - Master switch. ``False`` prevents all docs routes from registering,
       identical in effect to ``OPENAPI_EXCLUDE = "__ALL__"``.
   * - ``OPENAPI_TITLE``
     - ``"OpenViper API"``
     - Title shown in Swagger UI and ReDoc.
   * - ``OPENAPI_VERSION``
     - ``"0.0.1"``
     - API version string in the schema ``info`` block.
   * - ``OPENAPI_SCHEMA_URL``
     - ``"/open-api/openapi.json"``
     - URL at which the raw JSON schema is served.
   * - ``OPENAPI_DOCS_URL``
     - ``"/open-api/docs"``
     - URL for the Swagger UI page.
   * - ``OPENAPI_REDOC_URL``
     - ``"/open-api/redoc"``
     - URL for the ReDoc page.

----

Security Considerations
-----------------------

* Disable the schema entirely (``OPENAPI_EXCLUDE = "__ALL__"``) in production
  to prevent automated scanners from discovering your API surface.
* Use prefix exclusion to hide ``/admin`` and other sensitive sub-trees from
  publicly served documentation.
* Schema exposure is listed as a risk in OWASP API Security Top 10 (API7:
  Security Misconfiguration). ``OPENAPI_EXCLUDE`` directly mitigates this.

.. seealso::

   :ref:`openapi` — main OpenAPI reference including :func:`filter_openapi_routes`
   and :func:`should_register_openapi` API docs.
