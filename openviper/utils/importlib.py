from importlib import import_module


def import_string(import_string):
    module_path, class_name = import_string.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, class_name)
