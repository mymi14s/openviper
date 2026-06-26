"""Integration tests for CurrencyField model-level and schema-level behavior."""

from __future__ import annotations

from decimal import Decimal

import pytest

from openviper.contrib.fields.currencies import CurrencyField, Money
from openviper.contrib.fields.currencies.field import CurrencyCodeField, get_currency_field_name
from openviper.db.executor import build_table
from openviper.db.fields import CharField, DecimalField
from openviper.db.models import Model
from sqlalchemy import Numeric
from sqlalchemy.types import String

from openviper.db.schemas.detect import detect_column_changes


class CurrencyProduct(Model):
    class Meta:
        table_name = "currency_product"

    name = CharField(max_length=100)
    price = CurrencyField(max_digits=12, decimal_places=2, default_currency="USD")


class MultiCurrencyProduct(Model):
    class Meta:
        table_name = "multi_currency_product"

    name = CharField(max_length=100)
    price = CurrencyField(max_digits=19, decimal_places=4, default_currency="EUR")
    cost = CurrencyField(max_digits=19, decimal_places=6, default_currency="USD", null=True)


class TestModelMetaWiring:
    """ModelMeta injects the sibling currency field during class creation."""

    def test_currency_field_in_fields(self) -> None:
        assert "price" in CurrencyProduct._fields

    def test_currency_code_field_in_fields(self) -> None:
        assert "price_currency" in CurrencyProduct._fields

    def test_currency_code_field_is_charfield(self) -> None:
        field = CurrencyProduct._fields["price_currency"]
        assert isinstance(field, CurrencyCodeField)

    def test_currency_field_is_decimalfield(self) -> None:
        field = CurrencyProduct._fields["price"]
        assert isinstance(field, DecimalField)

    def test_currency_code_field_name_set(self) -> None:
        field = CurrencyProduct._fields["price_currency"]
        assert field.name == "price_currency"

    def test_currency_field_name_set(self) -> None:
        field = CurrencyProduct._fields["price"]
        assert field.name == "price"

    def test_multiple_currency_fields_each_get_sibling(self) -> None:
        assert "price_currency" in MultiCurrencyProduct._fields
        assert "cost_currency" in MultiCurrencyProduct._fields

    def test_currency_code_field_column_type(self) -> None:
        field = CurrencyProduct._fields["price_currency"]
        assert "CHAR" in field.column_type or "VARCHAR" in field.column_type

    def test_amount_field_column_type_numeric(self) -> None:
        field = CurrencyProduct._fields["price"]
        assert field.column_type == "NUMERIC"


class TestModelInstanceAccess:
    """Instance attribute access returns Money; assignment coerces correctly."""

    def test_create_with_money(self) -> None:
        product = CurrencyProduct(name="Widget", price=Money("19.99", "USD"))
        assert isinstance(product.price, Money)
        assert product.price.amount == Decimal("19.99")
        assert product.price.currency.code == "USD"
        assert product.price_currency == "USD"

    def test_create_with_tuple(self) -> None:
        product = CurrencyProduct(name="Widget", price=(Decimal("99.00"), "GBP"))
        assert isinstance(product.price, Money)
        assert product.price.currency.code == "GBP"
        assert product.price_currency == "GBP"

    def test_create_with_money_string(self) -> None:
        product = CurrencyProduct(name="Widget", price="50.00 EUR")
        assert isinstance(product.price, Money)
        assert product.price.currency.code == "EUR"
        assert product.price_currency == "EUR"

    def test_create_with_bare_numeric_uses_default_currency(self) -> None:
        product = CurrencyProduct(name="Widget", price="19.99")
        assert isinstance(product.price, Money)
        assert product.price.currency.code == "USD"
        assert product.price_currency == "USD"

    def test_create_with_int(self) -> None:
        product = CurrencyProduct(name="Widget", price=100)
        assert isinstance(product.price, Money)
        assert product.price.amount == Decimal("100")

    def test_create_without_price_uses_default_currency(self) -> None:
        product = CurrencyProduct(name="Widget")
        assert product.price is None
        assert product.price_currency == "USD"

    def test_nullable_field_allows_none(self) -> None:
        product = MultiCurrencyProduct(name="Gadget")
        assert product.cost is None

    def test_assign_money_after_construction(self) -> None:
        product = CurrencyProduct(name="Widget")
        product.price = Money("75.00", "GBP")
        assert product.price_currency == "GBP"
        assert isinstance(product.price, Money)
        assert product.price.amount == Decimal("75.00")

    def test_assign_tuple_after_construction(self) -> None:
        product = CurrencyProduct(name="Widget")
        product.price = (Decimal("50.00"), "EUR")
        assert product.price_currency == "EUR"
        assert product.price.amount == Decimal("50.00")

    def test_assign_none_clears_amount(self) -> None:
        product = CurrencyProduct(name="Widget", price=Money("10.00", "USD"))
        product.price = None
        assert product.price is None


