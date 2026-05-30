"""Database routing package for read/write replica selection."""

from openviper.db.routing.admin import AdminRouter
from openviper.db.routing.base import DatabaseRouter
from openviper.db.routing.context import (
    current_db_alias,
    mark_write_used,
    read_from_primary,
    reset_current_alias,
    reset_routing_context,
    set_current_alias,
    write_used,
)
from openviper.db.routing.primary_replica import PrimaryReplicaRouter
from openviper.db.routing.resolver import DefaultRouterResolver, RouterResolver

__all__ = [
    "AdminRouter",
    "DatabaseRouter",
    "DefaultRouterResolver",
    "PrimaryReplicaRouter",
    "RouterResolver",
    "current_db_alias",
    "mark_write_used",
    "read_from_primary",
    "reset_current_alias",
    "reset_routing_context",
    "set_current_alias",
    "write_used",
]
