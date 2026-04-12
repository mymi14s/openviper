"""Unit tests for openviper.contrib.countries."""

from __future__ import annotations

import pytest

from openviper.contrib.countries import (
    CountryField,
    get_country_choices,
    get_country_name,
    get_dial_code,
    search_country,
    validate_country,
)
from openviper.contrib.countries.cache import get_countries, get_country, invalidate_cache
from openviper.contrib.countries.data import COUNTRIES, COUNTRY_CODES


class TestCountryData:
    """Verify the integrity of the ISO 3166-1 country dataset."""

    def test_country_codes_frozenset_immutable(self) -> None:
        assert isinstance(COUNTRY_CODES, frozenset)

    def test_country_codes_non_empty(self) -> None:
        assert len(COUNTRY_CODES) >= 200

    def test_all_codes_two_chars(self) -> None:
        for code in COUNTRY_CODES:
            assert len(code) == 2, f"code {code!r} is not 2 chars"
            assert code.isupper(), f"code {code!r} is not uppercase"

    def test_known_countries_present(self) -> None:
        for code in ("GB", "US", "NG", "DE", "FR", "JP", "AU", "BR", "CN", "IN"):
            assert code in COUNTRIES

    def test_country_info_has_required_keys(self) -> None:
        for code, info in COUNTRIES.items():
            assert "name" in info, f"{code}: missing 'name'"
            assert "dial_code" in info, f"{code}: missing 'dial_code'"
            assert info["name"], f"{code}: empty name"
            assert info["dial_code"].startswith("+"), f"{code}: dial_code missing '+'"

    def test_gb_country_entry(self) -> None:
        assert COUNTRIES["GB"]["name"] == "United Kingdom"
        assert COUNTRIES["GB"]["dial_code"] == "+44"

    def test_us_country_entry(self) -> None:
        assert COUNTRIES["US"]["name"] == "United States"
        assert COUNTRIES["US"]["dial_code"] == "+1"


class TestCountryCache:
    """Cache functions return expected data and are thread-safe."""

    def setup_method(self) -> None:
        invalidate_cache()

    def test_get_countries_returns_full_registry(self) -> None:
        countries = get_countries()
        assert "GB" in countries
        assert len(countries) >= 200

    def test_get_countries_with_extra_merges_correctly(self) -> None:
        extra = (("XA", "Atlantis", "+000"),)
        countries = get_countries(extra)
        assert "XA" in countries
        assert countries["XA"]["name"] == "Atlantis"
        assert countries["XA"]["dial_code"] == "+000"

    def test_get_countries_without_extra_returns_base(self) -> None:
        countries_no_extra = get_countries(())
        assert "XA" not in countries_no_extra

    def test_get_country_known_code(self) -> None:
        info = get_country("GB")
        assert info is not None
        assert info["name"] == "United Kingdom"

    def test_get_country_unknown_code(self) -> None:
        assert get_country("ZZ") is None

    def test_get_country_case_normalised(self) -> None:
        info = get_country("gb")
        assert info is not None
        assert info["name"] == "United Kingdom"

    def test_get_country_choices_returns_sorted_tuple(self) -> None:
        choices = get_country_choices()
        assert isinstance(choices, tuple)
        names = [c[1] for c in choices]
        assert names == sorted(names)

    def test_get_country_choices_contains_known_entries(self) -> None:
        codes = {c[0] for c in get_country_choices()}
        assert "GB" in codes
        assert "US" in codes

    def test_invalidate_then_refetch(self) -> None:
        get_countries()
        invalidate_cache()
        countries = get_countries()
        assert "GB" in countries


