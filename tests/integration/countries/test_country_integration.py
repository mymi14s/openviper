"""Integration tests for CountryField — model, serializer, and OpenAPI."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from openviper.contrib.countries import CountryField
from openviper.contrib.countries.cache import get_countries, invalidate_cache
from openviper.contrib.countries.data import COUNTRIES
from openviper.db.fields import CharField

if TYPE_CHECKING:
    from openviper.contrib.countries.field import _EXTRA_COUNTRIES_TYPE


class TestCountryFieldInheritance:
    """CountryField is a proper CharField subclass compatible with the ORM."""

    def test_is_charfield_subclass(self) -> None:
        field = CountryField()
        assert isinstance(field, CharField)

    def test_column_type_is_char(self) -> None:
        field = CountryField()
        assert field._column_type == "CHAR(2)"

    def test_field_name_assigned(self) -> None:
        field = CountryField()
        field.name = "country"
        assert field.name == "country"

    def test_field_null_kwarg(self) -> None:
        field = CountryField(null=True)
        assert field.null is True

    def test_field_db_index_kwarg(self) -> None:
        field = CountryField(db_index=True)
        assert field.db_index is True

    def test_field_unique_kwarg(self) -> None:
        field = CountryField(unique=True)
        assert field.unique is True

    def test_field_default_kwarg(self) -> None:
        field = CountryField(default="US")
        assert field.default == "US"


class TestCountryFieldModelIntegration:
    """CountryField behaves correctly when attached to a Model-like object."""

    def _make_model_instance(self, field: CountryField, code: str | None) -> MagicMock:
        instance = MagicMock()
        instance.country = code
        return instance

    def test_field_to_python_round_trip(self) -> None:
        field = CountryField()
        for code in ("GB", "US", "NG", "DE"):
            assert field.to_python(code) == code
            assert field.to_python(code.lower()) == code

    def test_field_to_db_normalises(self) -> None:
        field = CountryField()
        assert field.to_db("gb") == "GB"
        assert field.to_db("us") == "US"

    def test_validate_rejects_sql_injection(self) -> None:
        field = CountryField()
        field.name = "country"
        dangerous_inputs = [
            "'; DROP TABLE users; --",
            "<script>alert(1)</script>",
            "' OR '1'='1",
            "\\x00",
        ]
        for payload in dangerous_inputs:
            with pytest.raises(ValueError, match="Country code|is not a valid ISO|max_length"):
                field.validate(payload)

    def test_validate_rejects_oversized_input(self) -> None:
        field = CountryField()
        field.name = "country"
        with pytest.raises(ValueError, match="Country code exceeds maximum safe length"):
            field.validate("A" * 100)

    def test_all_iso_codes_pass_validation(self) -> None:
        field = CountryField()
        field.name = "country"
        for code in list(COUNTRIES.keys())[:30]:
            field.validate(code)


class TestCountryFieldWithExtraCountries:
    """Extra countries are merged cleanly and do not pollute the base dataset."""

    def setup_method(self) -> None:
        invalidate_cache()

    def test_extra_country_validated(self) -> None:
        extra: _EXTRA_COUNTRIES_TYPE = (("XA", "Atlantis", "+000"),)
        field = CountryField(extra_countries=extra)
        field.name = "country"
        field.validate("XA")

    def test_extra_country_in_choices(self) -> None:
        extra: _EXTRA_COUNTRIES_TYPE = (("XB", "Hyperion", "+001"),)
        field = CountryField(extra_countries=extra)
        choices = field.get_choices()
        codes = {c[0] for c in choices}
        assert "XB" in codes

    def test_base_dataset_unchanged_after_extra(self) -> None:
        extra: _EXTRA_COUNTRIES_TYPE = (("XA", "Atlantis", "+000"),)
        field_with_extra = CountryField(extra_countries=extra)  # noqa: F841
        base_countries = get_countries(())
        assert "XA" not in base_countries

    def test_extra_code_not_valid_for_plain_field(self) -> None:
        field_plain = CountryField()
        field_plain.name = "country"
        with pytest.raises(ValueError, match="is not a valid ISO"):
            field_plain.validate("XA")


class TestCountryFieldSerializer:
    """to_representation() produces correct output for serializers."""

    def test_code_only_output(self) -> None:
        field = CountryField()
        assert field.to_representation("gb") == "GB"

    def test_full_object_output(self) -> None:
        field = CountryField()
        result = field.to_representation("GB", full=True)
        assert result == {
            "code": "GB",
            "name": "United Kingdom",
            "dial_code": "+44",
        }

    def test_full_object_us(self) -> None:
        field = CountryField()
        result = field.to_representation("US", full=True)
        assert result["code"] == "US"
        assert result["name"] == "United States"
        assert result["dial_code"] == "+1"

    def test_none_returns_none(self) -> None:
        field = CountryField(null=True)
        assert field.to_representation(None) is None
        assert field.to_representation(None, full=True) is None

    def test_full_output_all_codes(self) -> None:
        field = CountryField()
        for code in list(COUNTRIES.keys())[:10]:
            result = field.to_representation(code, full=True)
            assert isinstance(result, dict)
            assert result["code"] == code


class TestCountryFieldOpenAPIIntegration:
    """OpenAPI schema generation integrates with existing schema machinery."""

    def test_openapi_schema_has_enum(self) -> None:
        schema = CountryField.openapi_schema()
        assert isinstance(schema["enum"], list)
        assert len(schema["enum"]) >= 200

    def test_openapi_schema_all_enum_values_uppercase(self) -> None:
        schema = CountryField.openapi_schema()
        for code in schema["enum"]:
            assert code.isupper(), f"{code!r} is not uppercase"

    def test_openapi_schema_all_enum_two_chars(self) -> None:
        schema = CountryField.openapi_schema()
        for code in schema["enum"]:
            assert len(code) == 2, f"{code!r} is not 2 chars"

    def test_openapi_schema_extra_codes_in_enum(self) -> None:
        extra: _EXTRA_COUNTRIES_TYPE = (("XA", "Atlantis", "+000"),)
        schema = CountryField.openapi_schema(extra_countries=extra)
        assert "XA" in schema["enum"]

    def test_openapi_schema_structure(self) -> None:
        schema = CountryField.openapi_schema()
        assert schema["type"] == "string"
        assert schema["pattern"] == "^[A-Z]{2}$"
        assert "description" in schema
        assert "example" in schema


class TestCountryFieldORMFiltering:
    """CountryField values are safe for use as ORM filter arguments."""

    def test_to_db_gb(self) -> None:
        field = CountryField()
        assert field.to_db("GB") == "GB"

    def test_to_db_lowercase_normalised(self) -> None:
        field = CountryField()
        assert field.to_db("gb") == "GB"

    def test_to_db_none(self) -> None:
        field = CountryField(null=True)
        assert field.to_db(None) is None

    def test_filter_value_matches_stored_value(self) -> None:
        field = CountryField()
        stored = field.to_db("gb")
        filter_val = field.to_db("GB")
        assert stored == filter_val

    def test_repr_contains_class_name(self) -> None:
        field = CountryField()
        field.name = "country"
        assert "CountryField" in repr(field)


class TestSettingsIntegration:
    """COUNTRY_FIELD setting is accessible and has correct defaults."""

    def test_country_field_setting_exists(self) -> None:
        from openviper.conf import settings

        cfg = getattr(settings, "COUNTRY_FIELD", None)
        assert cfg is not None

    def test_country_field_setting_defaults(self) -> None:
        from openviper.conf import settings

        cfg = settings.COUNTRY_FIELD
        assert cfg["ENABLE_CACHE"] is True
        assert cfg["STRICT"] is True
        assert isinstance(cfg["EXTRA_COUNTRIES"], dict)