class TestSchemaDetection:
    """Schema detection emits both amount and currency columns."""

    def test_detect_added_columns_include_both(self) -> None:
        changes = detect_column_changes(
            CurrencyProduct,
            {"columns": [], "indexes": [], "unique_together": []},
        )
        added_names = {c["name"] for c in changes.get("added", [])}
        assert "price" in added_names
        assert "price_currency" in added_names

    def test_price_column_type_numeric(self) -> None:
        changes = detect_column_changes(
            CurrencyProduct,
            {"columns": [], "indexes": [], "unique_together": []},
        )
        price_col = next(c for c in changes["added"] if c["name"] == "price")
        assert price_col["type"] == "NUMERIC"

    def test_price_currency_column_type_char(self) -> None:
        changes = detect_column_changes(
            CurrencyProduct,
            {"columns": [], "indexes": [], "unique_together": []},
        )
        ccy_col = next(c for c in changes["added"] if c["name"] == "price_currency")
        assert "CHAR" in ccy_col["type"] or "VARCHAR" in ccy_col["type"]

    def test_no_changes_when_schema_matches(self) -> None:
        existing = {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                {"name": "name", "type": "VARCHAR(100)", "nullable": False},
                {
                    "name": "price_currency",
                    "type": "CHAR(3)",
                    "nullable": False,
                },
                {"name": "price", "type": "NUMERIC", "nullable": False},
            ],
            "indexes": [],
            "unique_together": [],
        }
        changes = detect_column_changes(CurrencyProduct, existing)
        assert changes == {}


class TestBuildTable:
    """build_table emits SQLAlchemy columns for both amount and currency."""

    def test_table_has_price_column(self) -> None:
        table = build_table("currency_product", CurrencyProduct)
        assert "price" in table.columns

    def test_table_has_price_currency_column(self) -> None:
        table = build_table("currency_product", CurrencyProduct)
        assert "price_currency" in table.columns

    def test_price_column_is_numeric(self) -> None:
        table = build_table("currency_product", CurrencyProduct)
        assert isinstance(table.columns["price"].type, Numeric)

    def test_price_currency_column_is_string(self) -> None:
        table = build_table("currency_product", CurrencyProduct)
        assert isinstance(table.columns["price_currency"].type, String)

    def test_multi_currency_table_has_four_extra_columns(self) -> None:
        table = build_table("multi_currency_product", MultiCurrencyProduct)
        assert "price" in table.columns
        assert "price_currency" in table.columns
        assert "cost" in table.columns
        assert "cost_currency" in table.columns


class TestMoneyArithmeticFromModel:
    """Money retrieved from a model supports arithmetic operations."""

    def test_sum_two_prices(self) -> None:
        p1 = CurrencyProduct(name="A", price=Money("10.00", "USD"))
        p2 = CurrencyProduct(name="B", price=Money("5.00", "USD"))
        total = p1.price + p2.price
        assert isinstance(total, Money)
        assert total.amount == Decimal("15.00")

    def test_multiply_price_by_scalar(self) -> None:
        product = CurrencyProduct(name="A", price=Money("10.00", "USD"))
        doubled = product.price * 2
        assert isinstance(doubled, Money)
        assert doubled.amount == Decimal("20.00")

    def test_subtract_prices(self) -> None:
        p1 = CurrencyProduct(name="A", price=Money("20.00", "USD"))
        p2 = CurrencyProduct(name="B", price=Money("7.00", "USD"))
        diff = p1.price - p2.price
        assert diff.amount == Decimal("13.00")

    def test_cross_currency_arithmetic_raises(self) -> None:
        p1 = CurrencyProduct(name="A", price=Money("10.00", "USD"))
        p2 = CurrencyProduct(name="B", price=Money("5.00", "EUR"))
        with pytest.raises(TypeError):
            p1.price + p2.price


class TestFromRow:
    """from_row hydrates a dict row into a Money instance."""

    def test_from_row_returns_money(self) -> None:
        row = {
            "id": 1,
            "name": "Widget",
            "price": Decimal("19.99"),
            "price_currency": "USD",
        }
        product = CurrencyProduct.from_row(row)
        assert isinstance(product.price, Money)
        assert product.price.amount == Decimal("19.99")
        assert product.price.currency.code == "USD"

    def test_from_row_fast_returns_money(self) -> None:
        row = {
            "id": 2,
            "name": "Gadget",
            "price": Decimal("50.00"),
            "price_currency": "EUR",
        }
        product = CurrencyProduct.from_row_fast(row)
        assert isinstance(product.price, Money)
        assert product.price.currency.code == "EUR"

    def test_from_row_null_amount(self) -> None:
        row = {
            "id": 3,
            "name": "Empty",
            "price": None,
            "price_currency": "USD",
        }
        product = CurrencyProduct.from_row(row)
        assert product.price is None


class TestToDbExtraction:
    """execute_save extracts the Decimal amount for the NUMERIC column."""

    def test_to_db_extracts_amount_from_money(self) -> None:
        field = CurrencyProduct._fields["price"]
        assert field.to_db(Money("19.99", "USD")) == Decimal("19.99")

    def test_to_db_extracts_amount_from_tuple(self) -> None:
        field = CurrencyProduct._fields["price"]
        assert field.to_db((Decimal("50.00"), "EUR")) == Decimal("50.00")

    def test_currency_code_to_db_uppercases(self) -> None:
        ccy_field = CurrencyProduct._fields["price_currency"]
        assert ccy_field.to_db("usd") == "USD"
