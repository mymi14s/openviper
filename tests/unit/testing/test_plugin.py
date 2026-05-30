"""Tests for the OpenViper pytest plugin registration."""

from __future__ import annotations

from openviper.testing.plugin import MARKERS


def test_all_required_markers_are_declared() -> None:
    marker_names = {name for name, _ in MARKERS}
    required = {
        "openviper",
        "db",
        "transactional_db",
        "integration",
        "slow",
        "admin",
        "openapi",
        "auth",
    }

    assert marker_names == required


def test_every_marker_has_a_non_empty_description() -> None:
    for name, description in MARKERS:
        assert description.strip(), f"Marker {name!r} has an empty description."


def test_marker_names_contain_no_spaces() -> None:
    for name, _ in MARKERS:
        assert " " not in name, f"Marker name {name!r} must not contain spaces."


def test_markers_tuple_is_immutable() -> None:
    assert isinstance(MARKERS, tuple)


def test_db_marker_is_declared() -> None:
    names = {name for name, _ in MARKERS}
    assert "db" in names


def test_transactional_db_marker_is_declared() -> None:
    names = {name for name, _ in MARKERS}
    assert "transactional_db" in names


def test_auth_marker_is_declared() -> None:
    names = {name for name, _ in MARKERS}
    assert "auth" in names


def test_openapi_marker_is_declared() -> None:
    names = {name for name, _ in MARKERS}
    assert "openapi" in names
