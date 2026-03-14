"""App resolver for flexible app directory structure.

Resolves app locations from INSTALLED_APPS, supporting apps anywhere in
the project structure.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Global cache for recursive search results to avoid repeated os.walk calls.
# Bounded to prevent unbounded memory growth in long-running processes.
_SEARCH_PATTERN_CACHE_MAX = 256
_SEARCH_PATTERN_CACHE: dict[tuple[str, str], str | None] = {}


class AppResolver:
    """Resolve app locations from INSTALLED_APPS.

    Supports multiple app naming patterns:
    - Simple name: "blog" (searches standard locations)
    - Relative path: "apps.blog"
    - Full module path: "myproject.apps.blog"
    """

    # Color codes for terminal output
    COLORS = {
        "GREEN": "\033[92m",
        "RED": "\033[91m",
        "YELLOW": "\033[93m",
        "BLUE": "\033[94m",
        "END": "\033[0m",
    }

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
        # Check cache
        if app_name in self.app_cache:
            return self.app_cache[app_name]

        # Try different resolution strategies
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

        # Not found
        self.app_cache[app_name] = (None, False)
        return None, False

    def _try_direct_path(self, app_name: str) -> str | None:
        """Try direct path resolution.

        Args:
            app_name: App name

        Returns:
            Path if found, None otherwise
        """
        # Try as-is first (for root-level apps)
        direct_path = os.path.join(self.project_root, app_name)
        if self._is_valid_app_directory(direct_path):
            return direct_path

        # Convert dots to slashes (apps.blog -> apps/blog)
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
        # Extract base app name
        base_name = app_name.split(".")[-1]

        # Search in common locations
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

        # Check global cache first
        cache_key = (self.project_root, base_name)
        if cache_key in _SEARCH_PATTERN_CACHE:
            return _SEARCH_PATTERN_CACHE[cache_key]

        # Search recursively in project root
        result = None
        for root, dirs, _files in os.walk(self.project_root):
            # Skip hidden directories and common excludes
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

        # Cache the result (even if None); evict oldest entry if at capacity.
        if len(_SEARCH_PATTERN_CACHE) >= _SEARCH_PATTERN_CACHE_MAX:
            _SEARCH_PATTERN_CACHE.pop(next(iter(_SEARCH_PATTERN_CACHE)))
        _SEARCH_PATTERN_CACHE[cache_key] = result
        return result

    @staticmethod
    def _is_valid_app_directory(path: str) -> bool:
        """Check if directory is a valid OpenViper app.

        Args:
            path: Directory path

        Returns:
            True if valid app directory
        """
        if not os.path.isdir(path):
            return False

        # Check for models.py or routes.py (indicates app)
        models_exists = os.path.exists(os.path.join(path, "models.py"))
        routes_exists = os.path.exists(os.path.join(path, "routes.py"))
        migrations_exists = os.path.isdir(os.path.join(path, "migrations"))
        init_exists = os.path.exists(os.path.join(path, "__init__.py"))

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
            # Skip openviper contrib apps unless explicitly allowed
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

        # Create if doesn't exist
        if not os.path.exists(migrations_dir):
            os.makedirs(migrations_dir)
            # Create __init__.py
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

        print(f"\n{self.COLORS['BLUE']}App Locations:{self.COLORS['END']}\n")

        found = resolved.get("found", {})
        if isinstance(found, dict):
            for app_name, app_path in found.items():
                rel_path = os.path.relpath(app_path, self.project_root)
                print(f"  {self.COLORS['GREEN']}✓{self.COLORS['END']} {app_name}: {rel_path}")

        not_found = resolved.get("not_found", [])
        if not_found:
            print(f"\n{self.COLORS['RED']}Not Found:{self.COLORS['END']}\n")
            for app_name in not_found:
                print(f"  {self.COLORS['RED']}✗{self.COLORS['END']} {app_name}")

        print()

    @staticmethod
    def print_app_not_found_error(app_name: str, search_paths: list[str]) -> None:
        """Print app not found error message.

        Args:
            app_name: App name that wasn't found
            search_paths: Paths that were searched
        """
        COLORS = {"RED": "\033[91m", "END": "\033[0m"}  # noqa: N806

        print(f"\n{COLORS['RED']}")
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
        print(f"{COLORS['END']}\n")

    @staticmethod
    def print_app_not_in_settings_error(app_name: str, app_path: str) -> None:
        """Print app found but not in settings error.

        Args:
            app_name: App name
            app_path: Path where app was found
        """
        COLORS = {"RED": "\033[91m", "END": "\033[0m"}  # noqa: N806

        print(f"\n{COLORS['RED']}")
        print("=" * 70)
        print(f"ERROR: App '{app_name}' exists but not in INSTALLED_APPS")
        print("=" * 70)
        print(f"\nApp directory found: {app_path}")
        print("\nTo use this app, add it to INSTALLED_APPS in settings.py:\n")
        print("INSTALLED_APPS = [")
        print('    "openviper.contrib.auth",')
        print(f'    "{app_name}",  # Add this line')
        print("]")
        print("\nFor more help, visit: https://openviper.dev/docs/apps")
        print(f"{COLORS['END']}\n")
