Currency Field
==============

The ``openviper.contrib.fields.currencies`` package provides a
**CurrencyField** for OpenViper models.  It stores a monetary amount
paired with an `ISO 4217 <https://en.wikipedia.org/wiki/ISO_4217>`_
currency code, enabling native SQL aggregation (``SUM``, ``AVG``) and
model-level ``Money`` arithmetic.

A single ``CurrencyField`` declaration creates **two physical database
columns**: a ``NUMERIC`` amount column and a sibling ``CHAR(3)`` currency
code column named ``<field>_currency``.  This two-column design means
``SELECT SUM(price)`` runs entirely in the database - no Python-level
aggregation is needed.

Overview
--------

* **ISO 4217 compliance** - Links the value to global currency codes like
  GBP, USD, or EUR.
* **Numeric validation** - Only viable mathematical values are recorded;
  ``max_digits`` and ``decimal_places`` are enforced at both the
  application and database levels.
* **Automatic formatting** - ``Money.__str__()`` renders locale-correct
  monetary formats (e.g. ``$1,500.00``) via ``babel``.
* **Calculation compatibility** - The amount column is a real ``NUMERIC``
  type, so ``SUM()``, ``AVG()``, and ``price * 1.2`` all execute in SQL.
* **Per-row currency** - Each row stores its own currency code, enabling
  multi-currency tables when filtered by ``price_currency = 'USD'``.
* **Money value object** - Instance access returns a :class:`Money` with
  arithmetic operators (``+``, ``-``, ``*``, comparisons) and cross-currency
  guards.
* **Admin panel support** - The admin UI renders a combined amount input
  with a searchable currency code dropdown.  The sibling currency column
  is hidden from the form automatically.

Installation
------------

``CurrencyField`` requires the ``py-moneyed`` and ``babel`` packages.
Install them via the ``currencies`` extra::

    pip install openviper[currencies]

Then import ``CurrencyField``::

    from openviper.contrib.fields.currencies import CurrencyField

Usage
-----

Basic model field::

    from openviper.db import Model
    from openviper.contrib.fields.currencies import CurrencyField

    class Product(Model):
        price = CurrencyField(max_digits=12, decimal_places=2, default_currency="USD")

Assigning values - the field accepts ``Money`` objects, tuples, bare
numerics, or ``"amount CODE"`` strings::

    from openviper.contrib.fields.currencies import Money

    product = Product(price=Money("19.99", "USD"))
    product.price          # Money('19.99', 'USD')
    product.price_currency # 'USD'

    # Tuple form
    product.price = (Decimal("99.00"), "GBP")
    product.price_currency # 'GBP'

    # String form
    product.price = "50.00 EUR"
    product.price_currency # 'EUR'

    # Bare numeric uses default_currency
    product.price = "19.99"
    product.price_currency # 'USD'

Native SQL aggregation works because the amount is a ``NUMERIC`` column::

    # SUM in the database
    total = await Product.objects.aggregate(Sum("price"))
    # AVG in the database
    avg = await Product.objects.aggregate(Avg("price"))

    # Filter by currency code
    usd_products = await Product.objects.filter(price_currency="USD").all()

Field options
~~~~~~~~~~~~~

``CurrencyField`` accepts all standard :class:`~openviper.db.fields.DecimalField`
keyword arguments plus:

``max_digits``
    Total digits for the ``NUMERIC`` amount column (default 19).

``decimal_places``
    Decimal places for the amount column (default 2, capped at 6).

``default_currency``
    ISO 4217 currency code used when a bare numeric value is assigned
    (default ``"USD"``).

``currency_choices``
    Restrict accepted codes to this sequence of ``(code, name)`` pairs.
    Empty means accept all ISO 4217 codes.

``currency_max_length``
    Width of the currency code column (default 3).

``currency_field_name``
    Override the sibling currency column name (default ``<field>_currency``).

``extra_currencies``
    Additional custom ``(code, name)`` tuples accepted alongside the
    ISO 4217 registry.

``strict``
    When ``False``, accept any 3-letter uppercase code not in the registry.

``allow_negative``
    Permit negative amounts for refunds/credits (default ``False``).

``format_options``
    A dict of formatting options passed to every ``Money`` instance
    created by this field.  Supported keys:

    - ``"locale"`` - Babel locale string for symbol positioning and
      number formatting (default ``"en_US"``).
    - ``"decimal_quantization"`` - Pad/truncate to locale decimal places
      (default ``True``).
    - ``"currency_digits"`` - Use the currency's official decimal places
      (default ``True``).

    .. code-block:: python

        class Invoice(Model):
            amount = CurrencyField(
                max_digits=12,
                decimal_places=2,
                default_currency="EUR",
                format_options={"locale": "de_DE"},
            )

        inv = Invoice(amount="1234.56")
        inv.price.formatted_currency  # "1.234,56 €"