class TestValidateCountry:
    """validate_country enforces strict ISO alpha-2 rules."""

    def test_valid_code_gb(self) -> None:
        assert validate_country("GB") is True

    def test_valid_code_lowercase(self) -> None:
        assert validate_country("gb") is True

    def test_invalid_code_unknown(self) -> None:
        assert validate_country("ZZ") is False

    def test_invalid_code_too_long(self) -> None:
        assert validate_country("GBR") is False

    def test_invalid_code_numeric(self) -> None:
        assert validate_country("44") is False

    def test_invalid_code_empty(self) -> None:
        assert validate_country("") is False

    def test_invalid_code_sql_injection(self) -> None:
        assert validate_country("'; DROP TABLE users; --") is False

    def test_invalid_code_non_string(self) -> None:
        assert validate_country(None) is False  # type: ignore[arg-type]
        assert validate_country(44) is False  # type: ignore[arg-type]

    def test_extra_countries_accepted(self) -> None:
        extra = (("XA", "Atlantis", "+000"),)
        assert validate_country("XA", extra=extra) is True

    def test_strict_false_allows_non_alpha2(self) -> None:
        extra = (("X1", "Custom", "+001"),)
        assert validate_country("X1", extra=extra, strict=False) is True

    def test_strict_true_rejects_non_alpha2(self) -> None:
        assert validate_country("X1", strict=True) is False


class TestGetCountryName:
    """get_country_name returns names or None for unknown codes."""

    def test_known_code(self) -> None:
        assert get_country_name("GB") == "United Kingdom"

    def test_lowercase_input(self) -> None:
        assert get_country_name("gb") == "United Kingdom"

    def test_unknown_code(self) -> None:
        assert get_country_name("ZZ") is None

    def test_extra_country(self) -> None:
        extra = (("XA", "Atlantis", "+000"),)
        assert get_country_name("XA", extra=extra) == "Atlantis"


class TestGetDialCode:
    """get_dial_code returns dial codes or None for unknown codes."""

    def test_known_code(self) -> None:
        assert get_dial_code("GB") == "+44"

    def test_us_dial_code(self) -> None:
        assert get_dial_code("US") == "+1"

    def test_unknown_code(self) -> None:
        assert get_dial_code("ZZ") is None

    def test_extra_country_dial_code(self) -> None:
        extra = (("XA", "Atlantis", "+000"),)
        assert get_dial_code("XA", extra=extra) == "+000"


class TestSearchCountry:
    """search_country returns filtered, sorted results."""

    def test_partial_name_match(self) -> None:
        results = search_country("united")
        names = [r["name"] for r in results]
        assert any("United" in n for n in names)

    def test_exact_code_match(self) -> None:
        results = search_country("gb")
        assert any(r["code"] == "GB" for r in results)

    def test_sorted_by_name(self) -> None:
        results = search_country("island")
        names = [r["name"] for r in results]
        assert names == sorted(names)

    def test_no_match_returns_empty(self) -> None:
        assert search_country("xyzqwerty") == []

    def test_empty_query_returns_empty(self) -> None:
        assert search_country("") == []

    def test_none_query_returns_empty(self) -> None:
        assert search_country(None) == []  # type: ignore[arg-type]

    def test_result_has_all_keys(self) -> None:
        results = search_country("nigeria")
        assert results
        r = results[0]
        assert "code" in r
        assert "name" in r
        assert "dial_code" in r

    def test_extra_countries_searchable(self) -> None:
        extra = (("XA", "Atlantis", "+000"),)
        results = search_country("atlantis", extra=extra)
        assert results
        assert results[0]["code"] == "XA"


