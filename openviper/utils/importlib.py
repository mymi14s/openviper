from importlib import import_module
from typing import Any


def import_string(import_string: str) -> Any:
    module_path, class_name = import_string.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, class_name)
