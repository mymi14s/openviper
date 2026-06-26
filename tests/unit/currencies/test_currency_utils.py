"""Unit tests for openviper.contrib.fields.currencies utilities and validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from openviper.contrib.fields.currencies import (
    CurrencyField,
    CurrencyValidationError,
    Money,
    get_currency_choices,
    get_currency_name,
    get_currency_symbol,
    resolve_currency,
    search_currency,
    validate_currency,
)
from openviper.contrib.fields.currencies.money import DEFAULT_DECIMAL_PLACES, currency_symbol_cache
from openviper.db.fields import CharField
from openviper.db.models import Model

from moneyed import Currency


class TestValidateCurrency:
    """validate_currency correctly accepts and rejects codes."""

    def test_valid_iso_codes(self) -> None:
        for code in ("USD", "EUR", "GBP", "JPY", "NGN"):
            assert validate_currency(code) is True

    def test_lowercase_normalised_to_uppercase(self) -> None:
        assert validate_currency("usd") is True

    def test_invalid_short_code(self) -> None:
        assert validate_currency("US") is False

    def test_invalid_long_code(self) -> None:
        assert validate_currency("USDD") is False

    def test_none_returns_false(self) -> None:
        assert validate_currency(None) is False

    def test_empty_string_returns_false(self) -> None:
        assert validate_currency("") is False

    def test_extra_currency_accepted(self) -> None:
        assert validate_currency("XBT", extra=(("XBT", "Bitcoin"),)) is True

    def test_strict_rejects_unknown_code(self) -> None:
        assert validate_currency("XYZ") is False

    def test_non_strict_accepts_unknown_code(self) -> None:
        assert validate_currency("XYZ", strict=False) is True


class TestGetCurrencyName:
    """get_currency_name resolves display names."""

    def test_known_code(self) -> None:
        assert get_currency_name("USD") is not None
        assert "dollar" in get_currency_name("USD").lower()

    def test_unknown_code(self) -> None:
        assert get_currency_name("XYZ") is None

    def test_none_returns_none(self) -> None:
        assert get_currency_name(None) is None

    def test_extra_currency_name(self) -> None:
        result = get_currency_name("XBT", extra=(("XBT", "Bitcoin"),))
        assert result == "Bitcoin"


class TestGetCurrencySymbol:
    """get_currency_symbol returns best-effort symbols."""

    def test_known_code_returns_string(self) -> None:
        symbol = get_currency_symbol("USD")
        assert symbol is not None

    def test_none_returns_none(self) -> None:
        assert get_currency_symbol(None) is None


class TestGetCurrencyChoices:
    """get_currency_choices returns sorted (code, name) pairs."""

    def test_returns_non_empty_tuple(self) -> None:
        choices = get_currency_choices()
        assert isinstance(choices, tuple)
        assert len(choices) > 0

    def test_choices_sorted_by_name(self) -> None:
        choices = get_currency_choices()
        names = [c[1] for c in choices]
        assert names == sorted(names)

    def test_extra_currency_in_choices(self) -> None:
        choices = get_currency_choices((("XBT", "Bitcoin"),))
        codes = {c[0] for c in choices}
        assert "XBT" in codes


class TestSearchCurrency:
    """search_currency partial-matches names and exact-matches codes."""

    def test_exact_code_match(self) -> None:
        results = search_currency("USD")
        assert any(r["code"] == "USD" for r in results)

    def test_partial_name_match(self) -> None:
        results = search_currency("dollar")
        codes = {r["code"] for r in results}
        assert "USD" in codes

    def test_empty_query_returns_empty(self) -> None:
        assert search_currency("") == []

    def test_extra_currency_searchable(self) -> None:
        results = search_currency("bitcoin", extra=(("XBT", "Bitcoin"),))
        assert any(r["code"] == "XBT" for r in results)


class TestResolveCurrency:
    """resolve_currency returns a Currency or raises."""

    def test_valid_code_returns_currency(self) -> None:
        currency = resolve_currency("USD")
        assert isinstance(currency, Currency)
        assert currency.code == "USD"

    def test_invalid_code_raises(self) -> None:
        with pytest.raises(CurrencyValidationError):
            resolve_currency("ZZZ")

    def test_non_strict_allows_custom_code(self) -> None:
        currency = resolve_currency("XBT", strict=False)
        assert isinstance(currency, Currency)
        assert currency.code == "XBT"


class TestMoneyValueObject:
    """Money subclass arithmetic and formatting."""

    def test_creation_with_amount_and_currency(self) -> None:
        m = Money("19.99", "USD")
        assert str(m.amount) == "19.99"
        assert m.currency.code == "USD"

    def test_creation_preserves_decimal_places(self) -> None:
        m = Money("100.00", "EUR", decimal_places=2)
        assert m.decimal_places == 2

    def test_default_decimal_places(self) -> None:
        m = Money("50", "USD")
        assert m.decimal_places == DEFAULT_DECIMAL_PLACES

    def test_addition_same_currency(self) -> None:
        result = Money("10.00", "USD") + Money("5.00", "USD")
        assert result.amount == 15
        assert result.currency.code == "USD"

    def test_addition_different_currency_raises(self) -> None:
        with pytest.raises(TypeError):
            Money("10.00", "USD") + Money("5.00", "EUR")

    def test_subtraction_same_currency(self) -> None:
        result = Money("10.00", "USD") - Money("3.00", "USD")
        assert result.amount == 7

    def test_multiplication_by_scalar(self) -> None:
        result = Money("10.00", "USD") * 2
        assert result.amount == 20

    def test_division_by_scalar(self) -> None:
        result = Money("10.00", "USD") / 2
        assert result.amount == 5

    def test_sum_on_list_of_money(self) -> None:
        total = sum([Money("10.00", "USD"), Money("5.00", "USD")], Money("0", "USD"))
        assert total.amount == 15

    def test_negation(self) -> None:
        result = -Money("10.00", "USD")
        assert result.amount == -10

    def test_abs(self) -> None:
        result = abs(Money("-10.00", "USD"))
        assert result.amount == 10

    def test_str_returns_formatted(self) -> None:
        m = Money("1500.00", "USD")
        assert isinstance(str(m), str)
        assert "1,500" in str(m)

    def test_decimal_places_preserved_after_addition(self) -> None:
        m1 = Money("10.00", "USD", decimal_places=2)
        m2 = Money("5.00", "USD", decimal_places=2)
        result = m1 + m2
        assert result.decimal_places == 2

    def test_comparison_same_currency(self) -> None:
        assert Money("10.00", "USD") > Money("5.00", "USD")
        assert Money("5.00", "USD") < Money("10.00", "USD")
        assert Money("5.00", "USD") == Money("5.00", "USD")

    def test_comparison_different_currency_raises(self) -> None:
        with pytest.raises(TypeError):
            assert Money("10.00", "USD") > Money("5.00", "EUR")  # noqa: B015

    def test_quantize_to_currency_usd(self) -> None:
        m = Money("10.123", "USD")
        quantized = m.quantize_to_currency()
        assert quantized.amount == Decimal("10.12")

    def test_quantize_to_currency_jpy(self) -> None:
        m = Money("10.123", "JPY", decimal_places=0)
        quantized = m.quantize_to_currency()
        assert quantized.amount == 10


class TestCurrencySymbol:
    """Currency.symbol property returns the locale-correct symbol."""

    def test_usd_symbol(self) -> None:
        m = Money("19.99", "USD")
        assert m.currency.symbol == "$"

    def test_eur_symbol(self) -> None:
        m = Money("100.00", "EUR")
        assert m.currency.symbol == "€"

    def test_gbp_symbol(self) -> None:
        m = Money("50.00", "GBP")
        assert m.currency.symbol == "£"

    def test_jpy_symbol(self) -> None:
        m = Money("1000", "JPY")
        assert m.currency.symbol == "¥"

    def test_symbol_cached(self) -> None:
        m1 = Money("1.00", "USD")
        _ = m1.currency.symbol
        assert "USD" in currency_symbol_cache
        m2 = Money("2.00", "USD")
        assert m2.currency.symbol == "$"

    def test_symbol_via_model_instance(self) -> None:
        class SymbolProduct(Model):
            class Meta:
                table_name = "test_symbol_access"

            name = CharField(max_length=100)
            price = CurrencyField(max_digits=12, decimal_places=2, default_currency="USD")

        p = SymbolProduct(name="Widget", price=Money("19.99", "USD"))
        assert p.price.currency.symbol == "$"

    def test_money_symbol_shortcut(self) -> None:
        m = Money("19.99", "USD")
        assert m.symbol == "$"
        assert m.symbol == m.currency.symbol

    def test_money_symbol_eur(self) -> None:
        m = Money("100.00", "EUR")
        assert m.symbol == "€"

    def test_object_price_symbol(self) -> None:
        class SymbolProduct2(Model):
            class Meta:
                table_name = "test_symbol_shortcut"

            name = CharField(max_length=100)
            price = CurrencyField(max_digits=12, decimal_places=2, default_currency="USD")

        p = SymbolProduct2(name="Widget", price=Money("19.99", "USD"))
        assert p.price.symbol == "$"
