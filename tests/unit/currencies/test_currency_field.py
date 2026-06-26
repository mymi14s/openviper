"""Unit tests for CurrencyField ORM field behavior."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from openviper.contrib.fields.currencies import (
    CurrencyField,
    Money,
    get_currency_field_name,
)
from openviper.contrib.fields.currencies.field import (
    DEFAULT_DECIMAL_PLACES,
    DEFAULT_MAX_DIGITS,
    CurrencyCodeField,
)
from openviper.db.fields import CharField, DecimalField


class FakeOwner:
    """Minimal owner object with an attribute dict for descriptor tests."""

    def __init__(self) -> None:
        object.__setattr__(self, "_storage", {})

    @property
    def __dict__(self) -> dict[str, Any]:
        return self._storage

    @__dict__.setter
    def __dict__(self, value: dict[str, Any]) -> None:
        object.__setattr__(self, "_storage", value)


class TestCurrencyFieldInheritance:
    """CurrencyField is a proper DecimalField subclass."""

    def test_is_decimalfield_subclass(self) -> None:
        field = CurrencyField()
        assert isinstance(field, DecimalField)

    def test_column_type_is_numeric(self) -> None:
        field = CurrencyField(max_digits=12, decimal_places=2)
        assert field.column_type == "NUMERIC"

    def test_field_name_assigned(self) -> None:
        field = CurrencyField()
        field.name = "price"
        assert field.name == "price"

    def test_field_null_kwarg(self) -> None:
        field = CurrencyField(null=True)
        assert field.null is True

    def test_field_default_currency(self) -> None:
        field = CurrencyField(default_currency="EUR")
        assert field.default_currency == "EUR"

    def test_default_currency_uppercased(self) -> None:
        field = CurrencyField(default_currency="usd")
        assert field.default_currency == "USD"

    def test_default_max_digits(self) -> None:
        field = CurrencyField()
        assert field.max_digits == DEFAULT_MAX_DIGITS

    def test_default_decimal_places(self) -> None:
        field = CurrencyField()
        assert field.decimal_places == DEFAULT_DECIMAL_PLACES

    def test_decimal_places_capped_at_six(self) -> None:
        with pytest.raises(ValueError, match="decimal_places must be between 0 and 6"):
            CurrencyField(decimal_places=7)

    def test_decimal_places_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="decimal_places must be between 0 and 6"):
            CurrencyField(decimal_places=-1)

    def test_allow_negative_default_false(self) -> None:
        field = CurrencyField()
        assert field.allow_negative is False

    def test_allow_negative_true(self) -> None:
        field = CurrencyField(allow_negative=True)
        assert field.allow_negative is True


class TestCurrencyFieldNaming:
    """Sibling currency column naming follows the <name>_currency convention."""

    def test_default_currency_field_name(self) -> None:
        field = CurrencyField()
        assert get_currency_field_name("price") == "price_currency"
        assert field.resolve_currency_field_name("price") == "price_currency"

    def test_override_currency_field_name(self) -> None:
        field = CurrencyField(currency_field_name="ccy")
        assert field.resolve_currency_field_name("price") == "ccy"


class TestCurrencyCodeField:
    """CurrencyCodeField stores uppercase 3-letter codes."""

    def test_is_charfield_subclass(self) -> None:
        field = CurrencyCodeField()
        assert isinstance(field, CharField)

    def test_default_max_length(self) -> None:
        field = CurrencyCodeField()
        assert field.max_length == 3

    def test_column_type_is_char(self) -> None:
        field = CurrencyCodeField()
        assert field.column_type == "CHAR(3)"

    def test_to_python_uppercase(self) -> None:
        field = CurrencyCodeField()
        assert field.to_python("usd") == "USD"

    def test_to_python_none(self) -> None:
        field = CurrencyCodeField()
        assert field.to_python(None) is None

    def test_to_db_uppercase(self) -> None:
        field = CurrencyCodeField()
        assert field.to_db("gbp") == "GBP"

    def test_to_db_none(self) -> None:
        field = CurrencyCodeField()
        assert field.to_db(None) is None


class TestCurrencyFieldValueCoercion:
    """CurrencyField.prepare_value coerces diverse input formats."""

    def _make_obj(self) -> Any:
        return FakeOwner()

    def test_prepare_value_money_instance(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        obj = self._make_obj()
        amount, currency = field.prepare_value(obj, Money("19.99", "EUR"))
        assert amount == Decimal("19.99")
        assert currency == "EUR"

    def test_prepare_value_tuple(self) -> None:
        field = CurrencyField(default_currency="USD")
        obj = self._make_obj()
        amount, currency = field.prepare_value(obj, (Decimal("99.00"), "GBP"))
        assert amount == Decimal("99.00")
        assert currency == "GBP"

    def test_prepare_value_tuple_none_currency_uses_default(self) -> None:
        field = CurrencyField(default_currency="USD")
        obj = self._make_obj()
        amount, currency = field.prepare_value(obj, (Decimal("50.00"), None))
        assert amount == Decimal("50.00")
        assert currency == "USD"

    def test_prepare_value_money_string(self) -> None:
        field = CurrencyField(default_currency="USD")
        obj = self._make_obj()
        amount, currency = field.prepare_value(obj, "1500.00 EUR")
        assert amount == Decimal("1500.00")
        assert currency == "EUR"

    def test_prepare_value_bare_numeric_uses_default_currency(self) -> None:
        field = CurrencyField(default_currency="USD")
        obj = self._make_obj()
        amount, currency = field.prepare_value(obj, "19.99")
        assert amount == Decimal("19.99")
        assert currency == "USD"

    def test_prepare_value_bare_int_uses_default_currency(self) -> None:
        field = CurrencyField(default_currency="USD")
        obj = self._make_obj()
        amount, currency = field.prepare_value(obj, 100)
        assert amount == Decimal("100")
        assert currency == "USD"

    def test_prepare_value_negative_rejected_by_default(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        obj = self._make_obj()
        with pytest.raises(ValueError, match="does not allow negative"):
            field.prepare_value(obj, Decimal("-10.00"))

    def test_prepare_value_negative_allowed_when_configured(self) -> None:
        field = CurrencyField(default_currency="USD", allow_negative=True)
        obj = self._make_obj()
        amount, _ = field.prepare_value(obj, Decimal("-10.00"))
        assert amount == Decimal("-10.00")


class TestCurrencyFieldToDb:
    """to_db extracts the Decimal amount from Money or tuples."""

    def test_to_db_money_returns_amount(self) -> None:
        field = CurrencyField()
        assert field.to_db(Money("19.99", "USD")) == Decimal("19.99")

    def test_to_db_tuple_returns_amount(self) -> None:
        field = CurrencyField()
        assert field.to_db((Decimal("50.00"), "EUR")) == Decimal("50.00")

    def test_to_db_bare_decimal(self) -> None:
        field = CurrencyField()
        assert field.to_db(Decimal("100.00")) == Decimal("100.00")

    def test_to_db_none(self) -> None:
        field = CurrencyField()
        assert field.to_db(None) is None


class TestCurrencyFieldToPython:
    """to_python returns Money instances."""

    def test_to_python_money_passthrough(self) -> None:
        field = CurrencyField(default_currency="USD")
        m = Money("19.99", "USD")
        assert field.to_python(m) is m

    def test_to_python_tuple(self) -> None:
        field = CurrencyField(default_currency="USD")
        result = field.to_python((Decimal("50.00"), "EUR"))
        assert isinstance(result, Money)
        assert result.amount == Decimal("50.00")
        assert result.currency.code == "EUR"

    def test_to_python_tuple_none_amount(self) -> None:
        field = CurrencyField(default_currency="USD")
        assert field.to_python((None, "USD")) is None

    def test_to_python_bare_numeric_uses_default_currency(self) -> None:
        field = CurrencyField(default_currency="GBP")
        result = field.to_python(Decimal("99.00"))
        assert isinstance(result, Money)
        assert result.currency.code == "GBP"

    def test_to_python_none(self) -> None:
        field = CurrencyField(default_currency="USD")
        assert field.to_python(None) is None

    def test_to_python_preserves_decimal_places(self) -> None:
        field = CurrencyField(decimal_places=2)
        result = field.to_python((Decimal("50.00"), "USD"))
        assert result.decimal_places == 2


class TestCurrencyFieldValidate:
    """validate enforces nullability, choices, and currency membership."""

    def test_validate_valid_money(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        field.validate(Money("19.99", "USD"))

    def test_validate_null_on_non_nullable_raises(self) -> None:
        field = CurrencyField()
        field.name = "price"
        with pytest.raises(ValueError, match="cannot be null"):
            field.validate(None)

    def test_validate_null_on_nullable_passes(self) -> None:
        field = CurrencyField(null=True)
        field.name = "price"
        field.validate(None)

    def test_validate_negative_rejected(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        with pytest.raises(ValueError, match="negative"):
            field.validate(Money("-10.00", "USD"))

    def test_validate_negative_allowed(self) -> None:
        field = CurrencyField(default_currency="USD", allow_negative=True)
        field.name = "price"
        field.validate(Money("-10.00", "USD"))

    def test_validate_invalid_currency_rejected(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        with pytest.raises(ValueError, match="not a valid ISO 4217"):
            field.validate((Decimal("10.00"), "ZZZ"))

    def test_validate_currency_in_choices(self) -> None:
        field = CurrencyField(
            default_currency="USD",
            currency_choices=(("USD", "US Dollar"), ("EUR", "Euro")),
        )
        field.name = "price"
        field.validate(Money("10.00", "USD"))
        field.validate(Money("10.00", "EUR"))

    def test_validate_currency_not_in_choices_rejected(self) -> None:
        field = CurrencyField(
            default_currency="USD",
            currency_choices=(("USD", "US Dollar"),),
        )
        field.name = "price"
        with pytest.raises(ValueError, match="not in choices"):
            field.validate(Money("10.00", "EUR"))

    def test_validate_extra_currency_accepted(self) -> None:
        field = CurrencyField(
            default_currency="USD",
            extra_currencies=(("XBT", "Bitcoin"),),
        )
        field.name = "price"
        field.validate((Decimal("1.00"), "XBT"))


class TestCurrencyFieldRepresentation:
    """to_representation returns compact or full forms."""

    def test_to_representation_none(self) -> None:
        field = CurrencyField()
        assert field.to_representation(None) is None

    def test_to_representation_compact(self) -> None:
        field = CurrencyField()
        result = field.to_representation(Money("19.99", "USD"))
        assert "19.99" in result
        assert "USD" in result

    def test_to_representation_full(self) -> None:
        field = CurrencyField()
        result = field.to_representation(Money("19.99", "USD"), full=True)
        assert isinstance(result, dict)
        assert result["currency"] == "USD"
        assert "amount" in result
        assert "name" in result
        assert "symbol" in result


class TestCurrencyFieldOpenAPISchema:
    """openapi_schema returns a valid JSON-Schema dict."""

    def test_schema_has_type_object(self) -> None:
        schema = CurrencyField.openapi_schema()
        assert schema["type"] == "object"

    def test_schema_has_amount_and_currency_properties(self) -> None:
        schema = CurrencyField.openapi_schema()
        assert "amount" in schema["properties"]
        assert "currency" in schema["properties"]

    def test_schema_currency_has_enum(self) -> None:
        schema = CurrencyField.openapi_schema()
        assert "enum" in schema["properties"]["currency"]
        assert "USD" in schema["properties"]["currency"]["enum"]

    def test_schema_required_fields(self) -> None:
        schema = CurrencyField.openapi_schema()
        assert "amount" in schema["required"]
        assert "currency" in schema["required"]


class TestCurrencyFieldGetChoices:
    """get_choices returns choices filtered by currency_choices or all ISO codes."""

    def test_default_returns_all_currencies(self) -> None:
        field = CurrencyField()
        choices = field.get_choices()
        assert len(choices) > 0
        codes = {c[0] for c in choices}
        assert "USD" in codes

    def test_custom_choices_returned_as_is(self) -> None:
        field = CurrencyField(currency_choices=(("USD", "US Dollar"),))
        choices = field.get_choices()
        assert choices == (("USD", "US Dollar"),)

    def test_extra_currencies_in_choices(self) -> None:
        field = CurrencyField(extra_currencies=(("XBT", "Bitcoin"),))
        choices = field.get_choices()
        codes = {c[0] for c in choices}
        assert "XBT" in codes


class TestCurrencyFieldDescriptor:
    """The __get__/__set__ descriptor bridges model instance and Money."""

    def test_get_returns_money(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        obj = FakeOwner()
        obj.__dict__.update({"price": Decimal("19.99"), "price_currency": "USD"})
        result = field.__get__(obj, type(obj))
        assert isinstance(result, Money)
        assert result.amount == Decimal("19.99")
        assert result.currency.code == "USD"

    def test_get_returns_none_when_amount_is_none(self) -> None:
        field = CurrencyField(default_currency="USD", null=True)
        field.name = "price"
        obj = FakeOwner()
        obj.__dict__.update({"price": None, "price_currency": None})
        assert field.__get__(obj, type(obj)) is None

    def test_set_money_assigns_both_columns(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        obj = FakeOwner()
        field.__set__(obj, Money("50.00", "EUR"))
        assert obj.__dict__["price"] == Decimal("50.00")
        assert obj.__dict__["price_currency"] == "EUR"

    def test_set_none_clears_amount(self) -> None:
        field = CurrencyField(default_currency="USD")
        field.name = "price"
        obj = FakeOwner()
        field.__set__(obj, None)
        assert obj.__dict__["price"] is None
        assert obj.__dict__["price_currency"] == "USD"
