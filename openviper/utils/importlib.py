import importlib
import typing as t
from typing import cast

IMPORT_CACHE: dict[str, t.Callable[..., object]] = {}

__all__ = ["import_string", "import_string_uncached", "reset_import_cache", "IMPORT_CACHE"]


def reset_import_cache() -> None:
    """Clear the import cache. Primarily for tests or dynamic imports."""
    IMPORT_CACHE.clear()


def import_string(dotted_path: str) -> t.Callable[..., object]:
    """Import a class or function from a string path.

    Results are cached to avoid repeated imports of the same path.
    Failed imports are NOT cached so that transient sys.path issues
    (e.g. early startup calls before app directories are on sys.path)
    do not permanently poison the cache.

    Args:
        dotted_path: Dotted path to the class/function (e.g., "myapp.views.MyView")

    Returns:
        The imported class or function

    Raises:
        ImportError: If *dotted_path* is empty or has no dot separator.
    """
    if not dotted_path or "." not in dotted_path:
        raise ImportError(
            f"import_string requires a dotted path with at least one dot, got {dotted_path!r}"
        )
    if dotted_path in IMPORT_CACHE:
        return IMPORT_CACHE[dotted_path]
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    result = cast("t.Callable[..., object]", getattr(module, class_name))
    IMPORT_CACHE[dotted_path] = result
    return result


def import_string_uncached(dotted_path: str) -> t.Callable[..., object]:
    """Import a class or function from a string path without caching."""
    if not dotted_path or "." not in dotted_path:
        raise ImportError(
            "import_string_uncached requires a dotted path with at least one "
            f"dot, got {dotted_path!r}"
        )
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return cast("t.Callable[..., object]", getattr(module, class_name))
