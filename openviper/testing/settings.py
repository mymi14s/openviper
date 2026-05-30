"""Configuration and settings overrides for OpenViper tests."""

import copy
import dataclasses
import functools
import importlib
import inspect
import os
import tomllib
import typing as t
import warnings
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from openviper.app import OpenViper
from openviper.conf import Settings, settings
from openviper.conf.settings import configure_logging

DatabaseIsolation = t.Literal["transaction", "truncate", "recreate", "in_memory"]


class PytestConfigProtocol(t.Protocol):
    rootpath: Path


@dataclasses.dataclass(frozen=True, slots=True)
class OpenViperTestConfig:
    """Resolved pytest configuration for OpenViper test helpers."""

    app: str
    settings: str | None = None
    database_url: str | None = None
    database_isolation: DatabaseIsolation = "transaction"
    migrate: bool = True
    use_test_settings: bool = True
    disable_real_email: bool = True
    disable_real_tasks: bool = True
    disable_real_cache: bool = False


class OpenViperTestingConfigError(RuntimeError):
    """Raised when OpenViper testing configuration is invalid."""


@contextmanager
def override_openviper_settings(**overrides: object) -> Iterator[Settings]:
    """Temporarily replace OpenViper settings with dataclass overrides."""

    original_configured = bool(getattr(settings, "_configured", False))
    original_instance = t.cast("Settings | None", getattr(settings, "_instance", None))
    if original_instance is None:
        settings._setup()
        original_instance = t.cast("Settings", settings._instance)

    allowed_fields = {field.name for field in dataclasses.fields(original_instance)}
    invalid = sorted(name for name in overrides if name not in allowed_fields)
    if invalid:
        raise OpenViperTestingConfigError(
            "Unknown OpenViper setting override(s): " + ", ".join(invalid)
        )

    replacement = copy.deepcopy(original_instance)
    for name, value in overrides.items():
        object.__setattr__(replacement, name, value)
    object.__setattr__(settings, "_instance", replacement)
    object.__setattr__(settings, "_configured", True)
    configure_logging(replacement)
    try:
        yield replacement
    finally:
        object.__setattr__(settings, "_instance", original_instance)
        object.__setattr__(settings, "_configured", original_configured)
        configure_logging(original_instance)


def override_settings[CallableT: Callable[..., object]](
    **overrides: object,
) -> Callable[[CallableT], CallableT]:
    """Decorator that applies setting overrides for the duration of a test.

    Works on sync/async functions and test classes (wrapping methods
    whose names begin with ``test``).
    """

    def decorator(target: CallableT) -> CallableT:
        if isinstance(target, type):
            return wrap_test_class(target, overrides)
        return wrap_test_function(target, overrides)

    return decorator


def wrap_test_class[CallableT: Callable[..., object]](
    cls: CallableT, overrides: dict[str, object]
) -> CallableT:
    for attr_name in list(vars(cls)):
        if not attr_name.startswith("test"):
            continue
        method = getattr(cls, attr_name)
        if callable(method):
            setattr(cls, attr_name, wrap_test_function(method, overrides))
    return cls


def wrap_test_function[CallableT: Callable[..., object]](
    func: CallableT, overrides: dict[str, object]
) -> CallableT:
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: object, **kwargs: object) -> object:
            with override_openviper_settings(**overrides):
                result: object = func(*args, **kwargs)
                if isinstance(result, Awaitable):
                    return await result
                return result

        return t.cast("CallableT", async_wrapper)

    @functools.wraps(func)
    def sync_wrapper(*args: object, **kwargs: object) -> object:
        with override_openviper_settings(**overrides):
            return func(*args, **kwargs)

    return t.cast("CallableT", sync_wrapper)


