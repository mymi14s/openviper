"""Pytest plugin entry point for OpenViper TestKit."""

import typing as t

if t.TYPE_CHECKING:
    import pytest

pytest_plugins = ["openviper.testing.fixtures"]

MARKERS: tuple[tuple[str, str], ...] = (
    ("openviper", "Marks a test as using OpenViper testing features."),
    ("db", "Marks a test as requiring database access."),
    ("transactional_db", "Marks a test as requiring real transaction behavior."),
    ("integration", "Marks a broader integration test."),
    ("slow", "Marks a slow test."),
    ("admin", "Marks an Admin UI test."),
    ("openapi", "Marks an OpenAPI schema test."),
    ("auth", "Marks an authentication or authorization test."),
)


def pytest_configure(config: pytest.Config) -> None:
    for name, description in MARKERS:
        config.addinivalue_line("markers", f"{name}: {description}")
