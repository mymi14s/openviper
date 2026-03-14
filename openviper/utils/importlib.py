from importlib import import_module
from typing import Any

# Cache for imported classes/functions to avoid repeated imports
_IMPORT_CACHE: dict[str, Any] = {}


def reset_import_cache() -> None:
    """Clear the import cache. Primarily for tests or dynamic imports."""
    _IMPORT_CACHE.clear()


def import_string(dotted_path: str) -> Any:
    """Import a class or function from a string path.

    Results are cached to avoid repeated imports of the same path.
    Failed imports are NOT cached so that transient sys.path issues
    (e.g. early startup calls before app directories are on sys.path)
    do not permanently poison the cache.

    Args:
        dotted_path: Dotted path to the class/function (e.g., "myapp.views.MyView")

    Returns:
        The imported class or function

    Example:
        >>> MyView = import_string("myapp.views.MyView")
    """
    if dotted_path in _IMPORT_CACHE:
        return _IMPORT_CACHE[dotted_path]
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = import_module(module_path)
    result = getattr(module, class_name)
    _IMPORT_CACHE[dotted_path] = result
    return result
