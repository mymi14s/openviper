"""Authentication lifecycle hooks."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from openviper.auth.constants import SENSITIVE_CREDENTIAL_FIELDS
from openviper.auth.exceptions import (
    AuthHookConfigError,
    AuthHookError,
    AuthHookExecutionError,
    AuthHookReject,
)
from openviper.conf import settings

logger = logging.getLogger("openviper.auth.hooks")

type AuthHookPhase = Literal["before_login", "on_login", "on_logout"]
type AuthHookPolicy = Literal["raise", "log"]
type AuthHook = Callable[["AuthHookContext"], Awaitable[None] | None]

DEFAULT_AUTH_HOOK_POLICIES: dict[str, AuthHookPolicy] = {
    "before_login_error": "raise",
    "on_login_error": "log",
    "on_logout_error": "log",
}


@dataclass(slots=True)
class AuthHookContext:
    """Typed payload passed to authentication lifecycle hooks."""

    user: object | None = None
    credentials: dict[str, object] = field(default_factory=dict)
    request: object | None = None
    session: object | None = None
    token: object | None = None
    auth_backend: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class AuthHookRegistry:
    """Registry and executor for authentication lifecycle hooks."""

    def __init__(self) -> None:
        self._before_login: list[AuthHook] = []
        self._on_login: list[AuthHook] = []
        self._on_logout: list[AuthHook] = []

    def before_login(self, hook: AuthHook) -> AuthHook:
        """Register a before-login hook."""
        return self.register("before_login", hook)

    def on_login(self, hook: AuthHook) -> AuthHook:
        """Register a post-login hook."""
        return self.register("on_login", hook)

    def on_logout(self, hook: AuthHook) -> AuthHook:
        """Register a logout hook."""
        return self.register("on_logout", hook)

    def register(self, phase: AuthHookPhase, hook: AuthHook) -> AuthHook:
        """Register *hook* for the given lifecycle phase."""
        if not callable(hook):
            raise AuthHookConfigError("Auth hook must be callable.")
        self.hooks_for_phase(phase).append(hook)
        return hook

    def clear(self) -> None:
        """Remove all registered hooks from this registry."""
        self._before_login.clear()
        self._on_login.clear()
        self._on_logout.clear()

    async def run_before_login(self, context: AuthHookContext) -> None:
        """Run before-login hooks using the configured failure policy."""
        await self.run_hooks("before_login", context)

    async def run_on_login(self, context: AuthHookContext) -> None:
        """Run post-login hooks using the configured failure policy."""
        await self.run_hooks("on_login", context)

    async def run_on_logout(self, context: AuthHookContext) -> None:
        """Run logout hooks using the configured failure policy."""
        await self.run_hooks("on_logout", context)

    async def run_hooks(self, phase: AuthHookPhase, context: AuthHookContext) -> None:
        """Run hooks in registration order for *phase*."""
        policy = error_policy_for_phase(phase)
        for hook in tuple(self.hooks_for_phase(phase)):
            hook_name = hook_name_for_log(hook)
            try:
                result = hook(context)
                if inspect.isawaitable(result):
                    await result
            except AuthHookReject:
                if phase == "before_login":
                    raise
                logger.warning("Auth hook %s rejected outside before_login.", hook_name)
            except Exception as exc:
                handle_hook_error(phase, hook_name, policy, exc)

    def hooks_for_phase(self, phase: AuthHookPhase) -> list[AuthHook]:
        """Return the hook list for *phase*."""
        if phase == "before_login":
            return self._before_login
        if phase == "on_login":
            return self._on_login
        if phase == "on_logout":
            return self._on_logout
        raise AuthHookConfigError(f"Unknown auth hook phase: {phase!r}")


def register_auth_hook(phase: str, hook: AuthHook) -> AuthHook:
    """Register an authentication hook by phase name."""
    if phase not in {"before_login", "on_login", "on_logout"}:
        raise AuthHookConfigError(f"Unknown auth hook phase: {phase!r}")
    return auth_hooks.register(cast("AuthHookPhase", phase), hook)


def safe_credentials(credentials: Mapping[str, object] | None) -> dict[str, object]:
    """Return credentials with password, token, and secret fields removed."""
    if credentials is None:
        return {}
    safe: dict[str, object] = {}
    for key, value in credentials.items():
        normalized = key.lower()
        if normalized in SENSITIVE_CREDENTIAL_FIELDS:
            continue
        safe[key] = value
    return safe


def auth_request_metadata(request: object | None) -> dict[str, object]:
    """Build non-secret request metadata for hook contexts."""
    if request is None:
        return {}

    metadata: dict[str, object] = {}
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if isinstance(host, str) and host:
        metadata["client_ip"] = host

    headers = getattr(request, "headers", None)
    user_agent = headers.get("user-agent") if isinstance(headers, Mapping) else None
    if isinstance(user_agent, str) and user_agent:
        metadata["user_agent"] = user_agent
    return metadata


def build_auth_hook_context(
    *,
    user: object | None = None,
    credentials: Mapping[str, object] | None = None,
    request: object | None = None,
    session: object | None = None,
    token: object | None = None,
    auth_backend: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> AuthHookContext:
    """Build a sanitized authentication hook context."""
    merged_metadata = auth_request_metadata(request)
    if metadata is not None:
        merged_metadata.update(metadata)
    return AuthHookContext(
        user=user,
        credentials=safe_credentials(credentials),
        request=request,
        session=session,
        token=token,
        auth_backend=auth_backend,
        metadata=merged_metadata,
    )


def error_policy_for_phase(phase: AuthHookPhase) -> AuthHookPolicy:
    """Return the configured error policy for a hook phase."""
    try:
        config = getattr(settings, "AUTH_HOOKS", {}) or {}
    except Exception:
        config = {}
    if not isinstance(config, dict):
        config = {}
    key = f"{phase}_error"
    policy = config.get(key, DEFAULT_AUTH_HOOK_POLICIES[key])
    if policy not in {"raise", "log"}:
        return DEFAULT_AUTH_HOOK_POLICIES[key]
    return cast("AuthHookPolicy", policy)


def hook_name_for_log(hook: AuthHook) -> str:
    """Return a non-secret hook name for log messages."""
    return getattr(hook, "__qualname__", getattr(hook, "__name__", hook.__class__.__name__))


def handle_hook_error(
    phase: AuthHookPhase,
    hook_name: str,
    policy: AuthHookPolicy,
    exc: Exception,
) -> None:
    """Apply a hook failure policy without logging credentials."""
    if policy == "log":
        logger.error(
            "Auth hook failed: phase=%s hook=%s error_class=%s",
            phase,
            hook_name,
            exc.__class__.__name__,
        )
        return
    message = f"Auth hook failed: phase={phase} hook={hook_name}"
    raise AuthHookExecutionError(message) from exc


auth_hooks = AuthHookRegistry()

__all__ = [
    "AuthHook",
    "AuthHookConfigError",
    "AuthHookContext",
    "AuthHookError",
    "AuthHookExecutionError",
    "AuthHookPhase",
    "AuthHookPolicy",
    "AuthHookRegistry",
    "AuthHookReject",
    "auth_hooks",
    "auth_request_metadata",
    "build_auth_hook_context",
    "register_auth_hook",
    "safe_credentials",
]
