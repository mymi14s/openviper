.. _array_fields:

Array Field
===========

The ``openviper.contrib.fields.array_fields`` package provides a
PostgreSQL-native **ArrayField** for OpenViper models.  It stores
homogeneous lists of a scalar type using PostgreSQL's ``ARRAY`` column
type and falls back to JSON serialisation on other databases.

Overview
--------

* **PostgreSQL-native** - ``INTEGER[]``, ``VARCHAR[]``, ``UUID[]``, etc.
* **Fallback JSON backend** - stores arrays as JSON text on non-PostgreSQL
  databases (SQLite, MySQL, MariaDB, MSSQL, Oracle).
* **Type-safe element coercion** - each element is converted through the
  base field's ``to_python()`` / ``to_db()`` methods.
* **Size constraint** - optional ``size`` parameter caps the maximum number
  of elements at validation time.
* **Auto-instantiation** - pass a Field class (``IntegerField``) or an
  instance (``IntegerField()``); classes are instantiated with defaults.

Installation
------------

``ArrayField`` is part of the core distribution.  No extra packages are
required.  Import it directly::

    from openviper.contrib.fields.array_fields import ArrayField

Basic Usage
-----------

Define a model with array fields:

.. code-block:: python

    from openviper.db import Model
    from openviper.db.fields import AutoField, CharField, IntegerField, UUIDField
    from openviper.contrib.fields.array_fields import ArrayField

    class Article(Model):
        id = AutoField(primary_key=True)
        title = CharField(max_length=200)
        tags = ArrayField(CharField(max_length=50))
        scores = ArrayField(IntegerField, null=True)
        source_entry_ids = ArrayField(UUIDField, null=True)

``base_field`` accepts either a Field **instance** (for custom options) or
a Field **class** (auto-instantiated with defaults):

.. code-block:: python

    # Instance - custom max_length propagates to each element
    tags = ArrayField(CharField(max_length=100))

    # Class - auto-instantiated as IntegerField()
    scores = ArrayField(IntegerField)

All standard Field keyword arguments (``null``, ``default``, ``db_index``,
``unique``, ``help_text``, etc.) are supported:

.. code-block:: python

    flags = ArrayField(BooleanField, default=list, null=True)
    rankings = ArrayField(IntegerField, size=10)
    notes = ArrayField(TextField, db_index=True)

Parameters
----------

``base_field``
    A :class:`~openviper.db.fields.Field` **instance** or **class** describing
    the element type.  Instances allow custom options (e.g.
    ``CharField(max_length=50)``); classes are auto-instantiated with
    defaults (e.g. ``IntegerField`` becomes ``IntegerField()``).

``size``
    Optional ``int``.  Maximum number of elements.  Enforced by
    :meth:`validate`.  ``None`` (default) means no limit.

All other keyword arguments (``null``, ``blank``, ``unique``, ``default``,
``db_column``, ``db_index``, ``help_text``) are forwarded to the base
:class:`~openviper.db.fields.Field` constructor.

Database Column Types
---------------------

PostgreSQL
~~~~~~~~~~

On PostgreSQL, ``ArrayField`` maps to the native ``ARRAY`` type.  The
element type is derived from the base field:

+-------------------------------------+----------------------------+
| ``base_field``                      | Column type                |
+=====================================+============================+
| ``IntegerField``                    | ``INTEGER[]``             |
+-------------------------------------+----------------------------+
| ``BigIntegerField``                 | ``BIGINT[]``              |
+-------------------------------------+----------------------------+
| ``SmallIntegerField``               | ``SMALLINT[]``            |
+-------------------------------------+----------------------------+
| ``FloatField``                      | ``REAL[]``                |
+-------------------------------------+----------------------------+
| ``CharField(max_length=N)``         | ``VARCHAR[]``             |
+-------------------------------------+----------------------------+
| ``TextField``                       | ``TEXT[]``                |
+-------------------------------------+----------------------------+
| ``BooleanField``                    | ``BOOLEAN[]``             |
+-------------------------------------+----------------------------+
| ``UUIDField``                       | ``UUID[]``                |
+-------------------------------------+----------------------------+
| ``DateField``                       | ``DATE[]``                |
+-------------------------------------+----------------------------+
| ``DateTimeField``                   | ``TIMESTAMP[]``           |
+-------------------------------------+----------------------------+

