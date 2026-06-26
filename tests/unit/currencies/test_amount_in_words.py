"""Tests for convert_amount_to_words utility and Money properties."""

from __future__ import annotations

from decimal import Decimal

import pytest

from openviper.contrib.fields.currencies import CurrencyField, Money, convert_amount_to_words
from openviper.db.fields import CharField
from openviper.db.models import Model


class TestAmountInWords:
    """convert_amount_to_words converts numeric amounts to English words."""

    def test_zero(self) -> None:
        assert convert_amount_to_words(0) == "zero dollars"

    def test_one_dollar(self) -> None:
        assert convert_amount_to_words(1) == "one dollar"

    def test_one_cent(self) -> None:
        assert convert_amount_to_words(Decimal("0.01")) == "zero dollars and one cent"

    def test_simple_whole(self) -> None:
        assert convert_amount_to_words(100) == "one hundred dollars"

    def test_with_cents(self) -> None:
        result = convert_amount_to_words(Decimal("19.99"))
        assert result == "nineteen dollars and ninety-nine cents"

    def test_thousands(self) -> None:
        result = convert_amount_to_words(1250)
        assert result == "one thousand two hundred fifty dollars"

    def test_millions(self) -> None:
        result = convert_amount_to_words(Decimal("1000000"))
        assert result == "one million dollars"

    def test_large_with_cents(self) -> None:
        result = convert_amount_to_words(Decimal("1250.75"))
        assert result == "one thousand two hundred fifty dollars and seventy-five cents"

    def test_custom_currency_names(self) -> None:
        result = convert_amount_to_words(
            Decimal("5.50"),
            currency_name="euro",
            currency_plural="euros",
            sub_name="cent",
            sub_plural="cents",
        )
        assert result == "five euros and fifty cents"

    def test_singular_vs_plural_dollar(self) -> None:
        assert "dollar" in convert_amount_to_words(1)
        assert "dollars" in convert_amount_to_words(2)

    def test_singular_vs_plural_cent(self) -> None:
        assert "one cent" in convert_amount_to_words(Decimal("0.01"))
        assert "cents" in convert_amount_to_words(Decimal("0.50"))

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="Negative"):
            convert_amount_to_words(-1)

    def test_too_large_raises(self) -> None:
        with pytest.raises(ValueError, match="maximum"):
            convert_amount_to_words(Decimal("10") ** 18)

    def test_string_input(self) -> None:
        result = convert_amount_to_words("99.99")
        assert result == "ninety-nine dollars and ninety-nine cents"

    def test_int_input(self) -> None:
        result = convert_amount_to_words(42)
        assert result == "forty-two dollars"

    def test_float_input(self) -> None:
        result = convert_amount_to_words(10.50)
        assert result == "ten dollars and fifty cents"

    def test_no_cents_whole_number(self) -> None:
        result = convert_amount_to_words(100)
        assert "and" not in result
        assert "cents" not in result


class TestMoneyFormattedCurrency:
    """Money.formatted_currency returns formatted string with symbol and space."""

    def test_whole_usd(self) -> None:
        m = Money("100", "USD")
        assert m.formatted_currency == "$ 100"

    def test_decimal_usd(self) -> None:
        m = Money("19.99", "USD")
        assert m.formatted_currency == "$ 19.99"

    def test_thousands_grouping(self) -> None:
        m = Money("1500", "EUR")
        assert m.formatted_currency == "€ 1,500"

    def test_gbp(self) -> None:
        m = Money("50.00", "GBP")
        assert m.formatted_currency == "£ 50"

    def test_jpy_no_decimals(self) -> None:
        m = Money("1000", "JPY")
        assert "1,000" in m.formatted_currency

    def test_zero(self) -> None:
        m = Money("0", "USD")
        assert m.formatted_currency == "$ 0"

    def test_negative_usd(self) -> None:
        m = Money("-5.50", "USD")
        assert m.formatted_currency == "-$ 5.50"

    def test_negative_eur(self) -> None:
        m = Money("-1500", "EUR")
        assert m.formatted_currency == "-€ 1,500"

    def test_code_as_symbol_sek(self) -> None:
        m = Money("1500", "SEK")
        assert m.formatted_currency == "SEK 1,500"

    def test_code_as_symbol_xau(self) -> None:
        m = Money("1500", "XAU")
        assert m.formatted_currency == "XAU 1,500"

    def test_fractional_chf(self) -> None:
        m = Money("100.50", "CHF")
        assert m.formatted_currency == "CHF 100.50"


class TestMoneyAmountInWords:
    """Money.amount_in_words spells out the amount with currency names."""

    def test_usd_whole(self) -> None:
        m = Money("100", "USD")
        assert m.amount_in_words == "one hundred US Dollars"

    def test_usd_with_cents(self) -> None:
        m = Money("19.99", "USD")
        assert m.amount_in_words == "nineteen US Dollars and ninety-nine cents"

    def test_eur_singular(self) -> None:
        m = Money("1", "EUR")
        assert m.amount_in_words == "one Euro"

    def test_eur_plural(self) -> None:
        m = Money("5", "EUR")
        assert m.amount_in_words == "five Euros"

    def test_gbp_with_cents(self) -> None:
        m = Money("1500.75", "GBP")
        assert m.amount_in_words == (
            "one thousand five hundred British Pounds and seventy-five cents"
        )

    def test_jpy_no_cents(self) -> None:
        m = Money("1000", "JPY")
        assert m.amount_in_words == "one thousand Japanese Yen"

    def test_one_cent(self) -> None:
        m = Money("0.01", "USD")
        assert m.amount_in_words == "zero US Dollars and one cent"

    def test_fifty_cents(self) -> None:
        m = Money("0.50", "USD")
        assert m.amount_in_words == "zero US Dollars and fifty cents"

    def test_kuwaiti_dinar_mills(self) -> None:
        m = Money("500.500", "KWD")
        result = m.amount_in_words
        assert "Kuwaiti Dinars" in result

    def test_via_model_instance(self) -> None:
        class WordProduct(Model):
            class Meta:
                table_name = "test_amount_words_model"

            name = CharField(max_length=100)
            price = CurrencyField(max_digits=12, decimal_places=2, default_currency="USD")

        p = WordProduct(name="Widget", price=Money("1250.99", "USD"))
        assert p.price.amount_in_words == (
            "one thousand two hundred fifty US Dollars and ninety-nine cents"
        )
        assert p.price.formatted_currency == "$ 1,250.99"