Runtime formatting
~~~~~~~~~~~~~~~~~~~

Call ``set_format_options`` directly on the Money returned by the field
to change formatting at runtime.  Options persist across subsequent
attribute accesses on the same model instance.

.. code-block:: python

    product = await Product.objects.get(id=1)
    product.price.set_format_options(locale="de_DE")
    product.price.formatted_currency  # "123.456,99 €"

    # Multiple options
    product.price.set_format_options(
        locale="fr_FR",
        decimal_quantization=False,
    )

    # Reset to default
    product.price.set_format_options(locale="en_US")

Standalone ``Money`` objects also support ``set_format_options``:

.. code-block:: python

    m = Money("100.50", "USD")
    m.set_format_options(locale="de_DE")
    m.formatted_currency  # "100,50 $"

Advanced field examples
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    class Order(Model):
        # Crypto-friendly: 6 decimal places, custom code accepted
        amount = CurrencyField(
            max_digits=20,
            decimal_places=6,
            default_currency="USD",
            extra_currencies=(("XBT", "Bitcoin"),),
            strict=False,
        )

        # Refundable: negative amounts allowed
        adjustment = CurrencyField(
            max_digits=10,
            decimal_places=2,
            default_currency="USD",
            allow_negative=True,
        )

Money value object
------------------

When accessed on a model instance, ``CurrencyField`` returns a
:class:`~openviper.contrib.fields.currencies.Money` object that subclasses
``py-moneyed.Money``.  It supports arithmetic operators with cross-currency
guards:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Operation
     - Description
   * - ``Money + Money``
     - Addition.  Raises ``TypeError`` if currencies differ.
   * - ``Money - Money``
     - Subtraction.  Raises ``TypeError`` if currencies differ.
   * - ``Money * scalar``
     - Multiply by a number (returns ``Money``).
   * - ``Money / scalar``
     - Divide by a number (returns ``Money``).
   * - ``Money / Money``
     - Divide by same-currency Money (returns ``Decimal`` ratio).
   * - ``Money < Money``
     - Comparison.  Raises ``TypeError`` if currencies differ.
   * - ``sum([Money, ...])``
     - Built-in ``sum()`` works on same-currency lists.
   * - ``-Money``
     - Negation (returns ``Money``).
   * - ``abs(Money)``
     - Absolute value (returns ``Money``).
   * - ``str(Money)``
     - Locale-formatted string via babel (e.g. ``"$1,500.00"``).
   * - ``Money.symbol``
     - Currency symbol (e.g. ``"$"``, ``"€"``, ``"£"``).
   * - ``Money.formatted_currency``
     - Formatted string with symbol, spacing, and thousands separators
       (e.g. ``"$ 1,250.99"``, ``"€ 1,500"``, ``"SEK 1,500"``,
       ``"-$ 5.50"``). Uses babel for locale-aware symbol positioning.
   * - ``Money.amount_in_words``
     - Amount spelled out in English words using the currency's name
       and sub-unit (e.g. ``"one hundred US Dollars"``,
       ``"nineteen US Dollars and ninety-nine cents"``).
   * - ``Money.set_format_options(*, locale=None, decimal_quantization=None, currency_digits=None, **extra)``
     - Set formatting options that persist across attribute accesses.
       Accepts ``locale``, ``decimal_quantization``, ``currency_digits``,
       plus any additional babel ``format_money`` options via ``**extra``.
   * - ``Money.quantize_to_currency()``
     - Quantize to the currency's sub-unit precision.
   * - ``Money.round(ndigits)``
     - Round to *ndigits* decimal places.

.. code-block:: python

   from openviper.contrib.fields.currencies import Money

   p1 = Money("10.00", "USD")
   p2 = Money("5.00", "USD")

   total = p1 + p2          # Money('15.00', 'USD')
   doubled = p1 * 2         # Money('20.00', 'USD')
   diff = p1 - p2           # Money('5.00', 'USD')
   ratio = p1 / p2          # Decimal('2')

   # Cross-currency raises
   p3 = Money("5.00", "EUR")
   p1 + p3                  # TypeError

   # decimal_places is preserved across arithmetic
   m = Money("10.00", "USD", decimal_places=2)
   result = m * 2
   result.decimal_places    # 2

Utility helpers
---------------

The following helpers are exported from ``openviper.contrib.fields.currencies``:

.. py:function:: validate_currency(code, extra=(), strict=True) -> bool

   Return ``True`` if *code* is a valid ISO 4217 currency code.

.. py:function:: get_currency_name(code, extra=()) -> str | None

   Return the display name for *code*, or ``None``.

.. py:function:: get_currency_symbol(code) -> str | None

   Return a best-effort currency symbol via babel, or ``None``.

.. py:function:: get_currency_choices(extra=()) -> tuple[tuple[str, str], ...]

   Return ``(code, name)`` pairs sorted by name, suitable for select
   widgets.