Other Databases
~~~~~~~~~~~~~~~

On non-PostgreSQL databases (SQLite, MySQL, MariaDB, MSSQL, Oracle),
arrays are stored as JSON-encoded ``TEXT`` columns.

Reading and Writing
-------------------

.. code-block:: python

    # Create
    article = await Article.objects.create(
        title="ArrayField guide",
        tags=["python", "orm", "database"],
        scores=[95, 87, 92],
    )

    # Read - values are automatically deserialised
    article = await Article.objects.get(id=1)
    article.tags     # ["python", "orm", "database"]
    article.scores   # [95, 87, 92]

    # Update
    article.tags = ["python", "orm"]
    article.scores = [100, 99]
    await article.save()

    # Filter - use __contains for array membership
    results = await Article.objects.filter(tags__contains="python")

Validation
----------

``ArrayField.validate()`` enforces:

1. **Type check** - value must be a ``list`` or ``tuple``.
2. **Null check** - ``None`` is rejected when ``null=False`` (the default).
3. **Size constraint** - if ``size`` is set, ``len(value)`` must not exceed it.
4. **Element validation** - each element is passed through the base field's
   ``validate()`` method.

.. code-block:: python

    field = ArrayField(IntegerField, size=5, null=False)
    field.name = "scores"

    field.validate([1, 2, 3])          # OK
    field.validate(None)                # raises ValueError
    field.validate("not a list")        # raises ValueError
    field.validate([1, 2, 3, 4, 5, 6]) # raises ValueError (exceeds size=5)

Backend Selection
-----------------

The backend is selected automatically based on the configured database:

- **PostgreSQL** connection URL detected: uses ``PostgresArrayBackend``
  with native ``ARRAY`` columns.
- **All other databases**: uses ``FallbackJsonBackend`` with JSON ``TEXT``
  columns.

The backend is cached after first selection.  Use ``reset_backend()`` in
tests to force re-evaluation:

.. code-block:: python

    from openviper.contrib.fields.array_fields.backends import reset_backend

    # In test teardown
    reset_backend()

API Reference
-------------

.. py:class:: ArrayField(base_field, size=None, **kwargs)

   PostgreSQL-native array field storing homogeneous lists.

   :param base_field: A Field instance (e.g. ``IntegerField()``) or class
     (e.g. ``IntegerField``).  Classes are auto-instantiated with defaults.
   :param size: Maximum number of elements.  ``None`` means no limit.
   :param kwargs: Standard Field keyword arguments (``null``, ``default``,
     ``db_index``, etc.).

   .. py:property:: db_column_type

      Returns the DDL column type string.  On PostgreSQL this is the base
      type with ``[]`` appended (e.g. ``INTEGER[]``).  On other databases
      this returns ``TEXT``.

   .. py:method:: to_python(value) -> list | None

      Convert a database value to a Python list.  Accepts lists, tuples,
      JSON strings, and ``None``.  Each element is coerced through the
      base field's ``to_python()``.

   .. py:method:: to_db(value) -> list | str | None

      Prepare a Python list for database storage.  On PostgreSQL the list
      is returned as-is.  On other databases the list is JSON-encoded.
      Each element is first coerced through the base field's ``to_db()``.

   .. py:method:: validate(value) -> None

      Validate the array value.  Checks type, null constraint, size
      constraint, and validates each element through the base field.

   .. py:method:: get_sa_type() -> sqlalchemy.types.TypeEngine

      Return the SQLAlchemy column type.  ``ARRAY`` on PostgreSQL,
      ``Text`` on other databases.

.. py:class:: PostgresArrayBackend

   PostgreSQL backend using native ``ARRAY`` columns.

.. py:class:: FallbackJsonBackend

   Fallback backend storing arrays as JSON text on non-PostgreSQL databases.

.. py:function:: get_backend() -> BaseArrayBackend

   Return the appropriate backend based on the configured database.
   The result is cached; call ``reset_backend()`` to force re-evaluation.

.. py:function:: reset_backend()

   Clear the cached backend.  Useful in test teardown.
