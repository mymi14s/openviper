"""Tests for CurrencyField gap fixes: precision validation, serialization, migration."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from openviper.admin.api.serializers import serialize_value
from openviper.admin.fields import coerce_field_value
from openviper.contrib.fields.currencies import CurrencyField, Money
from openviper.contrib.fields.currencies.field import CurrencyCodeField
from openviper.db.fields import CharField
from openviper.db.models import Model


class TestPrecisionValidation:
    """CurrencyField.validate enforces max_digits and decimal_places."""

    def test_validate_exceeds_max_digits(self) -> None:
        field = CurrencyField(max_digits=5, decimal_places=2, default_currency="USD")
        field.name = "price"
        with pytest.raises(ValueError, match="exceeds max_digits"):
            field.validate(Money("123456.00", "USD"))

    def test_validate_exceeds_decimal_places(self) -> None:
        field = CurrencyField(max_digits=10, decimal_places=2, default_currency="USD")
        field.name = "price"
        with pytest.raises(ValueError, match="exceeds decimal_places"):
            field.validate(Money("10.123", "USD"))

    def test_validate_within_bounds_passes(self) -> None:
        field = CurrencyField(max_digits=5, decimal_places=2, default_currency="USD")
        field.name = "price"
        field.validate(Money("123.45", "USD"))

    def test_check_precision_directly(self) -> None:
        field = CurrencyField(max_digits=10, decimal_places=2)
        field.check_precision(Decimal("99999999.99"))
        with pytest.raises(ValueError, match="exceeds max_digits"):
            field.check_precision(Decimal("9999999999.99"))


class TestSerializeValueMoney:
    """serialize_value correctly handles Money objects."""

    def test_serialize_money_returns_amount_string(self) -> None:
        m = Money("19.99", "USD")
        result = serialize_value(m)
        assert result == "19.99"

    def test_serialize_money_with_high_precision(self) -> None:
        m = Money("1234.567890", "EUR")
        result = serialize_value(m)
        assert "1234.56789" in str(result)

    def test_serialize_money_not_confused_with_decimal(self) -> None:
        """Money should not hit the as_tuple/float path."""
        m = Money("100.00", "GBP")
        result = serialize_value(m)
        assert isinstance(result, str)
        assert result == "100"

    def test_serialize_plain_decimal_still_floats(self) -> None:
        result = serialize_value(Decimal("42.5"))
        assert result == 42.5


class TestMoneyScalarArithmetic:
    """Scalar arithmetic preserves decimal_places."""

    def test_mul_scalar_preserves_decimal_places(self) -> None:
        m = Money("10.00", "USD", decimal_places=2)
        result = m * Decimal("2")
        assert result.decimal_places == 2

    def test_div_scalar_preserves_decimal_places(self) -> None:
        m = Money("10.00", "USD", decimal_places=2)
        result = m / Decimal("2")
        assert result.decimal_places == 2

    def test_mul_int_preserves_decimal_places(self) -> None:
        m = Money("10.00", "USD", decimal_places=2)
        result = m * 2
        assert result.decimal_places == 2

    def test_div_int_preserves_decimal_places(self) -> None:
        m = Money("10.00", "USD", decimal_places=2)
        result = m / 2
        assert result.decimal_places == 2


class TestQuantizeToCurrencyNoneSubUnit:
    """quantize_to_currency handles currencies with no sub_unit."""

    def test_gold_currency_no_sub_unit(self) -> None:
        m = Money("100.123456", "XAU", decimal_places=4)
        result = m.quantize_to_currency()
        assert result.amount == Decimal("100.1235")


class TestMoneyStrDeterministic:
    """Money.__str__ uses a deterministic locale."""

    def test_str_is_deterministic(self) -> None:
        m = Money("1500.00", "USD")
        s1 = str(m)
        s2 = str(m)
        assert s1 == s2
        assert "1,500" in s1 or "1500" in s1


class TestToRepresentationKeyAlignment:
    """to_representation uses 'currency' key matching openapi_schema."""

    def test_full_representation_uses_currency_key(self) -> None:
        field = CurrencyField(default_currency="USD")
        result = field.to_representation(Money("19.99", "USD"), full=True)
        assert isinstance(result, dict)
        assert "currency" in result
        assert "code" not in result
        assert result["currency"] == "USD"


class TestGetSaType:
    """CurrencyField.get_sa_type returns Numeric with correct precision."""

    def test_get_sa_type_returns_numeric(self) -> None:
        field = CurrencyField(max_digits=12, decimal_places=2)
        sa_type = field.get_sa_type()
        assert isinstance(sa_type, sa.Numeric)
        assert sa_type.precision == 12
        assert sa_type.scale == 2


class TestMoneyDefaultCoercion:
    """CurrencyField __init__ coerces Money default to Decimal."""

    def test_money_default_coerced_to_decimal(self) -> None:
        field = CurrencyField(default=Money("10.00", "USD"), default_currency="USD")
        assert field.default == Decimal("10.00")

    def test_decimal_default_preserved(self) -> None:
        field = CurrencyField(default=Decimal("5.00"), default_currency="USD")
        assert field.default == Decimal("5.00")


class TestCurrencyCodeFieldCoercion:
    """admin coerce_field_value uppercases CurrencyCodeField values."""

    def test_coerce_uppercases_currency_code(self) -> None:
        field = CurrencyCodeField()
        field.name = "price_currency"
        result = coerce_field_value(field, "usd")
        assert result == "USD"

    def test_coerce_none_currency_code(self) -> None:
        field = CurrencyCodeField(null=True)
        field.name = "price_currency"
        result = coerce_field_value(field, None)
        assert result is None


class TestSiblingFieldMarker:
    """CurrencyCodeField sibling has _is_currency_sibling marker."""

    def test_sibling_has_marker(self) -> None:
        class CurrencyTestModel(Model):
            class Meta:
                table_name = "currency_test_marker"

            name = CharField(max_length=50)
            price = CurrencyField(max_digits=10, decimal_places=2)

        sibling = CurrencyTestModel._fields["price_currency"]
        assert getattr(sibling, "_is_currency_sibling", False) is True

    def test_non_sibling_lacks_marker(self) -> None:
        class CurrencyTestModel2(Model):
            class Meta:
                table_name = "currency_test_marker2"

            name = CharField(max_length=50)

        assert getattr(CurrencyTestModel2._fields["name"], "_is_currency_sibling", False) is False
