"""Tests for admin API field-level validation error mapping."""

from __future__ import annotations

from openviper.admin.api.views import parse_validation_errors


class TestParseValidationErrors:
    """parse_validation_errors maps aggregate errors to field keys."""

    def test_single_field_error(self) -> None:
        msg = (
            "Validation failed for Product: "
            "Field 'price': value has 3 decimal places, exceeds decimal_places=2"
        )
        result = parse_validation_errors(msg, {"price", "name"})
        assert "price" in result
        assert "decimal_places" in result["price"]

    def test_multiple_field_errors(self) -> None:
        msg = (
            "Validation failed for Product: "
            "Field 'price': value has 3 decimal places, exceeds decimal_places=2; "
            "Field 'name' cannot be null."
        )
        result = parse_validation_errors(msg, {"price", "name"})
        assert "price" in result
        assert "name" in result
        assert "decimal_places" in result["price"]
        assert "null" in result["name"]

    def test_no_matching_fields_returns_empty(self) -> None:
        msg = "Validation failed for Product: Some unknown error"
        result = parse_validation_errors(msg, {"price", "name"})
        assert result == {}

    def test_empty_field_names_returns_empty(self) -> None:
        msg = "Validation failed for Product: Field 'price': bad"
        result = parse_validation_errors(msg, set())
        assert result == {}

    def test_non_validation_message_returns_empty(self) -> None:
        msg = "Some random error"
        result = parse_validation_errors(msg, {"price"})
        assert result == {}

    def test_currency_precision_error_parsed(self) -> None:
        msg = (
            "Validation failed for Order: "
            "Field 'amount': value has 5 decimal places, exceeds decimal_places=2"
        )
        result = parse_validation_errors(msg, {"amount", "id"})
        assert "amount" in result
        assert "exceeds decimal_places=2" in result["amount"]
