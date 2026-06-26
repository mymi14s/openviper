"""ISO 4217 CurrencyField - monetary amount paired with a currency code.

A single ``CurrencyField`` declaration creates two physical database
columns: a ``NUMERIC`` amount column (enabling native SQL ``SUM``/``AVG``
and arithmetic rollups) and a sibling ``CHAR(3)`` currency-code column
named ``<field>_currency``.

Instance attribute access returns a :class:`Money` value object exposing
arithmetic operators; assignment accepts ``Money``, ``(amount, currency)``
tuples, bare numeric amounts, or ``"1500.00 USD"`` strings.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

from openviper.contrib.fields.currencies.money import Money
from openviper.contrib.fields.currencies.utils import (
    get_currency_choices,
    get_currency_name,
    get_currency_symbol,
    validate_currency,
)
from openviper.db.fields import CharField, DecimalField

if TYPE_CHECKING:
    from openviper.contrib.fields.currencies.types import (
        CurrencyRepresentation,
        CurrencySchema,
        ExtraCurrencies,
        FormatOptions,
        MoneyOwner,
    )
    from openviper.db.fields import Field

DEFAULT_MAX_DIGITS: int = 19
DEFAULT_DECIMAL_PLACES: int = 2
CURRENCY_CODE_MAX_LENGTH: int = 3

MoneyInput = (
    Money
    | tuple[Decimal | str | int | float | None, str | None]
    | str
    | int
    | float
    | Decimal
    | None
)


def get_currency_field_name(field_name: str) -> str:
    """Return the sibling currency column name for *field_name*."""
    return f"{field_name}_currency"


class CurrencyCodeField(CharField):
    """CHAR(3) column storing an ISO 4217 currency code."""

    _column_type = "CHAR"

    def __init__(self, max_length: int = CURRENCY_CODE_MAX_LENGTH, **kwargs: object) -> None:
        super().__init__(max_length=max_length, **kwargs)  # type: ignore[arg-type]
        self._column_type = "CHAR"

    @property
    def column_type(self) -> str:
        return f"{self._column_type}({self.max_length})"

    @column_type.setter
    def column_type(self, value: str) -> None:
        self._column_type = value

    def to_python(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value).upper()

    def to_db(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value).upper()


class CurrencyField(DecimalField):
    """Monetary amount column paired with an ISO 4217 currency code.

    Args:
        max_digits: Total digits for the NUMERIC amount column (default 19).
        decimal_places: Decimal places for the amount column (default 4,
            capped at 6 per the CurrencyField specification).
        default_currency: ISO 4217 currency code used when a bare numeric
            value is assigned (default 'USD').
        currency_choices: Restrict accepted codes to this sequence of
            ``(code, name)`` pairs. Empty means accept all ISO 4217 codes.
        currency_max_length: Width of the currency code column (default 3).
        currency_field_name: Override the sibling currency column name.
        extra_currencies: Additional custom ``(code, name)`` tuples accepted
            alongside the ISO 4217 registry.
        strict: When False, accept any 3-letter uppercase code not in the registry.
        allow_negative: Permit negative amounts (refunds/credits). Defaults to False.
    """

    def __init__(
        self,
        max_digits: int = DEFAULT_MAX_DIGITS,
        decimal_places: int = DEFAULT_DECIMAL_PLACES,
        *,
        default_currency: str = "USD",
        currency_choices: tuple[tuple[str, str], ...] | None = None,
        currency_max_length: int = CURRENCY_CODE_MAX_LENGTH,
        currency_field_name: str | None = None,
        extra_currencies: ExtraCurrencies = (),
        strict: bool = True,
        allow_negative: bool = False,
        format_options: FormatOptions | None = None,
        **kwargs: object,
    ) -> None:
        if decimal_places < 0 or decimal_places > 6:
            raise ValueError("decimal_places must be between 0 and 6.")
        raw_default = kwargs.get("default")
        if isinstance(raw_default, Money):
            kwargs["default"] = raw_default.amount
        super().__init__(max_digits=max_digits, decimal_places=decimal_places, **kwargs)  # type: ignore[arg-type]
        self.default_currency: str = default_currency.upper()
        self.currency_choices: tuple[tuple[str, str], ...] | None = currency_choices
        self.currency_max_length: int = currency_max_length
        self.currency_field_name_override: str | None = currency_field_name
        self.extra_currencies: ExtraCurrencies = extra_currencies
        self.strict: bool = strict
        self.allow_negative: bool = allow_negative
        self.format_options: FormatOptions | None = format_options
        self._currency_field: CurrencyCodeField | None = None

    def contribute_to_class(self, model_class: type, name: str) -> None:
        """Inject the sibling currency code field onto the model class.

        The currency field is inserted immediately before the amount field
        in ``_fields`` so that ``Model.__init__`` processes it first; the
        amount field's descriptor then sets the currency from the assigned
        Money value without being clobbered by a later None default.
        """
        self.name = name
        currency_field_name = self.resolve_currency_field_name(name)
        currency_field = CurrencyCodeField(
            max_length=self.currency_max_length,
            default=None,
            editable=False,
            null=self.null,
            unique=False,
            db_index=False,
        )
        currency_field.name = currency_field_name
        currency_field._column_type = "CHAR"
        currency_field._is_currency_sibling = True
        fields: dict[str, Field] = model_class._fields  # type: ignore[attr-defined]
        reordered: dict[str, Field] = {}
        for key, val in fields.items():
            if key == name:
                reordered[currency_field_name] = currency_field
            reordered[key] = val
        if currency_field_name not in reordered:
            reordered[currency_field_name] = currency_field
        fields.clear()
        fields.update(reordered)
        setattr(model_class, currency_field_name, currency_field)
        known_fields: set[str] | None = getattr(model_class, "_known_fields", None)
        if known_fields is not None:
            known_fields.add(currency_field_name)
        col_to_field: dict[str, str] | None = getattr(model_class, "_col_to_field", None)
        if col_to_field is not None:
            col_to_field[currency_field.column_name] = currency_field_name
        self._currency_field = currency_field

    def resolve_currency_field_name(self, name: str) -> str:
        if self.currency_field_name_override is not None:
            return self.currency_field_name_override
        return get_currency_field_name(name)

    def currency_column_name(self) -> str:
        if self._currency_field is not None:
            return self._currency_field.column_name
        return get_currency_field_name(self.column_name)

    def __get__(
        self,
        obj: MoneyOwner | None,
        objtype: type | None = None,
    ) -> CurrencyField | Money | None:
        if obj is None:
            return self
        amount = obj.__dict__.get(self.name)
        currency = obj.__dict__.get(self.currency_column_name())
        if amount is None:
            return None
        instance_format_options = obj.__dict__.get(
            f"_{self.name}_format_options"
        )
        fmt_opts = (
            instance_format_options
            if instance_format_options is not None
            else self.format_options
        )
        money = self.to_python((amount, currency), format_options=fmt_opts)
        money.bound_field = self
        money.bound_instance = obj
        return money

    def __set__(self, obj: MoneyOwner, value: MoneyInput) -> None:
        if value is None:
            obj.__dict__[self.name] = None
            if not self.null:
                obj.__dict__[self.currency_column_name()] = self.default_currency
            else:
                obj.__dict__[self.currency_column_name()] = None
            return
        amount, currency = self.prepare_value(obj, value)
        obj.__dict__[self.name] = amount
        obj.__dict__[self.currency_column_name()] = currency

    def set_format_options(
        self,
        obj: MoneyOwner | None = None,
        format_options: FormatOptions | None = None,
    ) -> None:
        """Set formatting options for this field.

        When *obj* is provided, the options are stored on that specific
        model instance and affect only ``obj.price`` accesses.

        When *obj* is ``None``, the options are set on the field itself
        and affect **all** instances of the model.

        .. code-block:: python

           # Global: all instances use de_DE formatting
           Product._fields["price"].set_format_options(format_options={"locale": "de_DE"})

           # Per-instance: only this product uses de_DE
           product = await Product.objects.get(id=1)
           Product._fields["price"].set_format_options(product, {"locale": "de_DE"})
        """
        if obj is None:
            self.format_options = format_options
        else:
            obj.__dict__[f"_{self.name}_format_options"] = format_options

    def prepare_value(
        self,
        obj: MoneyOwner,
        value: MoneyInput,
    ) -> tuple[Decimal | None, str | None]:
        """Coerce *value* into ``(amount, currency_code)`` and set currency on obj."""
        currency: str | None
        amount: Decimal | None

        if isinstance(value, Money):
            currency = value.currency.code
            amount = value.amount
        elif isinstance(value, tuple) and len(value) == 2:
            amount_raw, currency_raw = value
            currency = self.default_currency if currency_raw is None else str(currency_raw).upper()
            amount = Decimal(str(amount_raw)) if amount_raw is not None else None
        elif isinstance(value, str) and " " in value:
            parts = value.strip().split(None, 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid money string: {value!r}")
            amount = Decimal(str(parts[0]))
            currency = parts[1].upper()
        elif isinstance(value, (int, float, Decimal, str)):
            amount = Decimal(str(value))
            existing = obj.__dict__.get(self.currency_column_name())
            currency = existing if existing else self.default_currency
        else:
            amount = Decimal(str(value))
            currency = self.default_currency

        if amount is not None and not self.allow_negative and amount < 0:
            raise ValueError(f"Field '{self.name}' does not allow negative amounts.")

        return amount, currency

    def to_python(
        self,
        value: object,
        *,
        format_options: FormatOptions | None = None,
    ) -> Money | None:
        if value is None:
            return None
        if isinstance(value, Money):
            return value
        fmt_opts = format_options if format_options is not None else self.format_options
        if isinstance(value, tuple) and len(value) == 2:
            amount_raw, currency_raw = value
            if amount_raw is None:
                return None
            currency = currency_raw if currency_raw else self.default_currency
            return Money(
                amount_raw,
                currency,
                decimal_places=self.decimal_places,
                format_options=fmt_opts,
            )
        amount = Decimal(str(value))
        return Money(
            amount,
            self.default_currency,
            decimal_places=self.decimal_places,
            format_options=fmt_opts,
        )

    def to_db(self, value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Money):
            return value.amount
        if isinstance(value, tuple) and len(value) == 2:
            amount_raw, _currency = value
            return Decimal(str(amount_raw)) if amount_raw is not None else None
        return Decimal(str(value))

    def validate(self, value: object) -> None:
        if value is None:
            if not self.null:
                raise ValueError(f"Field '{self.name}' cannot be null.")
            return
        if isinstance(value, Money):
            amount = value.amount
            currency_code = value.currency.code
        elif isinstance(value, tuple) and len(value) == 2:
            amount_raw, currency_raw = value
            amount = Decimal(str(amount_raw))
            currency_code = str(currency_raw).upper() if currency_raw else self.default_currency
        else:
            amount = Decimal(str(value))
            currency_code = self.default_currency

        if not self.allow_negative and amount < 0:
            raise ValueError(f"Field '{self.name}' does not allow negative amounts.")

        if self.currency_choices is not None:
            allowed = {c[0].upper() for c in self.currency_choices}
            if currency_code not in allowed:
                raise ValueError(
                    f"Field '{self.name}' currency {currency_code!r} not in choices."
                )
        elif not validate_currency(currency_code, extra=self.extra_currencies, strict=self.strict):
            raise ValueError(
                f"Field '{self.name}' currency {currency_code!r} is not a valid ISO 4217 code."
            )

        self.check_precision(amount)

        super().validate(amount)

    def check_precision(self, amount: Decimal) -> None:
        """Enforce max_digits and decimal_places bounds on *amount*.

        Handles scientific notation (e.g. ``1E+20``) and NaN/Infinity
        by normalising via ``amount.normalize()`` and computing adjusted
        digit counts.
        """
        if not amount.is_finite():
            raise ValueError(f"Field '{self.name}': value must be a finite number.")
        normalized = amount.normalize()
        _sign, digits, exponent = normalized.as_tuple()
        adjusted = normalized.adjusted()
        total_digits = len(digits) + max(0, adjusted - len(digits) + 1)
        decimal_places_count = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        if total_digits > self.max_digits:
            raise ValueError(
                f"Field '{self.name}': value has {total_digits} digits, "
                f"exceeds max_digits={self.max_digits}"
            )
        if decimal_places_count > self.decimal_places:
            raise ValueError(
                f"Field '{self.name}': value has {decimal_places_count} decimal places, "
                f"exceeds decimal_places={self.decimal_places}"
            )

    def get_sa_type(self) -> object:
        """Return the SQLAlchemy column type for the amount column."""
        return sa.Numeric(precision=self.max_digits, scale=self.decimal_places)

    def get_choices(self) -> tuple[tuple[str, str], ...]:
        if self.currency_choices is not None:
            return self.currency_choices
        return get_currency_choices(self.extra_currencies)

    def to_representation(
        self,
        value: object,
        *,
        full: bool = False,
    ) -> CurrencyRepresentation:
        if value is None:
            return None
        if isinstance(value, Money):
            code = value.currency.code
            amount = value.amount
        elif isinstance(value, tuple) and len(value) == 2:
            amount, code = value
            code = str(code).upper() if code else self.default_currency
        else:
            return None
        if not full:
            return f"{amount} {code}"
        return {
            "amount": str(amount),
            "currency": code,
            "name": get_currency_name(code, self.extra_currencies),
            "symbol": get_currency_symbol(code),
        }

    @classmethod
    def openapi_schema(cls, extra_currencies: ExtraCurrencies = ()) -> CurrencySchema:
        """Return OpenAPI 3.1 JSON-Schema describing the money representation."""
        codes = [c[0] for c in get_currency_choices(extra_currencies)]
        return {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "string",
                    "description": "Decimal amount as a string to preserve precision.",
                    "example": "1500.00",
                },
                "currency": {
                    "type": "string",
                    "enum": codes,
                    "description": "ISO 4217 currency code.",
                    "pattern": "^[A-Z]{3}$",
                    "example": "USD",
                },
            },
            "required": ["amount", "currency"],
            "description": "Monetary amount with ISO 4217 currency code.",
        }


__all__ = [
    "CurrencyCodeField",
    "CurrencyField",
    "DEFAULT_DECIMAL_PLACES",
    "DEFAULT_MAX_DIGITS",
    "get_currency_field_name",
]
