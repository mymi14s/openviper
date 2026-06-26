"""Routing context variables for database alias tracking and read-your-writes."""

from __future__ import annotations

from contextvars import ContextVar, Token

DEFAULT_ALIAS: str = "default"

current_db_alias: ContextVar[str] = ContextVar("current_db_alias", default=DEFAULT_ALIAS)
read_from_primary: ContextVar[bool] = ContextVar("read_from_primary", default=False)
write_used: ContextVar[bool] = ContextVar("write_used", default=False)


def reset_routing_context() -> None:
    """Reset all routing context variables to their defaults.

    Call at the end of each request, background task, or test to
    prevent routing state from leaking between contexts.
    """
    current_db_alias.set(DEFAULT_ALIAS)
    read_from_primary.set(False)
    write_used.set(False)


def mark_write_used() -> None:
    """Mark the current context as having performed a write.

    When read-your-writes is enabled, subsequent reads will be
    routed to the primary database.
    """
    write_used.set(True)
    read_from_primary.set(True)


def set_current_alias(alias: str) -> Token[str]:
    """Pin the current database alias and return the reset token."""
    return current_db_alias.set(alias)


def reset_current_alias(token: Token[str]) -> None:
    """Reset the current database alias using a previously saved token."""
    current_db_alias.reset(token)
