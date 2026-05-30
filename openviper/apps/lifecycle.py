"""App lifecycle hook discovery and execution for OpenViper."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from openviper.apps.exceptions import (
    AppLifecycleConfigError,
    AppLifecycleImportError,
    AppReadyError,
    AppShutdownError,
    AppStartupError,
)

ReadyHook = Callable[[], None]
AsyncLifecycleHook = Callable[[], Awaitable[None]]

logger = logging.getLogger("openviper.apps.lifecycle")


def is_plain_function(obj: object) -> bool:
    return isinstance(obj, type(lambda: None))


@dataclass(slots=True)
class AppLifecycle:
    app_name: str
    ready: ReadyHook | None = None
    startup: AsyncLifecycleHook | None = None
    shutdown: AsyncLifecycleHook | None = None


@dataclass
class AppLifecycleManager:
    lifecycles: list[AppLifecycle] = field(default_factory=list)
    lifecycle_index: dict[str, AppLifecycle] = field(default_factory=dict)
    started_apps: list[str] = field(default_factory=list)

    def discover(self, app_names: Sequence[str]) -> list[AppLifecycle]:
        self.lifecycles.clear()
        self.lifecycle_index.clear()
        self.started_apps.clear()
        for app_name in app_names:
            try:
                mod = importlib.import_module(f"{app_name}.lifecycle")
            except ModuleNotFoundError:
                continue
            except Exception as exc:
                raise AppLifecycleImportError(
                    f"App '{app_name}' lifecycle.py failed to import: {exc}"
                ) from exc
            lc = self.validate_and_create(app_name, mod)
            self.lifecycles.append(lc)
            self.lifecycle_index[app_name] = lc
        return list(self.lifecycles)

    def validate_and_create(self, app_name: str, module: object) -> AppLifecycle:
        lifecycle = AppLifecycle(app_name)
        ready = getattr(module, "ready", None)
        startup = getattr(module, "startup", None)
        shutdown = getattr(module, "shutdown", None)

        if ready is not None:
            lifecycle.ready = self.validate_sync_hook(app_name, "ready", ready)

        if startup is not None:
            lifecycle.startup = self.validate_async_hook(app_name, "startup", startup)

        if shutdown is not None:
            lifecycle.shutdown = self.validate_async_hook(app_name, "shutdown", shutdown)

        return lifecycle

    def validate_sync_hook(
        self, app_name: str, hook_name: str, hook: Callable[..., object]
    ) -> ReadyHook:
        if not callable(hook):
            raise AppLifecycleConfigError(f"App '{app_name}': '{hook_name}' is not callable.")
        if not is_plain_function(hook):
            raise AppLifecycleConfigError(
                f"App '{app_name}': '{hook_name}' must be a plain function."
            )
        if is_coroutine_function(hook):
            raise AppLifecycleConfigError(f"App '{app_name}': '{hook_name}' must not be async.")
        return hook

    def validate_async_hook(
        self, app_name: str, hook_name: str, hook: Callable[..., object]
    ) -> AsyncLifecycleHook:
        if not callable(hook):
            raise AppLifecycleConfigError(f"App '{app_name}': '{hook_name}' is not callable.")
        if not is_coroutine_function(hook):
            raise AppLifecycleConfigError(f"App '{app_name}': '{hook_name}' must be async.")
        return hook

    def run_ready(self) -> None:
        for lc in self.lifecycles:
            if lc.ready is None:
                continue
            try:
                lc.ready()
            except Exception as exc:
                raise AppReadyError(lc.app_name, exc) from exc

    async def run_startup(self) -> None:
        for lc in self.lifecycles:
            if lc.startup is None:
                continue
            try:
                await lc.startup()
            except Exception as exc:
                shutdown_errors = await self.shutdown_started()
                raise AppStartupError(lc.app_name, exc, shutdown_errors=shutdown_errors) from exc
            self.started_apps.append(lc.app_name)

    async def run_shutdown(self) -> None:
        errors = await self.shutdown_started()
        if errors:
            raise AppShutdownError(errors)

    async def shutdown_started(self) -> list[tuple[str, BaseException]]:
        errors: list[tuple[str, BaseException]] = []
        for app_name in reversed(self.started_apps):
            lc = self.find(app_name)
            if lc is None or lc.shutdown is None:
                continue
            try:
                await lc.shutdown()
            except Exception as exc:
                logger.error("shutdown() failed for '%s': %s", app_name, exc, exc_info=True)
                errors.append((app_name, exc))
        self.started_apps.clear()
        return errors

    def find(self, app_name: str) -> AppLifecycle | None:
        return self.lifecycle_index.get(app_name)


def is_coroutine_function(obj: object) -> bool:
    code = getattr(obj, "__code__", None)
    if code is None:
        return False
    return bool(code.co_flags & 0x180)
