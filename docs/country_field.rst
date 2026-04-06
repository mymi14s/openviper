Country Field
=============

The ``openviper.contrib.countries`` package provides a lightweight,
zero-overhead **CountryField** for OpenViper models.  It stores
`ISO 3166-1 alpha-2 <https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2>`_
two-letter country codes in a ``CHAR(2)`` column.

All lookups operate on an in-memory ``frozenset``; no database tables,
no ORM migrations for country data, and no external API calls are ever
made.

Overview
--------

* **ISO 3166-1 alpha-2** — 249 territories built-in.
* **O(1) validation** — ``frozenset`` membership test.
* **LRU-cached helpers** — choices and full registry cached after first access.
* **Strict input length guard** — inputs longer than 10 characters are
  rejected before any lookup, preventing DoS via huge strings.
* **Uppercase normalisation** — values are always stored and returned
  in uppercase.
* **OpenAPI enum** — ``CountryField.openapi_schema()`` returns a JSON
  Schema snippet with an ``enum`` of all valid codes.
* **Serializer support** — ``to_representation()`` can return either
  the raw code or a full ``{"code", "name", "dial_code"}`` dict.

Installation
------------

``openviper.contrib.countries`` is part of the core distribution.  No extra
packages are required.  Simply import ``CountryField``::

    from openviper.contrib.countries import CountryField

Usage
-----

Basic model field::

    from openviper.db import Model
    from openviper.contrib.countries import CountryField

    class UserProfile(Model):
        country = CountryField(null=True, db_index=True)

ORM filtering works as expected because the stored value is a plain
uppercase string::

    # Exact match
    profiles = await UserProfile.objects.filter(country="GB").all()

    # Nullable field — NULL rows
    profiles = await UserProfile.objects.filter(country=None).all()

Field options
~~~~~~~~~~~~~

``CountryField`` accepts all standard :class:`~openviper.db.fields.CharField`
keyword arguments plus:

``extra_countries``
    A tuple of ``(code, name, dial_code)`` triples for project-specific
    regions not in the ISO standard.

    .. code-block:: python

        class Profile(Model):
            region = CountryField(
                extra_countries=(
                    ("XA", "Atlantis", "+000"),
                )
            )

``strict``
    When ``True`` (default) the field only accepts exactly two ASCII letter
    codes.  Set to ``False`` to relax this constraint for custom codes that
    use digits or other characters.

Settings
--------

Add ``COUNTRY_FIELD`` to your project ``Settings`` subclass to customise
behaviour::

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        COUNTRY_FIELD: dict = dataclasses.field(
            default_factory=lambda: {
                "EXTRA_COUNTRIES": {
                    "XA": {"name": "Atlantis", "dial_code": "+000"},
                },
                "ENABLE_CACHE": True,
                "STRICT": True,
            }
        )

+------------------+---------+----------------------------------------------+
| Key              | Default | Description                                  |
+==================+=========+==============================================+
| EXTRA_COUNTRIES  | ``{}``  | Custom codes not in the ISO dataset.         |
+------------------+---------+----------------------------------------------+
| ENABLE_CACHE     | ``True``| Keep LRU caches warm (exposed for testing).  |
+------------------+---------+----------------------------------------------+
| STRICT           | ``True``| Require exactly two ASCII letters.           |
+------------------+---------+----------------------------------------------+

Serializer usage
----------------

Return the raw ISO code (default)::

    # Serializer output:
    {"country": "GB"}

Return the full country object::

    from openviper.contrib.countries import CountryField

    class ProfileSerializer(ModelSerializer):
        class Meta:
            model = UserProfile

        def to_representation(self, instance):
            data = super().to_representation(instance)
            field = self.model._meta.fields["country"]
            data["country"] = field.to_representation(
                instance.country, full=True
            )
            return data

    # Serializer output:
    {
        "country": {
            "code": "GB",
            "name": "United Kingdom",
            "dial_code": "+44"
        }
    }

OpenAPI example
---------------

When building OpenAPI schemas, call ``CountryField.openapi_schema()`` to
receive a ready-made JSON Schema fragment::

    CountryField.openapi_schema()
    # {
    #     "type": "string",
    #     "enum": ["AD", "AE", "AF", ..., "ZW"],
    #     "description": "ISO 3166-1 alpha-2 country code",
    #     "pattern": "^[A-Z]{2}$",
    #     "example": "GB"
    # }

Utility helpers
---------------

The following helpers are exported directly from ``openviper.contrib.countries``:

.. py:function:: validate_country(code, extra=(), strict=True) -> bool

   Return ``True`` if *code* is a valid alpha-2 country code.

.. py:function:: get_country_name(code, extra=()) -> str | None

   Return the English country name for *code*, or ``None``.

.. py:function:: get_dial_code(code, extra=()) -> str | None

   Return the international dialling prefix for *code*, or ``None``.

.. py:function:: search_country(query, extra=()) -> list[dict]

   Search countries by partial name or exact code.  Returns
   ``[{"code": ..., "name": ..., "dial_code": ...}, ...]`` sorted
   alphabetically by name.

.. py:function:: get_country_choices(extra=()) -> tuple[tuple[str, str], ...]

   Return ``(code, name)`` pairs sorted by name, suitable for select
   widgets and serializer ``choices`` parameters.

Performance
-----------

* The full dataset is loaded once at first import and held in the process
  memory.  There is no per-request overhead.
* ``validate_country()`` performs a single ``frozenset.__contains__`` call:
  O(1) constant time.
* ``get_countries()``, ``get_country()``, and ``get_country_choices()`` are
  decorated with ``functools.lru_cache`` so repeated calls with identical
  arguments return the cached result instantly.
* The ``CHAR(2)`` column type and optional ``db_index=True`` ensure fast
  equality filters and ``ORDER BY country`` queries at the database level.

.. note::

   ``CountryField`` stores its length in the column type as ``CHAR(2)`` (or
   ``CHAR(n)`` for a custom ``max_length``).  Bare ``CHAR`` without a length
   defaults to ``CHAR(1)`` in PostgreSQL, which would truncate any value
   longer than one character.  Always regenerate and apply migrations after
   upgrading from a version that used the bare ``CHAR`` type:

   .. code-block:: bash

      python viperctl.py makemigrations
      python viperctl.py migrate

Security
--------

* **Length guard** — values longer than 10 characters are rejected before
  any lookup, preventing denial-of-service via pathological input.
* **Strict mode** — the default ``strict=True`` enforces the two-letter
  alphabetic format, blocking numeric codes, SQL injection strings, and
  other malformed inputs.
* **Uppercase normalisation** — all values are uppercased before both
  storage and validation, eliminating case-sensitivity edge cases.
* **No dynamic SQL** — country validation never touches the database.

Testing
-------

Unit tests live in ``tests/unit/countries/test_country_field.py``.
Integration tests live in ``tests/integration/countries/test_country_integration.py``.

Run them with::

    pytest tests/unit/countries/ tests/integration/countries/ -v