.. py:function:: search_currency(query, extra=()) -> list[dict]

   Search currencies by partial name or exact code match.
   Returns ``[{"code": ..., "name": ...}, ...]`` sorted by name.

.. py:function:: resolve_currency(code, extra=(), strict=True) -> Currency

   Return a resolved ``Currency`` instance or raise
   ``CurrencyValidationError``.

.. py:function:: convert_amount_to_words(amount, *, currency_name="dollar", currency_plural="dollars", sub_name="cent", sub_plural="cents") -> str

   Convert a monetary amount to English words.  Handles amounts up to
   trillions with decimal sub-units.  Used by ``Money.amount_in_words``
   with the currency's ISO 4217 name and sub-unit.

   .. code-block:: python

      from openviper.contrib.fields.currencies import convert_amount_to_words

      convert_amount_to_words(Decimal("1250.75"))
      # "one thousand two hundred fifty dollars and seventy-five cents"

      convert_amount_to_words(1, currency_name="euro", currency_plural="euros")
      # "one euro"

``CurrencyField`` methods
~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: CurrencyField(max_digits=19, decimal_places=2, *, default_currency="USD", currency_choices=None, currency_max_length=3, currency_field_name=None, extra_currencies=(), strict=True, allow_negative=False, format_options=None, **kwargs)

   ORM field that stores a monetary amount and ISO 4217 currency code.

   .. py:method:: get_choices() -> tuple[tuple[str, str], ...]

      Return ``(code, name)`` pairs for all registered currencies.

   .. py:method:: to_representation(value, *, full=False) -> Any

      Serializer-friendly representation.  When *full* is ``True``,
      returns ``{"amount", "currency", "name", "symbol"}``.  When
      ``False`` (default), returns ``"amount CODE"`` string.

   .. py:classmethod:: openapi_schema(extra_currencies=()) -> dict

      Return an OpenAPI 3.1 JSON-Schema snippet with an ``enum`` of
      valid currency codes.

   .. py:method:: check_precision(amount) -> None

      Enforce ``max_digits`` and ``decimal_places`` bounds on *amount*.
      Raises ``ValueError`` if the value exceeds the declared precision.

   .. py:method:: set_format_options(obj=None, format_options=None) -> None

      Set formatting options for this field.  When *obj* is provided,
      options affect only that instance.  When *obj* is ``None``,
      options affect all instances of the model.

Admin panel integration
-----------------------

The admin panel automatically renders ``CurrencyField`` as a combined
amount input with a searchable currency code dropdown.  The sibling
``<field>_currency`` column is hidden from the form - the
``CurrencyField`` component manages both values.

The admin API returns field-level validation errors (e.g. "value has 3
decimal places, exceeds decimal_places=2") mapped to the correct field
name, so the frontend displays them inline under the input.

Serializer usage
----------------

``serialize_value()`` in the admin API returns the amount as a string
with trailing zeros normalised (e.g. ``"100"`` not ``"100.0000"``).
The currency code is available via the separate ``<field>_currency``
key in the serialised instance.

For custom serializers, use ``to_representation()``::

    from openviper.contrib.fields.currencies import CurrencyField

    class ProductSerializer(ModelSerializer):
        class Meta:
            model = Product

        def to_representation(self, instance):
            data = super().to_representation(instance)
            field = self.model._meta.fields["price"]
            data["price"] = field.to_representation(instance.price, full=True)
            return data

    # Serializer output:
    {
        "price": {
            "amount": "19.99",
            "currency": "USD",
            "name": "US Dollar",
            "symbol": "$"
        }
    }

OpenAPI example
---------------

.. code-block:: python

    CurrencyField.openapi_schema()
    # {
    #     "type": "object",
    #     "properties": {
    #         "amount": {"type": "string", "example": "1500.00"},
    #         "currency": {"type": "string", "enum": ["AED", "AFN", ...], "pattern": "^[A-Z]{3}$"}
    #     },
    #     "required": ["amount", "currency"],
    #     "description": "Monetary amount with ISO 4217 currency code."
    # }

Performance
-----------

* The amount column is a native ``NUMERIC`` type - ``SUM``, ``AVG``, and
  arithmetic all execute in the database engine.
* The currency code column is ``CHAR(3)`` with an optional ``db_index``
  for fast ``WHERE price_currency = 'USD'`` filters.
* ``Money`` arithmetic delegates to ``Decimal`` - no float conversion
  occurs, preserving exact precision.
* ``get_currency_choices()`` and ``validate_currency()`` operate on the
  in-memory py-moneyed registry (no database queries).

Testing
-------

Unit tests live in ``tests/unit/currencies/``.
Integration tests live in ``tests/integration/currencies/``.

Run them with::

    pytest tests/unit/currencies/ tests/integration/currencies/ -v