class TestCountryField:
    """CountryField ORM field validation and methods."""

    def test_default_max_length(self) -> None:
        field = CountryField()
        assert field.max_length == 2

    def test_column_type_includes_length(self) -> None:
        field = CountryField()
        assert field._column_type == "CHAR(2)"

    def test_column_type_respects_custom_max_length(self) -> None:
        field = CountryField(max_length=3, strict=False)
        assert field._column_type == "CHAR(3)"

    def test_to_python_uppercase(self) -> None:
        field = CountryField()
        assert field.to_python("gb") == "GB"

    def test_to_python_none(self) -> None:
        field = CountryField(null=True)
        assert field.to_python(None) is None

    def test_to_db_uppercase(self) -> None:
        field = CountryField()
        assert field.to_db("gb") == "GB"

    def test_validate_valid_code(self) -> None:
        field = CountryField()
        field.name = "country"
        field.validate("GB")

    def test_validate_lowercase_accepted(self) -> None:
        field = CountryField()
        field.name = "country"
        field.validate("gb")

    def test_validate_invalid_code_raises(self) -> None:
        field = CountryField()
        field.name = "country"
        with pytest.raises(ValueError, match="not a valid ISO"):
            field.validate("ZZ")

    def test_validate_long_string_raises(self) -> None:
        field = CountryField()
        field.name = "country"
        with pytest.raises(ValueError, match="exceeds maximum safe length"):
            field.validate("A" * 11)

    def test_validate_null_on_non_nullable_raises(self) -> None:
        field = CountryField()
        field.name = "country"
        with pytest.raises(ValueError, match="cannot be null"):
            field.validate(None)

    def test_validate_null_on_nullable_passes(self) -> None:
        field = CountryField(null=True)
        field.name = "country"
        field.validate(None)

    def test_validate_extra_countries(self) -> None:
        field = CountryField(extra_countries=(("XA", "Atlantis", "+000"),))
        field.name = "country"
        field.validate("XA")

    def test_get_choices_returns_sorted_tuples(self) -> None:
        field = CountryField()
        choices = field.get_choices()
        assert isinstance(choices, tuple)
        assert len(choices) >= 200
        names = [c[1] for c in choices]
        assert names == sorted(names)

    def test_get_country_name_method(self) -> None:
        field = CountryField()
        assert field.get_country_name("GB") == "United Kingdom"

    def test_get_country_name_none(self) -> None:
        field = CountryField()
        assert field.get_country_name(None) is None

    def test_search_method(self) -> None:
        field = CountryField()
        results = field.search("nigeria")
        assert any(r["code"] == "NG" for r in results)

    def test_to_representation_code_only(self) -> None:
        field = CountryField()
        assert field.to_representation("gb") == "GB"

    def test_to_representation_full(self) -> None:
        field = CountryField()
        result = field.to_representation("GB", full=True)
        assert isinstance(result, dict)
        assert result["code"] == "GB"
        assert result["name"] == "United Kingdom"
        assert result["dial_code"] == "+44"

    def test_to_representation_none(self) -> None:
        field = CountryField(null=True)
        assert field.to_representation(None) is None

    def test_to_representation_full_extra_country(self) -> None:
        field = CountryField(extra_countries=(("XA", "Atlantis", "+000"),))
        result = field.to_representation("XA", full=True)
        assert isinstance(result, dict)
        assert result["code"] == "XA"
        assert result["name"] == "Atlantis"
        assert result["dial_code"] == "+000"


class TestCountryFieldOpenAPISchema:
    """CountryField.openapi_schema() produces valid OpenAPI fragments."""

    def test_schema_type_string(self) -> None:
        schema = CountryField.openapi_schema()
        assert schema["type"] == "string"

    def test_schema_has_enum(self) -> None:
        schema = CountryField.openapi_schema()
        assert "enum" in schema
        assert "GB" in schema["enum"]
        assert "US" in schema["enum"]

    def test_schema_enum_sorted(self) -> None:
        schema = CountryField.openapi_schema()
        assert schema["enum"] == sorted(schema["enum"])

    def test_schema_has_pattern(self) -> None:
        schema = CountryField.openapi_schema()
        assert schema["pattern"] == "^[A-Z]{2}$"

    def test_schema_has_description(self) -> None:
        schema = CountryField.openapi_schema()
        assert "description" in schema

    def test_schema_extra_codes_included(self) -> None:
        extra = (("XA", "Atlantis", "+000"),)
        schema = CountryField.openapi_schema(extra_countries=extra)
        assert "XA" in schema["enum"]

    def test_schema_no_unknown_codes(self) -> None:
        schema = CountryField.openapi_schema()
        assert "ZZ" not in schema["enum"]


class TestCountryFieldPerformance:
    """CountryField and cache lookups operate within expected complexity."""

    def test_validate_runs_without_error_for_all_codes(self) -> None:
        field = CountryField()
        field.name = "country"
        for code in COUNTRY_CODES:
            field.validate(code)

    def test_validate_country_all_codes(self) -> None:
        for code in COUNTRY_CODES:
            assert validate_country(code) is True

    def test_choices_count_matches_registry(self) -> None:
        choices = get_country_choices()
        invalidate_cache()
        assert len(choices) == len(COUNTRIES)
