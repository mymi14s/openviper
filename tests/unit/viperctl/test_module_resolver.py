"""Tests for openviper.utils.module_resolver."""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from openviper.utils.module_resolver import ResolvedModule, resolve_target


class TestResolveTargetRoot:
    """Tests for resolve_target with '.' (CWD-as-app)."""

    def test_root_with_models(self, tmp_path: Path) -> None:
        """'.' resolves when models.py exists in CWD."""
        (tmp_path / "models.py").write_text("# models\n")

        result = resolve_target(".", cwd=tmp_path)

        assert result.app_label == tmp_path.name
        assert result.app_path == tmp_path
        assert result.is_root is True
        assert result.models_module == f"{tmp_path.name}.models"

    def test_root_with_routes(self, tmp_path: Path) -> None:
        """'.' resolves when routes.py exists (no models.py needed)."""
        (tmp_path / "routes.py").write_text("# routes\n")

        result = resolve_target(".", cwd=tmp_path)

        assert result.is_root is True
        assert result.app_label == tmp_path.name

    def test_root_without_models_or_routes_raises(self, tmp_path: Path) -> None:
        """'.' raises ClickException when CWD lacks models.py and routes.py."""
        with pytest.raises(click.ClickException, match="neither models.py nor routes.py"):
            resolve_target(".", cwd=tmp_path)

    def test_root_invalid_identifier_raises(self, tmp_path: Path) -> None:
        """'.' raises when CWD name is not a valid Python identifier."""
        bad_dir = tmp_path / "123-invalid"
        bad_dir.mkdir()
        (bad_dir / "models.py").write_text("# models\n")

        with pytest.raises(click.ClickException, match="not a valid Python identifier"):
            resolve_target(".", cwd=bad_dir)


class TestResolveTargetModule:
    """Tests for resolve_target with a named module."""

    def test_module_with_models(self, tmp_path: Path) -> None:
        """Named module resolves when models.py exists."""
        todo = tmp_path / "todo"
        todo.mkdir()
        (todo / "models.py").write_text("# models\n")

        result = resolve_target("todo", cwd=tmp_path)

        assert result.app_label == "todo"
        assert result.app_path == todo
        assert result.is_root is False
        assert result.models_module == "todo.models"

    def test_module_with_routes(self, tmp_path: Path) -> None:
        """Named module resolves when routes.py exists."""
        api = tmp_path / "api"
        api.mkdir()
        (api / "routes.py").write_text("# routes\n")

        result = resolve_target("api", cwd=tmp_path)

        assert result.app_label == "api"
        assert result.is_root is False

    def test_module_not_found_raises(self, tmp_path: Path) -> None:
        """Raises ClickException when module directory does not exist."""
        with pytest.raises(click.ClickException, match="not found"):
            resolve_target("nonexistent", cwd=tmp_path)

    def test_module_without_models_or_routes_raises(self, tmp_path: Path) -> None:
        """Raises when module directory has no models.py or routes.py."""
        empty = tmp_path / "empty"
        empty.mkdir()

        with pytest.raises(click.ClickException, match="neither models.py nor routes.py"):
            resolve_target("empty", cwd=tmp_path)


class TestResolvedModuleDataclass:
    """Tests for the ResolvedModule dataclass."""

    def test_frozen(self) -> None:
        """ResolvedModule is immutable."""
        rm = ResolvedModule(
            app_label="test",
            app_path=Path("/tmp/test"),
            is_root=False,
            models_module="test.models",
        )
        with pytest.raises(AttributeError):
            rm.app_label = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        """Two ResolvedModules with the same fields are equal."""
        a = ResolvedModule(
            app_label="x",
            app_path=Path("/a"),
            is_root=True,
            models_module="x.models",
        )
        b = ResolvedModule(
            app_label="x",
            app_path=Path("/a"),
            is_root=True,
            models_module="x.models",
        )
        assert a == b
