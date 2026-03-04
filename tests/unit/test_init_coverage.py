"""Coverage for openviper/__init__.py – PEP 562 lazy loader and setup()."""

from __future__ import annotations

import pytest


def test_lazy_getattr_loads_known_subpackage():
    """openviper.__getattr__ lazily imports a known subpackage and caches it."""
    import openviper

    tasks_module = openviper.__getattr__("tasks")
    import openviper.tasks

    assert tasks_module is openviper.tasks


def test_lazy_getattr_unknown_raises_attribute_error():
    """openviper.__getattr__ raises AttributeError for unknown attribute names."""
    import openviper

    with pytest.raises(AttributeError, match="has no attribute"):
        openviper.__getattr__("_nonexistent_subpackage_xyz")


def test_setup_runs_without_error():
    """openviper.setup() calls settings._setup() without raising."""
    import openviper

    # Should not raise even when called repeatedly (force=False is idempotent)
    openviper.setup(force=False)
