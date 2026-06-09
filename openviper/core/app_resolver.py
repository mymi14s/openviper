"""App resolver for flexible app directory structure.

Resolves app locations from INSTALLED_APPS, supporting apps anywhere in
the project structure.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Bounded LRU cache avoids repeated os.walk calls in long-running processes.
_SEARCH_PATTERN_CACHE_MAX = 256
_SEARCH_PATTERN_CACHE: dict[tuple[str, str], str | None] = {}
_CACHE_LOCK = threading.Lock()

_ANSI_GREEN = "\033[92m"
_ANSI_RED = "\033[91m"
_ANSI_BLUE = "\033[94m"
_ANSI_END = "\033[0m"


class AppResolver:
    """Resolve app locations from INSTALLED_APPS.

    Supports multiple app naming patterns:
    - Simple name: "blog" (searches standard locations)
    - Relative path: "apps.blog"
    - Full module path: "myproject.apps.blog"
    """

    def __init__(self, project_root: str | None = None):
        """Initialize app resolver.

        Args:
            project_root: Project root directory (default: current directory)
        """
        self.project_root = project_root or self._get_project_root()
        self.app_cache: dict[str, tuple[str | None, bool]] = {}

    @staticmethod
    def _get_project_root() -> str:
        """Get project root directory."""
        return os.getcwd()

    def resolve_app(self, app_name: str) -> tuple[str | None, bool]:
        """Resolve app location.

        Args:
            app_name: App name (e.g., "blog", "apps.blog")

        Returns:
            Tuple of (app_path, found)
        """
        if app_name in self.app_cache:
            return self.app_cache[app_name]

        app_path = self._try_direct_path(app_name)
        if app_path:
            self.app_cache[app_name] = (app_path, True)
            return app_path, True

        app_path = self._try_relative_path(app_name)
        if app_path:
            self.app_cache[app_name] = (app_path, True)
            return app_path, True

        app_path = self._try_search_patterns(app_name)
        if app_path:
            self.app_cache[app_name] = (app_path, True)
            return app_path, True

        self.app_cache[app_name] = (None, False)
        return None, False

    def _try_direct_path(self, app_name: str) -> str | None:
        """Try direct path resolution.

        Args:
            app_name: App name

        Returns:
            Path if found, None otherwise
        """
        if ".." in app_name or app_name.startswith("/") or app_name.startswith("\\"):
            return None

        direct_path = os.path.join(self.project_root, app_name)
        if self._is_valid_app_directory(direct_path):
            return direct_path

        if "." in app_name:
            converted = app_name.replace(".", "/")
            converted_path = os.path.join(self.project_root, converted)
            if self._is_valid_app_directory(converted_path):
                return converted_path

        return None

    def _try_relative_path(self, app_name: str) -> str | None:
        """Try relative path resolution.

        Args:
            app_name: App name

        Returns:
            Path if found, None otherwise
        """
        base_name = app_name.split(".")[-1]

        search_dirs = [
            "apps",
            "src",
            "modules",
            "services",
            "api",
            "core",
        ]

        for search_dir in search_dirs:
            app_path = os.path.join(self.project_root, search_dir, base_name)
            if self._is_valid_app_directory(app_path):
                return app_path

        return None

    def _try_search_patterns(self, app_name: str) -> str | None:
        """Try fuzzy search patterns.

        Uses a global cache to avoid repeated os.walk calls which are expensive.

        Args:
            app_name: App name

        Returns:
            Path if found, None otherwise
        """
        base_name = app_name.split(".")[-1]

        cache_key = (self.project_root, base_name)
        with _CACHE_LOCK:
            if cache_key in _SEARCH_PATTERN_CACHE:
                return _SEARCH_PATTERN_CACHE[cache_key]

        result = None
        for root, dirs, _files in os.walk(self.project_root):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d
                not in [
                    "__pycache__",
                    "venv",
                    ".venv",
                    "env",
                    "node_modules",
                    "build",
                    "dist",
                ]
            ]

            if base_name in dirs:
                app_path = os.path.join(root, base_name)
                if self._is_valid_app_directory(app_path):
                    result = app_path
                    break

        with _CACHE_LOCK:
            if len(_SEARCH_PATTERN_CACHE) >= _SEARCH_PATTERN_CACHE_MAX:
                _SEARCH_PATTERN_CACHE.pop(next(iter(_SEARCH_PATTERN_CACHE)))
            _SEARCH_PATTERN_CACHE[cache_key] = result
        return result

    @staticmethod
    def _is_valid_app_directory(path: str) -> bool:
        """Check if directory is a valid OpenViper app.

        Resolves symlinks to prevent traversal through symbolic links.

        Args:
            path: Directory path

        Returns:
            True if valid app directory
        """
        resolved = os.path.realpath(path)
        if not os.path.isdir(resolved):
            return False

        models_exists = os.path.exists(os.path.join(resolved, "models.py"))
        routes_exists = os.path.exists(os.path.join(resolved, "routes.py"))
        migrations_exists = os.path.isdir(os.path.join(resolved, "migrations"))
        init_exists = os.path.exists(os.path.join(resolved, "__init__.py"))

        return (models_exists or routes_exists or migrations_exists) and init_exists

    def resolve_all_apps(
        self, installed_apps: list[str], include_builtin: bool = False
    ) -> dict[str, dict[str, str] | list[str]]:
        """Resolve all installed apps.

        Args:
            installed_apps: List from settings.INSTALLED_APPS
            include_builtin: Whether to include openviper.* apps (default: False)

        Returns:
            Dict with 'found' and 'not_found' keys
        """
        resolved: dict[str, str] = {}
        not_found: list[str] = []

        for app_name in installed_apps:
            if app_name.startswith("openviper.") and not include_builtin:
                continue

            app_path, found = self.resolve_app(app_name)

            if found and app_path:
                resolved[app_name] = app_path
            else:
                not_found.append(app_name)

        return {"found": resolved, "not_found": not_found}

    def get_migrations_dir(self, app_name: str) -> str | None:
        """Get migrations directory for app.

        Args:
            app_name: App name

        Returns:
            Path to migrations directory
        """
        app_path, found = self.resolve_app(app_name)

        if not found or app_path is None:
            return None

        migrations_dir = os.path.join(app_path, "migrations")

        if not os.path.exists(migrations_dir):
            os.makedirs(migrations_dir)

            init_file = os.path.join(migrations_dir, "__init__.py")
            if not os.path.exists(init_file):
                Path(init_file).touch()

        return migrations_dir

    def print_app_locations(self, installed_apps: list[str]) -> None:
        """Print app locations for debugging.

        Args:
            installed_apps: List from settings.INSTALLED_APPS
        """
        resolved = self.resolve_all_apps(installed_apps)

        print(f"\n{_ANSI_BLUE}App Locations:{_ANSI_END}\n")

        found = resolved.get("found", {})
        if isinstance(found, dict):
            for app_name, app_path in found.items():
                rel_path = os.path.relpath(app_path, self.project_root)
                print(f"  {_ANSI_GREEN}✓{_ANSI_END} {app_name}: {rel_path}")

        not_found = resolved.get("not_found", [])
        if not_found:
            print(f"\n{_ANSI_RED}Not Found:{_ANSI_END}\n")
            for app_name in not_found:
                print(f"  {_ANSI_RED}✗{_ANSI_END} {app_name}")

        print()

    @staticmethod
    def print_app_not_found_error(app_name: str, search_paths: list[str]) -> None:
        """Print app not found error message.

        Args:
            app_name: App name that wasn't found
            search_paths: Paths that were searched
        """
        print(f"\n{_ANSI_RED}")
        print("=" * 70)
        print(f"ERROR: App '{app_name}' not found")
        print("=" * 70)
        print(f"\nThe app '{app_name}' was not found in your project.")
        print("\nPossible solutions:\n")
        print("1. Check if app exists in one of these locations:")
        for path in search_paths:
            print(f"   - {path}")
        print("\n2. Add app to INSTALLED_APPS in settings.py:")
        print(f'   INSTALLED_APPS = [\n       "{app_name}",\n   ]')
        print("\n3. Verify app has required structure:")
        print(f"   {app_name}/")
        print("   ├── __init__.py")
        print("   ├── models.py (or routes.py)")
        print("   └── migrations/ (optional)\n")
        print("For more help, visit: https://openviper.dev/docs/apps")
        print(f"{_ANSI_END}\n")

    @staticmethod
    def print_app_not_in_settings_error(app_name: str, app_path: str) -> None:
        """Print app found but not in settings error.

        Args:
            app_name: App name
            app_path: Path where app was found
        """
        print(f"\n{_ANSI_RED}")
        print("=" * 70)
        print(f"ERROR: App '{app_name}' exists but not in INSTALLED_APPS")
        print("=" * 70)
        print(f"\nApp directory found: {app_path}")
        print("\nTo use this app, add it to INSTALLED_APPS in settings.py:\n")
        print("INSTALLED_APPS = [")
        print('    "openviper.contrib.auth",')
        print(f'    "{app_name}",')
        print("]")
        print("\nFor more help, visit: https://openviper.dev/docs/apps")
        print(f"{_ANSI_END}\n")