def load_testing_config(pytest_config: PytestConfigProtocol) -> OpenViperTestConfig:
    """Load ``[tool.openviper.testing]`` from ``pyproject.toml``."""

    project_config = read_pyproject_testing_config(pytest_config.rootpath)
    env_app = os.environ.get("OPENVIPER_TEST_APP")
    app_path = env_app or as_optional_string(project_config.get("app"))
    if not app_path:
        raise OpenViperTestingConfigError(
            "OpenViper testing requires [tool.openviper.testing].app or OPENVIPER_TEST_APP."
        )

    isolation = as_database_isolation(project_config.get("database_isolation"))
    return OpenViperTestConfig(
        app=app_path,
        settings=as_optional_string(project_config.get("settings")),
        database_url=as_optional_string(project_config.get("database_url")),
        database_isolation=isolation,
        migrate=as_bool(project_config.get("migrate"), True),
        use_test_settings=as_bool(project_config.get("use_test_settings"), True),
        disable_real_email=as_bool(project_config.get("disable_real_email"), True),
        disable_real_tasks=as_bool(project_config.get("disable_real_tasks"), True),
        disable_real_cache=as_bool(project_config.get("disable_real_cache"), False),
    )


def read_pyproject_testing_config(root_path: Path) -> Mapping[str, object]:
    """Return testing config from pyproject, or an empty mapping."""

    pyproject_path = root_path / "pyproject.toml"
    if not pyproject_path.is_file():
        return {}
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    tool_config = as_mapping(data.get("tool"))
    openviper_config = as_mapping(tool_config.get("openviper"))
    return as_mapping(openviper_config.get("testing"))


async def load_app(config: OpenViperTestConfig) -> OpenViper:
    """Import and return the configured OpenViper app or app factory."""

    original_env: str | None = None
    if config.settings is not None:
        original_env = os.environ.get("OPENVIPER_SETTINGS_MODULE")
        os.environ["OPENVIPER_SETTINGS_MODULE"] = config.settings
        settings._setup(force=True)

    target = import_from_path(config.app)
    app_candidate = call_app_factory(target)
    if inspect.isawaitable(app_candidate):
        app_candidate = await app_candidate
    if not isinstance(app_candidate, OpenViper):
        raise OpenViperTestingConfigError(
            f"Configured app {config.app!r} did not resolve to an OpenViper instance."
        )
    app_candidate.debug = True
    app_candidate.invalidate_middleware_cache()

    if original_env is not None:
        os.environ["OPENVIPER_SETTINGS_MODULE"] = original_env
    else:
        os.environ.pop("OPENVIPER_SETTINGS_MODULE", None)

    return app_candidate


def import_from_path(path: str) -> object:
    """Import ``module:attribute`` or dotted ``module.attribute`` paths."""

    module_path, separator, attribute_path = path.partition(":")
    if not separator:
        module_path, separator, attribute_path = path.rpartition(".")
    if not module_path or not attribute_path:
        raise OpenViperTestingConfigError(f"Invalid import path {path!r}. Use 'module:attribute'.")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise OpenViperTestingConfigError(f"Could not import {module_path!r}: {exc}") from exc

    module_name = getattr(module, "__name__", "")
    if not module_name.startswith(("openviper.", "tests.")):
        warnings.warn(
            f"Importing test app from outside project namespace: {module_path!r}",
            stacklevel=2,
        )

    current: object = module
    for part in attribute_path.split("."):
        try:
            current = getattr(current, part)
        except AttributeError as exc:
            raise OpenViperTestingConfigError(
                f"Import path {path!r} has no attribute {part!r}."
            ) from exc
    return current


def call_app_factory(target: object) -> object:
    """Call zero-argument app factories while preserving app instances."""

    if isinstance(target, OpenViper) or not callable(target):
        return target
    candidate = t.cast("Callable[[], object]", target)
    signature = inspect.signature(candidate)
    required = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    ]
    if required:
        return target
    return candidate()


def as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return t.cast("Mapping[str, object]", value)
    return {}


def as_optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def as_database_isolation(value: object) -> DatabaseIsolation:
    if value in {"transaction", "truncate", "recreate", "in_memory"}:
        return t.cast("DatabaseIsolation", value)
    if value is None:
        return "transaction"
    raise OpenViperTestingConfigError(
        "database_isolation must be one of: transaction, truncate, recreate, in_memory."
    )
