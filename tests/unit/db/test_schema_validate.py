"""Unit tests for type change validation."""

from __future__ import annotations

import warnings

import pytest

from openviper.db.schemas.validate import (
    is_narrowing,
    normalize_type,
    validate_type_change,
)
from openviper.exceptions import MigrationError


class TestNormalizeType:
    """Tests for normalize_type function."""

    def test_strips_length_suffix(self) -> None:
        assert normalize_type("VARCHAR(255)") == "VARCHAR"

    def test_uppercases(self) -> None:
        assert normalize_type("integer") == "INTEGER"

    def test_no_suffix(self) -> None:
        assert normalize_type("TEXT") == "TEXT"

    def test_complex_type(self) -> None:
        assert normalize_type("DOUBLE PRECISION") == "DOUBLE"


class TestIsNarrowing:
    """Tests for is_narrowing function."""

    def test_varchar_length_narrowing(self) -> None:
        assert is_narrowing("VARCHAR(200)", "VARCHAR(50)") is True

    def test_varchar_length_widening(self) -> None:
        assert is_narrowing("VARCHAR(50)", "VARCHAR(200)") is False

    def test_text_to_varchar_is_narrowing(self) -> None:
        assert is_narrowing("TEXT", "VARCHAR(100)") is True

    def test_same_length_not_narrowing(self) -> None:
        assert is_narrowing("VARCHAR(100)", "VARCHAR(100)") is False

    def test_different_types_not_narrowing(self) -> None:
        assert is_narrowing("INTEGER", "VARCHAR(255)") is False


class TestValidateTypeChange:
    """Tests for validate_type_change function."""

    def test_safe_widening_passes(self) -> None:
        validate_type_change("VARCHAR(50)", "VARCHAR(200)")

    def test_integer_to_string_raises(self) -> None:
        with pytest.raises(MigrationError, match="Cannot change column type"):
            validate_type_change("INTEGER", "VARCHAR(255)")

    def test_string_to_integer_raises(self) -> None:
        with pytest.raises(MigrationError, match="Cannot change column type"):
            validate_type_change("VARCHAR(255)", "INTEGER")

    def test_datetime_to_date_raises(self) -> None:
        with pytest.raises(MigrationError, match="Cannot change column type"):
            validate_type_change("DATETIME", "DATE")

    def test_float_to_integer_raises(self) -> None:
        with pytest.raises(MigrationError, match="Cannot change column type"):
            validate_type_change("FLOAT", "INTEGER")

    def test_force_bypasses_incompatible_check(self) -> None:
        validate_type_change("INTEGER", "VARCHAR(255)", force=True)

    def test_narrowing_warns(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_type_change("VARCHAR(200)", "VARCHAR(50)")
            assert len(w) == 1
            assert "narrowing" in str(w[0].message)

    def test_safe_change_no_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_type_change("VARCHAR(50)", "VARCHAR(200)")
            assert len(w) == 0

    def test_date_to_datetime_allowed(self) -> None:
        validate_type_change("DATE", "DATETIME")

    def test_integer_to_float_allowed(self) -> None:
        validate_type_change("INTEGER", "FLOAT")
